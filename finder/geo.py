"""Shapefile -> simplified WGS84 GeoJSON. Only used when (re)building map data.

Kommuner are simplified as a *coverage*: shared borders are simplified once,
so neighbours still meet exactly (no hairline gaps or overlaps). Län outlines
are the union of their kommuner (the first two digits of a kommun code are the
län code), which gives clean county borders and the coastline for free.
"""

SWEREF99_TM = "EPSG:3006"
# Rough extent of Sweden in SWEREF 99 TM, to catch a file in another projection.
SWEDEN_BOUNDS = (180_000, 6_100_000, 1_000_000, 7_700_000)
# Overlaps smaller than this (m²) are rounding noise and left alone.
MIN_OVERLAP_M2 = 1.0


def remove_overlaps(geoms):
    """Give any area claimed by two polygons to the one that comes first.

    Returns the fixed list and the (i, j, area) overlaps that were removed.
    """
    import shapely

    geoms = list(geoms)
    tree = shapely.STRtree(geoms)
    removed = []
    for i, j in zip(*tree.query(geoms, predicate="overlaps"), strict=True):
        if i >= j:
            continue
        overlap = shapely.intersection(geoms[i], geoms[j]).area
        if overlap > MIN_OVERLAP_M2:
            geoms[j] = shapely.make_valid(shapely.difference(geoms[j], geoms[i]))
            # Overlaying i with the new j adds the new corner points to i's
            # side of the border too, so both sides match vertex for vertex.
            geoms[i] = shapely.make_valid(shapely.difference(geoms[i], geoms[j]))
            removed.append((int(i), int(j), overlap))
    return geoms, removed


def shapefile_to_geojson(path, tolerance_m):
    """Return (kommun FeatureCollection, län FeatureCollection, {code: name}, warnings)."""
    import numpy as np
    import shapefile
    import shapely
    from pyproj import Transformer
    from shapely.geometry import mapping, shape
    from shapely.ops import transform

    reader = shapefile.Reader(path, encoding="latin1")
    fields = [f[0] for f in reader.fields[1:]]
    if "KnKod" not in fields or "KnNamn" not in fields:
        raise ValueError(f"expected KnKod and KnNamn fields, found {fields}")

    minx, miny, maxx, maxy = reader.bbox
    bx0, by0, bx1, by1 = SWEDEN_BOUNDS
    if not (bx0 <= minx and maxx <= bx1 and by0 <= miny and maxy <= by1):
        raise ValueError(f"bounding box {reader.bbox} does not look like Sweden in SWEREF 99 TM")

    codes, names, geoms = [], [], []
    for record in reader.iterShapeRecords():
        codes.append(record.record["KnKod"].strip())
        names.append(record.record["KnNamn"].strip())
        geoms.append(shape(record.shape.__geo_interface__))

    geoms, removed = remove_overlaps(geoms)
    warnings = [f"{names[j]} overlapped {names[i]} by {area:,.0f} m²; gave it to {names[i]}" for i, j, area in removed]
    coverage = np.array(geoms, dtype=object)
    if not shapely.coverage_is_valid(coverage):
        raise ValueError("kommun polygons still overlap after cleaning; check the shapefile")
    simplified = shapely.coverage_simplify(coverage, tolerance_m)

    to_wgs84 = Transformer.from_crs(SWEREF99_TM, "EPSG:4326", always_xy=True).transform

    def feature(geom, properties):
        return {
            "type": "Feature",
            "properties": properties,
            "geometry": _round(mapping(transform(to_wgs84, geom)), 4),
        }

    kommun_features = [
        feature(geom, {"code": code, "name": name}) for code, name, geom in zip(codes, names, simplified, strict=True)
    ]

    by_lan = {}
    for code, geom in zip(codes, simplified, strict=True):
        by_lan.setdefault(code[:2], []).append(geom)
    lan_features = [
        feature(shapely.coverage_union_all(np.array(parts, dtype=object)), {"code": lan})
        for lan, parts in sorted(by_lan.items())
    ]

    return (
        {"type": "FeatureCollection", "features": kommun_features},
        {"type": "FeatureCollection", "features": lan_features},
        dict(zip(codes, names, strict=True)),
        warnings,
    )


def _round(geometry, digits):
    def walk(coords):
        if isinstance(coords[0], (int, float)):
            return [round(c, digits) for c in coords]
        return [walk(c) for c in coords]

    if geometry["type"] == "GeometryCollection":
        raise ValueError("unexpected GeometryCollection after simplification")
    return {"type": geometry["type"], "coordinates": walk(geometry["coordinates"])}
