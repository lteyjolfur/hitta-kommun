from collections import defaultdict

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Dimension, Indicator, Kommun, Value
from .scoring import dimension_scores, rank

MAX_WEIGHT = 10
DEFAULT_WEIGHT = 5


def _catalog():
    """Dimensions with their indicators, as plain dicts, and whether each has data."""
    with_data = set(Value.objects.values_list("indicator_id", flat=True).distinct())
    indicators_by_dim = defaultdict(list)
    for ind in Indicator.objects.all():
        indicators_by_dim[ind.dimension_id].append(
            {
                "slug": ind.slug,
                "name": ind.name,
                "unit": ind.unit,
                "year": ind.year,
                "lower_is_better": ind.lower_is_better,
                "source": ind.source,
                "source_url": ind.source_url,
                "has_data": ind.slug in with_data,
            }
        )
    return [
        {
            "slug": dim.slug,
            "name": dim.name,
            "description": dim.description,
            "indicators": indicators_by_dim[dim.slug],
            "has_data": any(i["has_data"] for i in indicators_by_dim[dim.slug]),
        }
        for dim in Dimension.objects.all()
    ]


@require_GET
def index(request):
    return render(
        request,
        "finder/index.html",
        {"dimensions": _catalog(), "max_weight": MAX_WEIGHT, "default_weight": DEFAULT_WEIGHT},
    )


def parse_weights(params, slugs):
    """Read w_<dimension>=<0..MAX_WEIGHT> query params. Returns (weights, error)."""
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
        return None, f"unknown dimension(s): {', '.join(unknown)}"
    return weights, None


@require_GET
def api_rank(request):
    dimension_slugs = list(Dimension.objects.values_list("slug", flat=True))
    weights, error = parse_weights(request.GET, dimension_slugs)
    if error:
        return JsonResponse({"error": error}, status=400)

    indicators = list(Indicator.objects.all())
    values = defaultdict(dict)
    for slug, code, value in Value.objects.values_list("indicator_id", "kommun_id", "value"):
        values[slug][code] = value
    names = dict(Kommun.objects.values_list("code", "name"))

    dim_scores = dimension_scores(
        codes=list(names),
        values=values,
        lower_is_better={i.slug: i.lower_is_better for i in indicators},
        dimension_of={i.slug: i.dimension_id for i in indicators},
    )
    results = rank(list(names), dim_scores, weights)
    return JsonResponse(
        {
            "results": [
                {
                    "code": r.code,
                    "name": names[r.code],
                    "score": None if r.score is None else round(r.score, 4),
                    "parts": {d: round(s, 4) for d, s in r.parts.items()},
                    "missing": r.missing,
                    "values": {i.slug: values[i.slug].get(r.code) for i in indicators},
                }
                for r in results
            ]
        }
    )
