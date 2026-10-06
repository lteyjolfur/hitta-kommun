"""Shapefile -> simplified WGS84 GeoJSON. Only used when (re)building map data."""

SWEREF99_TM = "EPSG:3006"
# Rough extent of Sweden in SWEREF 99 TM, to catch a file in another projection.
SWEDEN_BOUNDS = (180_000, 6_100_000, 1_000_000, 7_700_000)


def shapefile_to_geojson(path, tolerance_m):
    import shapefile
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

    to_wgs84 = Transformer.from_crs(SWEREF99_TM, "EPSG:4326", always_xy=True).transform
    features, kommuner = [], {}
    for record in reader.iterShapeRecords():
        code = record.record["KnKod"].strip()
        name = record.record["KnNamn"].strip()
        geom = shape(record.shape.__geo_interface__).simplify(tolerance_m, preserve_topology=True)
        geom = transform(to_wgs84, geom)
        features.append(
            {
                "type": "Feature",
                "properties": {"code": code, "name": name},
                "geometry": _round(mapping(geom), 4),
            }
        )
        kommuner[code] = name
    return {"type": "FeatureCollection", "features": features}, kommuner


def _round(geometry, digits):
    def walk(coords):
        if isinstance(coords[0], (int, float)):
            return [round(c, digits) for c in coords]
        return [walk(c) for c in coords]

    return {"type": geometry["type"], "coordinates": walk(geometry["coordinates"])}
