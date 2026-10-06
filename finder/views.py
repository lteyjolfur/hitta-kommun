from collections import defaultdict

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Indicator, Kommun, Value
from .scoring import rank

MAX_WEIGHT = 10


def _indicator_json(indicator, has_data):
    return {
        "has_data": has_data,
        "slug": indicator.slug,
        "name": indicator.name,
        "unit": indicator.unit,
        "year": indicator.year,
        "lower_is_better": indicator.lower_is_better,
        "source": indicator.source,
        "source_url": indicator.source_url,
    }


@require_GET
def index(request):
    with_data = set(Value.objects.values_list("indicator_id", flat=True).distinct())
    indicators = [_indicator_json(i, i.slug in with_data) for i in Indicator.objects.all()]
    return render(request, "finder/index.html", {"indicators": indicators, "max_weight": MAX_WEIGHT})


def parse_weights(params, slugs):
    """Read w_<slug>=<0..MAX_WEIGHT> query params. Returns (weights, error)."""
    weights = {}
    for slug in slugs:
        raw = params.get(f"w_{slug}", "0")
        try:
            weight = float(raw)
        except ValueError:
            return None, f"w_{slug} must be a number"
        if not 0 <= weight <= MAX_WEIGHT:
            return None, f"w_{slug} must be between 0 and {MAX_WEIGHT}"
        weights[slug] = weight
    unknown = sorted(k for k in params if k.startswith("w_") and k[2:] not in slugs)
    if unknown:
        return None, f"unknown indicator(s): {', '.join(unknown)}"
    return weights, None


@require_GET
def api_rank(request):
    indicators = {i.slug: i for i in Indicator.objects.all()}
    weights, error = parse_weights(request.GET, indicators)
    if error:
        return JsonResponse({"error": error}, status=400)

    values = defaultdict(dict)
    for slug, code, value in Value.objects.values_list("indicator_id", "kommun_id", "value"):
        values[slug][code] = value
    names = dict(Kommun.objects.values_list("code", "name"))

    results = rank(
        codes=list(names),
        values=values,
        lower_is_better={slug: i.lower_is_better for slug, i in indicators.items()},
        weights=weights,
    )
    return JsonResponse(
        {
            "results": [
                {
                    "code": r.code,
                    "name": names[r.code],
                    "score": None if r.score is None else round(r.score, 4),
                    "parts": {slug: round(s, 4) for slug, s in r.parts.items()},
                    "missing": r.missing,
                    "values": {slug: values[slug].get(r.code) for slug in indicators},
                }
                for r in results
            ]
        }
    )
