"""Turn raw indicator values and user weights into a ranking.

Plain functions with no Django imports, so the maths is easy to test and reason
about. The app never decides what "good" means on its own: each dimension
only counts as much as the user's weight says.

Scoring has two levels:
1. Each indicator is min-max scaled to 0..1 (1 = the preferred end).
2. A dimension's sub-score is the mean of its indicators' scores (weighted by
   the user's indicator weights, equal by default), and the kommun's score is
   the weighted mean of its dimension sub-scores.
"""

from dataclasses import dataclass, field


@dataclass
class Result:
    code: str
    score: float | None  # 0..1, higher = better match; None when no weighted data
    parts: dict[str, float] = field(default_factory=dict)  # dimension -> 0..1 sub-score
    missing: list[str] = field(default_factory=list)  # weighted dimensions with no data for this kommun


def normalize(values, lower_is_better):
    """Min-max scale {code: value} to 0..1 where 1 is the preferred end."""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {code: 1.0 for code in values}
    scaled = {code: (v - lo) / (hi - lo) for code, v in values.items()}
    if lower_is_better:
        scaled = {code: 1.0 - s for code, s in scaled.items()}
    return scaled


def dimension_scores(codes, values, lower_is_better, dimension_of, indicator_weights=None):
    """Return {dimension: {code: 0..1}}: the mean of each kommun's indicator scores.

    `indicator_weights` ({indicator: weight}) turns the plain mean into a
    weighted one; indicators not listed count with weight 1 and indicators
    with weight 0 are left out. A kommun missing one indicator in a dimension
    is scored on the others; a kommun missing all of them gets no entry for
    that dimension.
    """
    indicator_weights = indicator_weights or {}
    by_dimension = {}
    for slug, raw in values.items():
        weight = indicator_weights.get(slug, 1)
        if raw and weight > 0:
            by_dimension.setdefault(dimension_of[slug], []).append((normalize(raw, lower_is_better[slug]), weight))
    result = {}
    for dimension, scaled_list in by_dimension.items():
        scores = {}
        for code in codes:
            present = [(scaled[code], weight) for scaled, weight in scaled_list if code in scaled]
            if present:
                scores[code] = sum(s * w for s, w in present) / sum(w for _, w in present)
        result[dimension] = scores
    return result


def rank(codes, dim_scores, weights):
    """Score every kommun in `codes` from dimension_scores() output and {dimension: weight}.

    Dimensions with weight 0 or no data are ignored. Missing dimensions are
    listed so the UI can say so instead of silently treating them as zero.
    """
    active = {d: w for d, w in weights.items() if w > 0 and dim_scores.get(d)}

    results = []
    for code in codes:
        parts = {d: dim_scores[d][code] for d in active if code in dim_scores[d]}
        missing = [d for d in active if d not in parts]
        total_weight = sum(active[d] for d in parts)
        score = sum(parts[d] * active[d] for d in parts) / total_weight if total_weight else None
        results.append(Result(code=code, score=score, parts=parts, missing=missing))

    # Best first; kommuner without a score go last, alphabetically by code.
    results.sort(key=lambda r: (r.score is None, -(r.score or 0), r.code))
    return results
