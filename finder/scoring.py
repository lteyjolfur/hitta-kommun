"""Turn raw indicator values and user weights into a ranking.

Plain functions with no Django imports, so the maths is easy to test and reason
about. The app never decides what "good" means on its own: every indicator
only counts as much as the user's weight says.
"""

from dataclasses import dataclass, field


@dataclass
class Result:
    code: str
    score: float | None  # 0..1, higher = better match; None when no weighted data
    parts: dict[str, float] = field(default_factory=dict)  # slug -> 0..1 sub-score
    missing: list[str] = field(default_factory=list)  # weighted slugs with no value


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


def rank(codes, values, lower_is_better, weights):
    """Score every kommun in `codes`.

    values: {slug: {code: raw value}}
    lower_is_better: {slug: bool}
    weights: {slug: non-negative number}; slugs with weight 0 are ignored.

    A kommun's score is the weighted mean of its sub-scores over the indicators
    it has data for. Missing indicators are listed so the UI can say so instead
    of silently treating them as zero.
    """
    active = {slug: w for slug, w in weights.items() if w > 0 and values.get(slug)}
    scaled = {slug: normalize(values[slug], lower_is_better[slug]) for slug in active}

    results = []
    for code in codes:
        parts, missing = {}, []
        for slug in active:
            if code in scaled[slug]:
                parts[slug] = scaled[slug][code]
            else:
                missing.append(slug)
        total_weight = sum(active[s] for s in parts)
        score = sum(parts[s] * active[s] for s in parts) / total_weight if total_weight else None
        results.append(Result(code=code, score=score, parts=parts, missing=missing))

    # Best first; kommuner without a score go last, alphabetically by code.
    results.sort(key=lambda r: (r.score is None, -(r.score or 0), r.code))
    return results
