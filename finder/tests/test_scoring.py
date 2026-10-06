from django.test import SimpleTestCase

from finder.scoring import normalize, rank


class NormalizeTests(SimpleTestCase):
    def test_higher_is_better_maps_max_to_one(self):
        self.assertEqual(normalize({"a": 10, "b": 20, "c": 15}, lower_is_better=False), {"a": 0, "b": 1, "c": 0.5})

    def test_lower_is_better_flips(self):
        self.assertEqual(normalize({"a": 10, "b": 20}, lower_is_better=True), {"a": 1, "b": 0})

    def test_all_equal_values_score_one(self):
        self.assertEqual(normalize({"a": 3, "b": 3}, lower_is_better=True), {"a": 1, "b": 1})

    def test_empty(self):
        self.assertEqual(normalize({}, lower_is_better=True), {})


class RankTests(SimpleTestCase):
    values = {
        "crime": {"a": 10, "b": 20, "c": 30},
        "price": {"a": 900, "b": 100, "c": 500},
    }
    lower = {"crime": True, "price": True}

    def scores(self, weights, codes=("a", "b", "c")):
        return {r.code: r.score for r in rank(list(codes), self.values, self.lower, weights)}

    def test_single_indicator(self):
        self.assertEqual(self.scores({"crime": 1, "price": 0}), {"a": 1, "b": 0.5, "c": 0})

    def test_weights_shift_the_ranking(self):
        crime_heavy = rank(["a", "b", "c"], self.values, self.lower, {"crime": 9, "price": 1})
        price_heavy = rank(["a", "b", "c"], self.values, self.lower, {"crime": 1, "price": 9})
        self.assertEqual(crime_heavy[0].code, "a")
        self.assertEqual(price_heavy[0].code, "b")

    def test_weighted_mean(self):
        # b: crime 0.5, price 1.0 -> (0.5*1 + 1.0*3) / 4
        self.assertAlmostEqual(self.scores({"crime": 1, "price": 3})["b"], 0.875)

    def test_no_weights_gives_no_scores(self):
        self.assertEqual(set(self.scores({"crime": 0, "price": 0}).values()), {None})

    def test_missing_value_is_reported_not_zeroed(self):
        values = {"crime": {"a": 10, "b": 20}, "price": {"a": 1, "b": 2, "c": 3}}
        results = {r.code: r for r in rank(["a", "b", "c"], values, self.lower, {"crime": 1, "price": 1})}
        self.assertEqual(results["c"].missing, ["crime"])
        self.assertEqual(results["c"].score, 0)  # price only: c is the most expensive
        self.assertEqual(results["a"].missing, [])

    def test_kommun_with_no_data_sorts_last(self):
        results = rank(["z", "a"], {"crime": {"a": 1}}, {"crime": True}, {"crime": 1})
        self.assertEqual([r.code for r in results], ["a", "z"])
        self.assertIsNone(results[1].score)

    def test_indicator_without_values_is_ignored(self):
        results = rank(["a"], {"crime": {"a": 1}, "price": {}}, self.lower, {"crime": 1, "price": 5})
        self.assertEqual(results[0].score, 1)
        self.assertEqual(results[0].missing, [])
