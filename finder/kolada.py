"""Fetch indicators from Kolada (https://www.kolada.se), RKA's open database of kommun statistics.

API v3: GET {base}/kpi/{id}, {base}/kpi?title=..., {base}/data?kpi_id=...&year=...
Responses are {"values": [...], "next_url": ...}; data rows look like
{"kpi": "N00900", "municipality": "0114", "period": 2024,
 "values": [{"gender": "T", "value": 33.1, "status": "", "count": 1}]}.

Everything here takes a `get(path, params) -> dict` callable so tests can
replace the network with saved responses.
"""

import json
import time
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://api.kolada.se/v3/"
MIN_COVERAGE = 250  # of 290 kommuner; below this a year is treated as not published yet
YEARS_BACK = 6
# KPI municipality_type: "K" kommun only, "L" region only, "A" both.
KOMMUN_TYPES = {"K", "A"}


class KoladaError(RuntimeError):
    pass


def http_getter(base_url=DEFAULT_BASE_URL, timeout=30, retries=3):
    """Return get(path_or_url, params) that fetches JSON, retrying on transient errors."""

    def get(path, params=None):
        url = path if path.startswith("http") else urllib.parse.urljoin(base_url, path)
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "hitta-kommun"})
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.load(response)
            except (OSError, json.JSONDecodeError) as exc:
                if attempt == retries - 1:
                    raise KoladaError(f"GET {url} failed: {exc}") from exc
                time.sleep(2**attempt)

    return get


def _all_values(get, path, params=None):
    """Follow next_url pagination and return the concatenated "values" lists."""
    response = get(path, params)
    rows = list(response.get("values", []))
    while response.get("next_url"):
        response = get(response["next_url"])
        rows.extend(response.get("values", []))
    return rows


def resolve_kpi(get, spec):
    """Return (kpi_id, title) for a {"kpi": ...} and/or {"search": ...} spec.

    With only a search term, exactly one KPI with kommun data must match;
    otherwise the error lists the candidates so the right id can be pinned in
    data/indicators.json. With both, the pinned KPI's title must contain the
    search term, which catches a wrong or reused id.
    """
    if "kpi" in spec:
        response = get(f"kpi/{spec['kpi']}")
        # Accept both {"values": [kpi]} and a bare kpi object.
        rows = response.get("values", [response] if "id" in response else [])
        if not rows:
            raise KoladaError(f"Kolada has no KPI {spec['kpi']}")
        kpi_id, title = rows[0]["id"], rows[0]["title"]
        if "search" in spec and spec["search"].lower() not in title.lower():
            raise KoladaError(f"{kpi_id} is titled {title!r}, which does not contain {spec['search']!r}")
        return kpi_id, title

    rows = _all_values(get, "kpi", {"title": spec["search"]})
    candidates = [r for r in rows if r.get("municipality_type", "K") in KOMMUN_TYPES]
    if len(candidates) == 1:
        return candidates[0]["id"], candidates[0]["title"]
    if not candidates and rows:
        other = ", ".join(f"{r['id']} ({r.get('municipality_type')}): {r['title']}" for r in rows[:5])
        raise KoladaError(f"search {spec['search']!r} only matched KPIs without kommun data: {other}")
    listing = "\n".join(f"  {r['id']}: {r['title']}" for r in candidates[:15])
    more = f"\n  ... and {len(candidates) - 15} more" if len(candidates) > 15 else ""
    raise KoladaError(
        f"search {spec['search']!r} matched {len(candidates)} kommun KPIs; "
        f'pin one with "kpi" in data/indicators.json:\n{listing}{more}'
    )


def fetch_year(get, kpi_id, year, kommun_codes):
    """Return {code: value} for one KPI and year, total for both genders, kommuner only."""
    values = {}
    for row in _all_values(get, "data", {"kpi_id": kpi_id, "year": year, "per_page": 5000}):
        code = row.get("municipality")
        if code not in kommun_codes:
            continue  # "0000" (Riket), län, or groups
        for entry in row.get("values", []):
            if entry.get("gender", "T") == "T" and entry.get("value") is not None and not entry.get("isdeleted"):
                values[code] = float(entry["value"])
    return values


def latest_year(get, kpi_id, kommun_codes, this_year, min_coverage=None):
    """Return (year, {code: value}) for the newest year with data for at least min_coverage kommuner."""
    min_coverage = MIN_COVERAGE if min_coverage is None else min_coverage
    tried = []
    for year in range(this_year, this_year - YEARS_BACK, -1):
        values = fetch_year(get, kpi_id, year, kommun_codes)
        if len(values) >= min_coverage:
            return year, values
        tried.append(f"{year}: {len(values)}")
    raise KoladaError(f"{kpi_id}: no year with at least {min_coverage} kommuner ({', '.join(tried)})")
