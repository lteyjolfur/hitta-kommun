"""Kolada adapter and import command, against saved responses in the documented v3 shape.

These responses are hand-written in the shape the v3 API documents (and the
koladapy client parses), not recorded from the live API.
"""

import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from finder import kolada

KOMMUNER = {"0114", "0115", "1440"}


def data_row(code, value, year=2024, gender="T"):
    return {"kpi": "N00900", "municipality": code, "period": year, "values": [{"gender": gender, "value": value}]}


class FakeKolada:
    """get(path, params) over a dict of canned responses; records the calls."""

    def __init__(self, kpis=None, data=None):
        self.kpis = kpis or {}
        self.data = data or {}  # (kpi_id, year) -> list of rows
        self.calls = []

    def __call__(self, path, params=None):
        self.calls.append((path, params))
        if path.startswith("http"):  # next_url
            return {"values": [data_row("1440", 31.0)]}
        if path == "kpi":
            needle = params["title"].lower()
            return {"values": [k for k in self.kpis.values() if needle in k["title"].lower()]}
        if path.startswith("kpi/"):
            kpi = self.kpis.get(path[4:])
            return {"values": [kpi] if kpi else []}
        if path == "data":
            return {"values": self.data.get((params["kpi_id"], params["year"]), [])}
        raise AssertionError(path)


TAX = {"id": "N00900", "title": "Skattesats till kommun och region, %", "municipality_type": "K"}


class AdapterTests(SimpleTestCase):
    def test_resolve_by_id(self):
        self.assertEqual(kolada.resolve_kpi(FakeKolada({"N00900": TAX}), {"kpi": "N00900"}), ("N00900", TAX["title"]))

    def test_resolve_by_id_accepts_bare_object(self):
        self.assertEqual(kolada.resolve_kpi(lambda path, params=None: TAX, {"kpi": "N00900"})[0], "N00900")

    def test_pinned_id_must_match_search_title(self):
        with self.assertRaisesRegex(kolada.KoladaError, "does not contain 'medianinkomst'"):
            kolada.resolve_kpi(FakeKolada({"N00900": TAX}), {"kpi": "N00900", "search": "medianinkomst"})
        self.assertEqual(
            kolada.resolve_kpi(FakeKolada({"N00900": TAX}), {"kpi": "N00900", "search": "skattesats"})[0], "N00900"
        )

    def test_search_includes_kpis_for_both_kommun_and_region(self):
        kpis = {"N00905": {"id": "N00905", "title": "Mediannettoinkomst, kr/inv 20+", "municipality_type": "A"}}
        self.assertEqual(kolada.resolve_kpi(FakeKolada(kpis), {"search": "mediannettoinkomst"})[0], "N00905")

    def test_search_matching_only_region_kpis_says_so(self):
        kpis = {"R1": {"id": "R1", "title": "Medianinkomst region", "municipality_type": "L"}}
        with self.assertRaisesRegex(kolada.KoladaError, "only matched KPIs without kommun data"):
            kolada.resolve_kpi(FakeKolada(kpis), {"search": "medianinkomst"})

    def test_unknown_id(self):
        with self.assertRaisesRegex(kolada.KoladaError, "no KPI"):
            kolada.resolve_kpi(FakeKolada(), {"kpi": "N99999"})

    def test_resolve_by_unique_search_ignores_region_kpis(self):
        kpis = {"N00900": TAX, "R00900": {"id": "R00900", "title": "Skattesats region", "municipality_type": "L"}}
        self.assertEqual(kolada.resolve_kpi(FakeKolada(kpis), {"search": "skattesats"})[0], "N00900")

    def test_ambiguous_search_lists_candidates(self):
        kpis = {
            "N1": {"id": "N1", "title": "Medianinkomst, kvinnor", "municipality_type": "K"},
            "N2": {"id": "N2", "title": "Medianinkomst, män", "municipality_type": "K"},
        }
        with self.assertRaisesRegex(kolada.KoladaError, r"matched 2[\s\S]*N1: Medianinkomst, kvinnor"):
            kolada.resolve_kpi(FakeKolada(kpis), {"search": "medianinkomst"})

    def test_fetch_year_keeps_total_gender_and_kommuner_only(self):
        rows = [
            data_row("0114", 33.1),
            data_row("0114", 99.0, gender="K"),
            data_row("0000", 32.0),  # Riket
            {"kpi": "N00900", "municipality": "0115", "period": 2024, "values": [{"gender": "T", "value": None}]},
        ]
        fake = FakeKolada(data={("N00900", 2024): rows})
        self.assertEqual(kolada.fetch_year(fake, "N00900", 2024, KOMMUNER), {"0114": 33.1})

    def test_follows_next_url(self):
        fake = FakeKolada()
        fake.data[("N00900", 2024)] = [data_row("0114", 33.1)]
        original = fake.__call__

        def first_page_has_next(path, params=None):
            response = original(path, params)
            if path == "data":
                response["next_url"] = "https://api.kolada.se/v3/data?page=2"
            return response

        values = kolada.fetch_year(first_page_has_next, "N00900", 2024, KOMMUNER)
        self.assertEqual(values, {"0114": 33.1, "1440": 31.0})

    def test_latest_year_skips_years_without_enough_kommuner(self):
        fake = FakeKolada(
            data={
                ("N00900", 2026): [data_row("0114", 1.0)],  # only partly published
                ("N00900", 2025): [data_row(c, 32.0) for c in KOMMUNER],
            }
        )
        year, values = kolada.latest_year(fake, "N00900", KOMMUNER, 2026, min_coverage=3)
        self.assertEqual((year, len(values)), (2025, 3))

    def test_latest_year_gives_up_after_years_back(self):
        with self.assertRaisesRegex(kolada.KoladaError, "no year"):
            kolada.latest_year(FakeKolada(), "N00900", KOMMUNER, 2026, min_coverage=3)


class ImportCommandTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name)
        (self.data / "values").mkdir()
        (self.data / "kommuner.csv").write_text("code,name\n0114,Upplands Väsby\n0115,Vallentuna\n1440,Ale\n")
        (self.data / "dimensions.json").write_text(
            json.dumps([{"slug": "economy", "name": "Ekonomi", "description": ""}])
        )
        self.indicators = [
            {
                "slug": "tax-rate",
                "name": "Skattesats",
                "unit": "%",
                "year": None,
                "lower_is_better": True,
                "source": "Kolada (RKA)",
                "source_url": "",
                "file": "values/tax-rate.csv",
                "dimension": "economy",
                "range": [25, 40],
                "kolada": {"search": "skattesats"},
            }
        ]
        (self.data / "indicators.json").write_text(json.dumps(self.indicators))

    def tearDown(self):
        self._tmp.cleanup()

    def run_import(self, fake, *args):
        with (
            override_settings(DATA_DIR=self.data),
            mock.patch.object(kolada, "MIN_COVERAGE", 3),
            mock.patch.object(kolada, "http_getter", return_value=fake),
        ):
            call_command("import_kolada", "--year", "2025", *args, stdout=io.StringIO(), stderr=io.StringIO())

    def add_unresolvable_indicator(self):
        self.indicators.append(
            {**self.indicators[0], "slug": "income", "file": "values/income.csv", "kolada": {"search": "nope"}}
        )
        (self.data / "indicators.json").write_text(json.dumps(self.indicators))

    def test_one_failure_blocks_all_by_default(self):
        self.add_unresolvable_indicator()
        fake = FakeKolada({"N00900": TAX}, {("N00900", 2025): [data_row(c, 32.5) for c in KOMMUNER]})
        with self.assertRaisesRegex(CommandError, "income: search 'nope' matched 0"):
            self.run_import(fake)
        self.assertFalse((self.data / "values" / "tax-rate.csv").exists())

    def test_allow_partial_writes_what_passed_and_reports_the_rest(self):
        self.add_unresolvable_indicator()
        fake = FakeKolada({"N00900": TAX}, {("N00900", 2025): [data_row(c, 32.5) for c in KOMMUNER]})
        summary = self.data / "summary.md"
        self.run_import(fake, "--allow-partial", "--summary", str(summary))
        self.assertTrue((self.data / "values" / "tax-rate.csv").exists())
        self.assertFalse((self.data / "values" / "income.csv").exists())
        self.assertIn("Kunde inte hämtas (1)", summary.read_text())

    def test_allow_partial_still_fails_when_nothing_passed(self):
        with self.assertRaises(CommandError):
            self.run_import(FakeKolada(), "--allow-partial")

    def test_writes_values_pins_kpi_and_sets_year(self):
        fake = FakeKolada({"N00900": TAX}, {("N00900", 2025): [data_row(c, 32.5) for c in KOMMUNER]})
        summary = self.data / "summary.md"
        self.run_import(fake, "--summary", str(summary))
        self.assertEqual((self.data / "values" / "tax-rate.csv").read_text().splitlines()[1], "0114,32.5")
        meta = json.loads((self.data / "indicators.json").read_text())[0]
        self.assertEqual((meta["year"], meta["kolada"]["kpi"]), (2025, "N00900"))
        self.assertIn("N00900", meta["source"])
        self.assertIn("| Skattesats | N00900", summary.read_text())

    def test_value_outside_range_fails_and_writes_nothing(self):
        rows = [data_row("0114", 32.5), data_row("0115", 3250), data_row("1440", 32.0)]  # 3250: wrong unit
        fake = FakeKolada({"N00900": TAX}, {("N00900", 2025): rows})
        with self.assertRaisesRegex(CommandError, "outside"):
            self.run_import(fake)
        self.assertFalse((self.data / "values" / "tax-rate.csv").exists())
        self.assertIsNone(json.loads((self.data / "indicators.json").read_text())[0]["year"])
