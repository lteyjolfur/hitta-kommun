from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from finder.models import Dimension, Indicator, Kommun, Value
from finder.sources import (
    SourceError,
    read_dimensions_json,
    read_indicators_json,
    read_kommuner_csv,
    read_values_csv,
)

INDICATOR_MODEL_FIELDS = {"slug", "name", "unit", "year", "lower_is_better", "source", "source_url"}


def derive(numerator, denominator):
    """{code: numerator / denominator} for kommuner that have both (and a non-zero denominator)."""
    return {
        code: numerator[code] / denominator[code] for code in numerator.keys() & denominator.keys() if denominator[code]
    }


def check_range(meta, values):
    lo, hi = meta["range"]
    outside = sorted((code, v) for code, v in values.items() if not lo <= v <= hi)
    if outside:
        sample = ", ".join(f"{code}={v:g}" for code, v in outside[:5])
        raise SourceError(f"{meta['slug']}: {len(outside)} values outside the plausible range [{lo}, {hi}]: {sample}")


class Command(BaseCommand):
    help = "Replace the database contents with data/: kommuner, dimensions, indicators and their values."

    def handle(self, **options):
        data_dir = settings.DATA_DIR
        try:
            kommuner = read_kommuner_csv(data_dir / "kommuner.csv")
            dimensions = read_dimensions_json(data_dir / "dimensions.json")
            indicators = read_indicators_json(data_dir / "indicators.json", {d["slug"] for d in dimensions})

            values = {}
            for meta in indicators:
                if "file" not in meta:
                    continue
                path = data_dir / meta["file"]
                values[meta["slug"]] = read_values_csv(path) if path.exists() else {}
                unknown = sorted(set(values[meta["slug"]]) - set(kommuner))
                if unknown:
                    raise SourceError(f"{meta['file']}: unknown kommun codes {unknown[:5]}")
            for meta in indicators:
                if "derived" in meta:
                    parts = meta["derived"]
                    values[meta["slug"]] = derive(values[parts["numerator"]], values[parts["denominator"]])
            for meta in indicators:
                check_range(meta, values[meta["slug"]])
        except (SourceError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        with transaction.atomic():
            Value.objects.all().delete()
            Indicator.objects.all().delete()
            Dimension.objects.all().delete()
            Kommun.objects.all().delete()
            Kommun.objects.bulk_create(Kommun(code=c, name=n) for c, n in kommuner.items())
            Dimension.objects.bulk_create(Dimension(position=i, **d) for i, d in enumerate(dimensions))
            for position, meta in enumerate(indicators):
                fields = {k: v for k, v in meta.items() if k in INDICATOR_MODEL_FIELDS}
                indicator = Indicator.objects.create(position=position, dimension_id=meta["dimension"], **fields)
                rows = values[meta["slug"]]
                Value.objects.bulk_create(
                    Value(kommun_id=code, indicator=indicator, value=v) for code, v in rows.items()
                )
                note = "" if rows else " (no data yet, shown as 'no data')"
                self.stdout.write(f"{meta['dimension']}/{indicator.slug}: {len(rows)}/{len(kommuner)} kommuner{note}")
        self.stdout.write(
            f"loaded {len(kommuner)} kommuner, {len(dimensions)} dimensions, {len(indicators)} indicators"
        )
