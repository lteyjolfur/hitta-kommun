import json
import tempfile
from pathlib import Path

import openpyxl
from django.test import SimpleTestCase

from finder.sources import (
    CRIME_SHEET,
    SourceError,
    parse_crime_workbook,
    parse_scb_region_csv,
    read_dimensions_json,
    read_indicators_json,
    read_values_csv,
    write_values_csv,
)


class TempDirMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


def make_crime_workbook(path, header_overrides=None, rows=None):
    """Mimic the layout of the Öppna jämförelser workbook (header row 3, data from row 8)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = CRIME_SHEET
    header = [None] * 30
    header[0] = "K-kod"
    header[12] = "Antal anmälda våldsbrott per 1\xa0000 invånare"
    header[17] = "Antal anmälda stöld- och tillgreppsbrott per 1 000 invånare"
    header[26] = "Antal anmälda brott om skadegörelse per 1 000 invånare"
    for col, text in (header_overrides or {}).items():
        header[col] = text
    ws.append([" ", None, None, "A1. Personskador"])
    ws.append([])
    ws.append(header)
    ws.append([None, "Min – Max"])
    ws.append([None, "Rikets värde", None, 9.1])
    ws.append([])
    ws.append([None, "Kommun"])  # a hand-added label row with no code: must be skipped
    for code, name, violence, theft, vandalism in rows or [
        ("1440", "Ale", 5.7, 25.3, 8.4),
        ("0114", "Upplands Väsby", 11.2, 30.4, 47.3),
    ]:
        row = [None] * 30
        row[0], row[1], row[12], row[17], row[26] = code, name, violence, theft, vandalism
        ws.append(row)
    wb.save(path)


class CrimeWorkbookTests(TempDirMixin, SimpleTestCase):
    def test_parses_three_indicators_by_header_text(self):
        path = self.tmp / "crime.xlsx"
        make_crime_workbook(path)
        result = parse_crime_workbook(path)
        self.assertEqual(result["violent-crime"], {"1440": 5.7, "0114": 11.2})
        self.assertEqual(result["theft"]["1440"], 25.3)
        self.assertEqual(result["vandalism"]["0114"], 47.3)

    def test_rejects_unexpected_layout(self):
        path = self.tmp / "crime.xlsx"
        make_crime_workbook(path, header_overrides={12: "Något annat"})
        with self.assertRaisesRegex(SourceError, "våldsbrott"):
            parse_crime_workbook(path)

    def test_rejects_missing_sheet(self):
        path = self.tmp / "other.xlsx"
        openpyxl.Workbook().save(path)
        with self.assertRaisesRegex(SourceError, "not found"):
            parse_crime_workbook(path)


class ScbCsvTests(TempDirMixin, SimpleTestCase):
    def write(self, text, encoding="utf-8"):
        path = self.tmp / "scb.csv"
        path.write_bytes(text.encode(encoding))
        return path

    def test_comma_export_skips_country_and_missing(self):
        path = self.write(
            "Titel på tabellen\n"
            '"region","2023"\n'
            '"00 Riket","3000"\n'
            '"0114 Upplands Väsby","4500"\n'
            '"0115 Vallentuna",".."\n'
            '"1440 Ale","2900"\n'
        )
        self.assertEqual(parse_scb_region_csv(path), {"0114": 4500.0, "1440": 2900.0})

    def test_semicolon_decimal_comma_and_cp1252(self):
        path = self.write("region;värde\n0114 Upplands Väsby;4 512,5\n", encoding="cp1252")
        self.assertEqual(parse_scb_region_csv(path), {"0114": 4512.5})

    def test_duplicate_kommun_means_wrong_export(self):
        path = self.write("region,2022,2023\n0114 Upplands Väsby,1,2\n0114 Upplands Väsby,3,4\n")
        with self.assertRaisesRegex(SourceError, "twice"):
            parse_scb_region_csv(path)

    def test_no_rows(self):
        with self.assertRaises(SourceError):
            parse_scb_region_csv(self.write("a,b\n1,2\n"))


class DataFileTests(TempDirMixin, SimpleTestCase):
    def test_values_round_trip(self):
        path = self.tmp / "v.csv"
        write_values_csv(path, {"1440": 5.7359, "0114": 11.0})
        self.assertEqual(path.read_text().splitlines(), ["code,value", "0114,11", "1440,5.7359"])
        self.assertEqual(read_values_csv(path), {"0114": 11.0, "1440": 5.7359})

    def test_values_rejects_bad_rows(self):
        for body, message in [
            ("code,value\n114,1\n", "invalid kommun code"),
            ("code,value\n0114,x\n", "not a number"),
            ("code,value\n0114,1\n0114,2\n", "duplicate"),
            ("kod,value\n0114,1\n", "header"),
        ]:
            path = self.tmp / "v.csv"
            path.write_text(body)
            with self.subTest(body=body), self.assertRaisesRegex(SourceError, message):
                read_values_csv(path)

    def indicator(self, **overrides):
        item = {
            "slug": "theft",
            "name": "Stöld",
            "unit": "per 1 000",
            "year": 2022,
            "lower_is_better": True,
            "source": "Test",
            "source_url": "",
            "file": "values/theft.csv",
            "dimension": "safety",
            "range": [0, 100],
        }
        item.update(overrides)
        return {k: v for k, v in item.items() if v is not DROP}

    def read(self, content):
        path = self.tmp / "i.json"
        path.write_text(json.dumps(content))
        return read_indicators_json(path, {"safety", "housing"})

    def test_indicators_json_valid(self):
        price = self.indicator(slug="price", dimension="housing", file="values/price.csv")
        income = self.indicator(slug="income", year=None, file="values/income.csv", kolada={"search": "median"})
        ratio = self.indicator(slug="ratio", file=DROP, derived={"numerator": "price", "denominator": "income"})
        self.assertEqual(
            [i["slug"] for i in self.read([self.indicator(), price, income, ratio])],
            ["theft", "price", "income", "ratio"],
        )

    def test_indicators_json_rejects_bad_entries(self):
        bad = [
            [self.indicator(lower_is_better="yes")],
            [self.indicator(year="2022")],
            [self.indicator(slug="Bad Slug")],
            [self.indicator(), self.indicator()],
            [{**self.indicator(), "extra": 1}],
            [self.indicator(dimension="nope")],
            [self.indicator(range=[5, 1])],
            [self.indicator(range=None)],
            [self.indicator(file=DROP)],
            [self.indicator(kolada={"kpi": "12345"})],
            [self.indicator(kolada={})],
            [self.indicator(derived={"numerator": "theft", "denominator": "x"})],
            [self.indicator(file=DROP, derived={"numerator": "nope", "denominator": "theft"})],
            [self.indicator(slug="r", file=DROP, derived={"numerator": "theft", "denominator": "theft", "scale": 0})],
            {"not": "a list"},
        ]
        for content in bad:
            with self.subTest(content=content), self.assertRaises(SourceError):
                self.read(content)

    def test_dimensions_json(self):
        path = self.tmp / "d.json"
        path.write_text(json.dumps([{"slug": "safety", "name": "Trygghet", "description": "x"}]))
        self.assertEqual(read_dimensions_json(path)[0]["name"], "Trygghet")
        for content in [[], [{"slug": "safety"}], [{"slug": "a", "name": "A", "description": ""}] * 2]:
            path.write_text(json.dumps(content))
            with self.subTest(content=content), self.assertRaises(SourceError):
                read_dimensions_json(path)


DROP = object()
