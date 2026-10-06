from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from finder.sources import SourceError, parse_scb_region_csv, write_values_csv


class Command(BaseCommand):
    help = "Convert an SCB house price export (CSV, one value per kommun) into data/values/house-price.csv."

    def add_arguments(self, parser):
        parser.add_argument("csv_file", help="path to the CSV exported from Statistikdatabasen")

    def handle(self, csv_file, **options):
        try:
            values = parse_scb_region_csv(csv_file)
        except (SourceError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        out = settings.DATA_DIR / "values" / "house-price.csv"
        write_values_csv(out, values)
        self.stdout.write(f"house-price: {len(values)} kommuner -> {out.relative_to(settings.BASE_DIR)}")
        self.stdout.write("Check the year in data/indicators.json matches the export.")
