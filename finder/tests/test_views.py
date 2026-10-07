import io
import json
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from finder.models import Dimension, Indicator, Kommun, Value


def seed():
    for code, name in [("0114", "Upplands Väsby"), ("0115", "Vallentuna"), ("1440", "Ale")]:
        Kommun.objects.create(code=code, name=name)
    Dimension.objects.create(slug="safety", name="Trygghet", description="Brott")
    Dimension.objects.create(slug="housing", name="Boendekostnad", description="Priser", position=1)
    meta = {"unit": "u", "year": 2022, "lower_is_better": True, "source": "Test"}
    crime = Indicator.objects.create(slug="violent-crime", name="Våld", dimension_id="safety", **meta)
    Indicator.objects.create(slug="house-price", name="Pris", dimension_id="housing", position=1, **meta)
    for code, value in [("0114", 11.0), ("0115", 5.0), ("1440", 8.0)]:
        Value.objects.create(kommun_id=code, indicator=crime, value=value)


class RankApiTests(TestCase):
    def setUp(self):
        seed()

    def test_ranks_by_weighted_dimension(self):
        data = self.client.get("/api/rank", {"w_safety": 5}).json()["results"]
        self.assertEqual([r["code"] for r in data], ["0115", "1440", "0114"])
        self.assertEqual(data[0]["score"], 1)
        self.assertEqual(data[0]["parts"], {"safety": 1})
        self.assertEqual(data[0]["values"], {"violent-crime": 5.0, "house-price": None})

    def test_weight_on_dimension_without_data_is_harmless(self):
        data = self.client.get("/api/rank", {"w_safety": 1, "w_housing": 10}).json()["results"]
        self.assertEqual(data[0]["code"], "0115")

    def test_rejects_bad_weights(self):
        for params in [{"w_safety": "x"}, {"w_safety": 11}, {"w_safety": -1}, {"w_violent-crime": 1}]:
            with self.subTest(params=params):
                response = self.client.get("/api/rank", params)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())

    def test_index_renders_one_slider_per_dimension(self):
        html = self.client.get("/").content.decode()
        self.assertIn('id="w_safety"', html)
        self.assertIn('id="w_housing"', html)
        self.assertNotIn('id="w_violent-crime"', html)
        self.assertIn("data saknas ännu", html)  # house-price has no values


class LoadDataTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name)
        (self.data / "values").mkdir()
        (self.data / "kommuner.csv").write_text("code,name\n0114,Upplands Väsby\n1440,Ale\n", encoding="utf-8")
        (self.data / "dimensions.json").write_text(
            json.dumps(
                [
                    {"slug": "safety", "name": "Trygghet", "description": "d"},
                    {"slug": "housing", "name": "Boende", "description": "d"},
                ]
            )
        )
        meta = {"unit": "u", "year": 2022, "lower_is_better": True, "source": "s", "source_url": ""}
        self.indicators = [
            {
                "slug": "theft",
                "name": "Stöld",
                "file": "values/theft.csv",
                "dimension": "safety",
                "range": [0, 100],
                **meta,
            },
            {
                "slug": "price",
                "name": "Pris",
                "file": "values/price.csv",
                "dimension": "housing",
                "range": [0, 1e5],
                **meta,
            },
            {
                "slug": "income",
                "name": "Inkomst",
                "file": "values/income.csv",
                "dimension": "housing",
                "range": [0, 1e6],
                **meta,
            },
            {
                "slug": "ratio",
                "name": "Pris/inkomst",
                "derived": {"numerator": "price", "denominator": "income"},
                "dimension": "housing",
                "range": [0, 50],
                **meta,
            },
        ]
        self.write_indicators()
        (self.data / "values" / "theft.csv").write_text("code,value\n0114,30.4\n1440,25.3\n")
        (self.data / "values" / "price.csv").write_text("code,value\n0114,5396\n1440,3899\n")

    def write_indicators(self):
        (self.data / "indicators.json").write_text(json.dumps(self.indicators), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def load(self):
        with override_settings(DATA_DIR=self.data):
            call_command("load_data", stdout=io.StringIO())

    def test_loads_dimensions_and_keeps_indicators_without_data(self):
        self.load()
        self.assertEqual(list(Dimension.objects.values_list("slug", flat=True)), ["safety", "housing"])
        self.assertEqual(Indicator.objects.get(slug="price").dimension_id, "housing")
        self.assertEqual(Value.objects.get(kommun_id="1440", indicator_id="theft").value, 25.3)
        self.assertFalse(Value.objects.filter(indicator_id__in=["income", "ratio"]).exists())

    def test_derived_indicator_is_computed_when_both_parts_exist(self):
        (self.data / "values" / "income.csv").write_text("code,value\n0114,400\n")  # Ale has no income
        self.load()
        ratios = dict(Value.objects.filter(indicator_id="ratio").values_list("kommun_id", "value"))
        self.assertEqual(ratios, {"0114": 5396 / 400})

    def test_is_repeatable(self):
        self.load()
        self.load()
        self.assertEqual(Value.objects.count(), 4)

    def test_rejects_value_for_unknown_kommun(self):
        (self.data / "values" / "theft.csv").write_text("code,value\n9999,1\n")
        with self.assertRaisesRegex(CommandError, "unknown kommun"):
            self.load()

    def test_rejects_values_outside_plausible_range(self):
        (self.data / "values" / "theft.csv").write_text("code,value\n0114,250\n")
        with self.assertRaisesRegex(CommandError, "outside the plausible range"):
            self.load()

    def test_rejects_derived_value_outside_range(self):
        # income accidentally in kr instead of tkr -> ratio ~0.01, outside [0.5, 50]
        self.indicators[3]["range"] = [0.5, 50]
        self.write_indicators()
        (self.data / "values" / "income.csv").write_text("code,value\n0114,400000\n1440,380000\n")
        with self.assertRaisesRegex(CommandError, "ratio"):
            self.load()
