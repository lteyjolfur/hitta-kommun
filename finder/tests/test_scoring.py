from django.test import SimpleTestCase

from finder.scoring import dimension_scores, normalize, rank


class NormalizeTests(SimpleTestCase):
    def test_higher_is_better_maps_max_to_one(self):
        self.assertEqual(normalize({"a": 10, "b": 20, "c": 15}, lower_is_better=False), {"a": 0, "b": 1, "c": 0.5})

    def test_lower_is_better_flips(self):
        self.assertEqual(normalize({"a": 10, "b": 20}, lower_is_better=True), {"a": 1, "b": 0})

    def test_all_equal_values_score_one(self):
        self.assertEqual(normalize({"a": 3, "b": 3}, lower_is_better=True), {"a": 1, "b": 1})

    def test_empty(self):
        self.assertEqual(normalize({}, lower_is_better=True), {})


CODES = ["a", "b", "c"]
VALUES = {
    "violence": {"a": 10, "b": 20, "c": 30},  # a best
    "theft": {"a": 30, "b": 20, "c": 10},  # c best
    "price": {"a": 900, "b": 100, "c": 500},  # b best
}
LOWER = {"violence": True, "theft": True, "price": True}
DIMENSION = {"violence": "safety", "theft": "safety", "price": "housing"}


class DimensionScoreTests(SimpleTestCase):
    def test_dimension_is_mean_of_its_indicators(self):
        scores = dimension_scores(CODES, VALUES, LOWER, DIMENSION)
        self.assertEqual(scores["safety"], {"a": 0.5, "b": 0.5, "c": 0.5})
        self.assertEqual(scores["housing"], {"a": 0, "b": 1, "c": 0.5})

    def test_missing_indicator_uses_the_others_in_that_dimension(self):
        values = {"violence": {"a": 10, "b": 20}, "theft": {"a": 1, "b": 2, "c": 3}}
        scores = dimension_scores(CODES, values, LOWER, DIMENSION)
        self.assertEqual(scores["safety"]["c"], 0)  # theft only: c is worst
        self.assertEqual(scores["safety"]["a"], 1)

    def test_indicator_without_values_is_ignored(self):
        scores = dimension_scores(CODES, {"violence": VALUES["violence"], "theft": {}}, LOWER, DIMENSION)
        self.assertEqual(scores["safety"], {"a": 1, "b": 0.5, "c": 0})


class RankTests(SimpleTestCase):
    def setUp(self):
        self.dims = dimension_scores(CODES, VALUES, LOWER, DIMENSION)

    def scores(self, weights):
        return {r.code: r.score for r in rank(CODES, self.dims, weights)}

    def test_weights_shift_the_ranking(self):
        self.assertEqual(rank(CODES, self.dims, {"safety": 0, "housing": 1})[0].code, "b")

    def test_weighted_mean_of_dimensions(self):
        # c: safety 0.5, housing 0.5 -> 0.5 whatever the weights
        self.assertAlmostEqual(self.scores({"safety": 3, "housing": 1})["c"], 0.5)
        # a: safety 0.5, housing 0 -> (0.5*3 + 0*1) / 4
        self.assertAlmostEqual(self.scores({"safety": 3, "housing": 1})["a"], 0.375)

    def test_no_weights_gives_no_scores(self):
        self.assertEqual(set(self.scores({"safety": 0, "housing": 0}).values()), {None})

    def test_missing_dimension_is_reported_not_zeroed(self):
        dims = {"safety": {"a": 1.0, "b": 0.0}, "housing": {"a": 0.0, "b": 1.0, "c": 0.5}}
        results = {r.code: r for r in rank(CODES, dims, {"safety": 1, "housing": 1})}
        self.assertEqual(results["c"].missing, ["safety"])
        self.assertEqual(results["c"].score, 0.5)

    def test_kommun_with_no_data_sorts_last(self):
        results = rank(["z", "a"], {"safety": {"a": 1.0}}, {"safety": 1})
        self.assertEqual([r.code for r in results], ["a", "z"])
        self.assertIsNone(results[1].score)
