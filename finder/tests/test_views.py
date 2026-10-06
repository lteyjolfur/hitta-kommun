import io
import json
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from finder.models import Indicator, Kommun, Value


def seed():
    for code, name in [("0114", "Upplands Väsby"), ("0115", "Vallentuna"), ("1440", "Ale")]:
        Kommun.objects.create(code=code, name=name)
    crime = Indicator.objects.create(
        slug="violent-crime", name="Våld", unit="per 1 000", year=2022, lower_is_better=True, source="Test"
    )
    Indicator.objects.create(
        slug="house-price", name="Pris", unit="tkr", year=2023, lower_is_better=True, source="Test", position=1
    )
    for code, value in [("0114", 11.0), ("0115", 5.0), ("1440", 8.0)]:
        Value.objects.create(kommun_id=code, indicator=crime, value=value)


class RankApiTests(TestCase):
    def setUp(self):
        seed()

    def test_ranks_by_weighted_indicator(self):
        data = self.client.get("/api/rank", {"w_violent-crime": 5}).json()["results"]
        self.assertEqual([r["code"] for r in data], ["0115", "1440", "0114"])
        self.assertEqual(data[0]["score"], 1)
        self.assertEqual(data[0]["values"], {"violent-crime": 5.0, "house-price": None})

    def test_weight_on_indicator_without_data_is_harmless(self):
        data = self.client.get("/api/rank", {"w_violent-crime": 1, "w_house-price": 10}).json()["results"]
        self.assertEqual(data[0]["code"], "0115")

    def test_rejects_bad_weights(self):
        for params in [{"w_violent-crime": "x"}, {"w_violent-crime": 11}, {"w_violent-crime": -1}, {"w_nope": 1}]:
            with self.subTest(params=params):
                response = self.client.get("/api/rank", params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_index_renders_sliders_and_no_data_state(self):
        html = self.client.get("/").content.decode()
        self.assertIn('id="w_violent-crime"', html)
        self.assertIn("Ingen data inlagd ännu", html)  # house-price has no values


class LoadDataTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name)
        (self.data / "values").mkdir()
        (self.data / "kommuner.csv").write_text("code,name\n0114,Upplands Väsby\n1440,Ale\n", encoding="utf-8")
        meta = {"unit": "u", "year": 2022, "lower_is_better": True, "source": "s", "source_url": ""}
        (self.data / "indicators.json").write_text(
            json.dumps(
                [
                    {"slug": "theft", "name": "Stöld", "file": "values/theft.csv", **meta},
                    {"slug": "house-price", "name": "Pris", "file": "values/house-price.csv", **meta},
                ]
            ),
            encoding="utf-8",
        )
        (self.data / "values" / "theft.csv").write_text("code,value\n0114,30.4\n1440,25.3\n")

    def tearDown(self):
        self._tmp.cleanup()

    def load(self):
        with override_settings(DATA_DIR=self.data):
            call_command("load_data", stdout=io.StringIO())

    def test_loads_and_keeps_indicator_without_file(self):
        self.load()
        self.assertEqual(Kommun.objects.count(), 2)
        self.assertEqual(list(Indicator.objects.values_list("slug", flat=True)), ["theft", "house-price"])
        self.assertEqual(Value.objects.get(kommun_id="1440").value, 25.3)
        self.assertFalse(Value.objects.filter(indicator_id="house-price").exists())

    def test_is_repeatable(self):
        self.load()
        self.load()
        self.assertEqual(Value.objects.count(), 2)

    def test_rejects_value_for_unknown_kommun(self):
        (self.data / "values" / "theft.csv").write_text("code,value\n9999,1\n")
        with self.assertRaisesRegex(CommandError, "unknown kommun"):
            self.load()
