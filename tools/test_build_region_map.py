#!/usr/bin/env python3
"""Tests for the parts of tools/build_region_map.py that need no map data: cutting the coastline to a box, closing
the sea, and choosing a help-point class from raw tags. Skipped where pyosmium is not installed.

  derived/buildenv/bin/python -B -m unittest tools/test_build_region_map.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import build_region_map as b
except ImportError:  # pyosmium is a build-machine package
    b = None

BOX = [0.0, 0.0, 10.0, 10.0]


def area(ring):
    """Signed area: negative for a clockwise ring (y up), which is how a sea polygon must run."""
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:])) / 2


@unittest.skipIf(b is None, 'pyosmium is not installed')
class Sea(unittest.TestCase):
    def test_sea_to_the_south(self):
        # the coast runs west to east, so land (left) is north and the sea (right) is south
        pieces = b.clip_line([(-5, 4), (5, 6), (15, 4)], BOX)
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0][0], (0.0, 5.0))
        self.assertEqual(pieces[0][-1], (10.0, 5.0))
        (ring,) = b.sea_rings(pieces, BOX)
        self.assertEqual(ring[0], ring[-1])
        self.assertIn((10.0, 0.0), ring)
        self.assertIn((0.0, 0.0), ring)
        self.assertNotIn((0.0, 10.0), ring)
        self.assertAlmostEqual(abs(area(ring)), 55.0)
        self.assertLess(area(ring), 0)

    def test_sea_to_the_north(self):
        # the same coast the other way round: the sea is now north
        pieces = b.clip_line([(15, 4), (5, 6), (-5, 4)], BOX)
        (ring,) = b.sea_rings(pieces, BOX)
        self.assertIn((0.0, 10.0), ring)
        self.assertIn((10.0, 10.0), ring)
        self.assertNotIn((0.0, 0.0), ring)
        self.assertAlmostEqual(abs(area(ring)), 45.0)

    def test_two_coasts_make_one_strait(self):
        # land to the north and to the south, sea between them
        north = b.clip_line([(-5, 8), (15, 8)], BOX)   # land on the left: north
        south = b.clip_line([(15, 2), (-5, 2)], BOX)   # land on the left: south
        rings = b.sea_rings(north + south, BOX)
        self.assertEqual(len(rings), 1)
        self.assertAlmostEqual(abs(area(rings[0])), 60.0)

    def test_coast_outside_the_box_is_dropped(self):
        self.assertEqual(b.clip_line([(-5, -5), (-2, -1), (-1, -4)], BOX), [])

    def test_line_crossing_twice_gives_two_pieces(self):
        pieces = b.clip_line([(-1, 5), (5, 5), (5, 12), (7, 12), (7, 5), (12, 5)], BOX)
        self.assertEqual(len(pieces), 2)
        for p in pieces:
            self.assertIsNotNone(b.edge_pos(p[0], BOX))
            self.assertIsNotNone(b.edge_pos(p[-1], BOX))

    def test_chains_join_ways_in_any_order(self):
        ways = [([2, 3], [(1, 0), (2, 0)]), ([1, 2], [(0, 0), (1, 0)]), ([3, 4], [(2, 0), (3, 0)])]
        (chain,) = b.chains(ways)
        self.assertEqual(chain, (False, [(0, 0), (1, 0), (2, 0), (3, 0)]))


@unittest.skipIf(b is None, 'pyosmium is not installed')
class HelpPoints(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(b.poi_class({'amenity': 'hospital'}), 'hospital')
        self.assertEqual(b.poi_class({'amenity': 'toilets'}), 'toilet')
        self.assertEqual(b.poi_class({'amenity': 'townhall'}), 'town_hall')
        self.assertEqual(b.poi_class({'shop': 'bicycle'}), 'bicycle_shop')
        self.assertEqual(b.poi_class({'man_made': 'tower', 'tower:type': 'communication'}), 'comms_tower')
        self.assertIsNone(b.poi_class({'amenity': 'restaurant'}))

    def test_bus_shelters_are_not_shelters(self):
        self.assertIsNone(b.poi_class({'amenity': 'shelter', 'shelter_type': 'public_transport'}))
        self.assertEqual(b.poi_class({'amenity': 'shelter'}), 'shelter')
        self.assertEqual(b.poi_class({'amenity': 'shelter', 'shelter_type': 'weather_shelter'}), 'shelter')

    def test_every_class_is_one_build_map_keeps(self):
        text = (Path(__file__).resolve().parent / 'build_map.py').read_text(encoding='utf-8')
        start = text.index('POI_KEEP = {')
        keep = set(eval(text[start + 11:text.index('}', start) + 1]))
        ours = set(b.AMENITY.values()) | set(b.SHOP.values()) | set(b.MAN_MADE.values()) | {'comms_tower', 'camp_site', 'spring', 'embassy', 'beach', 'park'}
        self.assertLessEqual(ours, keep)


if __name__ == '__main__':
    unittest.main()
