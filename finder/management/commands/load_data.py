from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from finder.models import Indicator, Kommun, Value
from finder.sources import SourceError, read_indicators_json, read_kommuner_csv, read_values_csv


class Command(BaseCommand):
    help = "Replace the database contents with data/kommuner.csv, data/indicators.json and data/values/*.csv."

    def handle(self, **options):
        data_dir = settings.DATA_DIR
        try:
            kommuner = read_kommuner_csv(data_dir / "kommuner.csv")
            indicators = read_indicators_json(data_dir / "indicators.json")
            loaded = []
            for meta in indicators:
                path = data_dir / meta["file"]
                if not path.exists():
                    loaded.append((meta, {}))
                    continue
                values = read_values_csv(path)
                unknown = sorted(set(values) - set(kommuner))
                if unknown:
                    raise SourceError(f"{meta['file']}: unknown kommun codes {unknown[:5]}")
                loaded.append((meta, values))
        except (SourceError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        with transaction.atomic():
            Value.objects.all().delete()
            Indicator.objects.all().delete()
            Kommun.objects.all().delete()
            Kommun.objects.bulk_create(Kommun(code=c, name=n) for c, n in kommuner.items())
            for position, (meta, values) in enumerate(loaded):
                fields = {k: v for k, v in meta.items() if k != "file"}
                indicator = Indicator.objects.create(position=position, **fields)
                Value.objects.bulk_create(
                    Value(kommun_id=code, indicator=indicator, value=v) for code, v in values.items()
                )
                note = "" if values else f" ({meta['file']} not found, shown as 'no data')"
                self.stdout.write(f"{indicator.slug}: {len(values)}/{len(kommuner)} kommuner{note}")
        self.stdout.write(f"loaded {len(kommuner)} kommuner, {len(loaded)} indicators")
