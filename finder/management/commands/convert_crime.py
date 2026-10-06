from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from finder.sources import SourceError, parse_crime_workbook, write_values_csv


class Command(BaseCommand):
    help = "Convert the Öppna jämförelser Trygghet och säkerhet workbook (.xlsx) into data/values/*.csv."

    def add_arguments(self, parser):
        parser.add_argument("workbook", help="path to the downloaded .xlsx")

    def handle(self, workbook, **options):
        try:
            parsed = parse_crime_workbook(workbook)
        except (SourceError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        for slug, values in parsed.items():
            out = settings.DATA_DIR / "values" / f"{slug}.csv"
            write_values_csv(out, values)
            self.stdout.write(f"{slug}: {len(values)} kommuner -> {out.relative_to(settings.BASE_DIR)}")
