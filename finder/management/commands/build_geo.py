import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from finder.geo import shapefile_to_geojson

STATIC_DIR = "finder/static/finder"


class Command(BaseCommand):
    help = "Convert a SWEREF 99 TM kommun shapefile into kommuner.geojson, lan.geojson and data/kommuner.csv."

    def add_arguments(self, parser):
        parser.add_argument("shapefile", help="path to the .shp (with .dbf/.shx next to it)")
        parser.add_argument("--tolerance", type=float, default=400, help="simplification in metres (default 400)")

    def handle(self, shapefile, tolerance, **options):
        try:
            kommuner_geojson, lan_geojson, kommuner, warnings = shapefile_to_geojson(shapefile, tolerance)
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        for warning in warnings:
            self.stdout.write(f"note: {warning}")

        for filename, geojson in [("kommuner.geojson", kommuner_geojson), ("lan.geojson", lan_geojson)]:
            out = settings.BASE_DIR / STATIC_DIR / filename
            out.write_text(json.dumps(geojson, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            count = len(geojson["features"])
            self.stdout.write(f"{count} features -> {STATIC_DIR}/{filename} ({out.stat().st_size // 1024} KB)")

        csv_path = settings.DATA_DIR / "kommuner.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            f.write("code,name\n")
            for code in sorted(kommuner):
                f.write(f"{code},{kommuner[code]}\n")
        self.stdout.write(f"{len(kommuner)} kommuner -> data/kommuner.csv")
