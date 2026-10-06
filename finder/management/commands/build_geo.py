import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from finder.geo import shapefile_to_geojson

GEOJSON_PATH = "finder/static/finder/kommuner.geojson"


class Command(BaseCommand):
    help = "Convert a SWEREF 99 TM kommun shapefile into kommuner.geojson and data/kommuner.csv."

    def add_arguments(self, parser):
        parser.add_argument("shapefile", help="path to the .shp (with .dbf/.shx next to it)")
        parser.add_argument("--tolerance", type=float, default=400, help="simplification in metres (default 400)")

    def handle(self, shapefile, tolerance, **options):
        try:
            geojson, kommuner = shapefile_to_geojson(shapefile, tolerance)
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        out = settings.BASE_DIR / GEOJSON_PATH
        out.write_text(json.dumps(geojson, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        csv_path = settings.DATA_DIR / "kommuner.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            f.write("code,name\n")
            for code in sorted(kommuner):
                f.write(f"{code},{kommuner[code]}\n")
        size_kb = out.stat().st_size // 1024
        self.stdout.write(f"{len(kommuner)} kommuner -> {GEOJSON_PATH} ({size_kb} KB) and data/kommuner.csv")
