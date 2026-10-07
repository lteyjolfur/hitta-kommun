import datetime
import statistics

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from finder import kolada
from finder.kolada import DEFAULT_BASE_URL, KoladaError, latest_year, resolve_kpi
from finder.sources import (
    SourceError,
    read_dimensions_json,
    read_indicators_json,
    read_kommuner_csv,
    read_values_csv,
    write_indicators_json,
    write_values_csv,
)


class Command(BaseCommand):
    help = (
        "Fetch every indicator in data/indicators.json that has a 'kolada' entry, write data/values/<slug>.csv "
        "and update the year, source and pinned KPI id. Fails without writing anything if any check fails."
    )

    def add_arguments(self, parser):
        parser.add_argument("--only", action="append", default=[], help="indicator slug (repeatable)")
        parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
        parser.add_argument("--summary", help="also write a Markdown summary of the changes to this file")
        parser.add_argument("--year", type=int, default=datetime.date.today().year, help="newest year to try")
        parser.add_argument(
            "--allow-partial",
            action="store_true",
            help="write the indicators that passed and list the failures in the summary (fails if none passed)",
        )

    def handle(self, only, base_url, summary, year, allow_partial, **options):
        get = kolada.http_getter(base_url)  # tests patch finder.kolada.http_getter
        data_dir = settings.DATA_DIR
        try:
            kommuner = read_kommuner_csv(data_dir / "kommuner.csv")
            dimensions = read_dimensions_json(data_dir / "dimensions.json")
            indicators = read_indicators_json(data_dir / "indicators.json", {d["slug"] for d in dimensions})
        except (SourceError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        targets = [m for m in indicators if "kolada" in m and (not only or m["slug"] in only)]
        unknown = set(only) - {m["slug"] for m in targets}
        if unknown:
            raise CommandError(f"not Kolada indicators: {sorted(unknown)}")

        # Fetch and check everything first; by default write only if all indicators pass.
        fetched, errors = [], []
        for meta in targets:
            try:
                kpi_id, title = resolve_kpi(get, meta["kolada"])
                data_year, values = latest_year(get, kpi_id, set(kommuner), year)
                lo, hi = meta["range"]
                outside = sorted((c, v) for c, v in values.items() if not lo <= v <= hi)
                if outside:
                    sample = ", ".join(f"{c}={v:g}" for c, v in outside[:5])
                    raise KoladaError(f"{kpi_id} ({title}): {len(outside)} values outside [{lo}, {hi}]: {sample}")
                fetched.append((meta, kpi_id, title, data_year, values))
                self.stdout.write(f"{meta['slug']}: {kpi_id} {title!r}, {data_year}, {len(values)} kommuner")
            except KoladaError as exc:
                errors.append(f"{meta['slug']}: {exc}")
        if errors and not (allow_partial and fetched):
            raise CommandError("Kolada import failed, nothing written:\n" + "\n".join(errors))

        lines = ["| Indikator | KPI | År | Kommuner | Median | Förra medianen |", "|---|---|---|---|---|---|"]
        for meta, kpi_id, title, data_year, values in fetched:
            path = data_dir / meta["file"]
            old = read_values_csv(path) if path.exists() else {}
            old_median = f"{statistics.median(old.values()):g} ({meta['year']})" if old else "–"
            lines.append(
                f"| {meta['name']} | {kpi_id}: {title} | {data_year} | {len(values)} | "
                f"{statistics.median(values.values()):g} | {old_median} |"
            )
            write_values_csv(path, values)
            meta["year"] = data_year
            meta["kolada"]["kpi"] = kpi_id
            meta["source"] = f"Kolada (RKA), {kpi_id}: {title}"
        write_indicators_json(data_dir / "indicators.json", indicators)

        if errors:
            lines += ["", f"### Kunde inte hämtas ({len(errors)})", "", "```", *errors, "```"]
            self.stderr.write("not imported:\n" + "\n".join(errors))
        if summary:
            with open(summary, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        self.stdout.write(f"wrote {len(fetched)} indicators, {len(errors)} failed")
