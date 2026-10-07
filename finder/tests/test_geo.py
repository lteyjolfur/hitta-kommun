import numpy as np
import shapely
from django.test import SimpleTestCase
from shapely.geometry import box

from finder.geo import remove_overlaps


class RemoveOverlapsTests(SimpleTestCase):
    def test_overlap_goes_to_first_polygon_and_result_is_a_valid_coverage(self):
        a = box(0, 0, 10, 10)
        b = box(9, 2, 20, 10)  # overlaps a by 1 x 8, with corners that a doesn't have
        fixed, removed = remove_overlaps([a, b])
        self.assertEqual([(i, j, round(area)) for i, j, area in removed], [(0, 1, 8)])
        self.assertEqual(fixed[0].area, 100)
        self.assertEqual(fixed[1].area, 11 * 8 - 8)
        self.assertTrue(shapely.coverage_is_valid(np.array(fixed, dtype=object)))

    def test_neighbours_that_only_touch_are_unchanged(self):
        a, b = box(0, 0, 1, 1), box(1, 0, 2, 1)
        fixed, removed = remove_overlaps([a, b])
        self.assertEqual(removed, [])
        self.assertTrue(fixed[0].equals(a) and fixed[1].equals(b))
