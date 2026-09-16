"""The SVG mark and the PNG renderer must describe the same shape.

There are two copies of the logo geometry — deskpilot_mark.svg, which the browser
renders, and scripts/render_mark.py, which produces the marketplace logo, because
ImageMagick's built-in SVG renderer drops the ring stroke. Two copies drift. This
reads the numbers back out of the SVG and checks them against the renderer, so
editing one without the other fails here rather than shipping a logo that does
not match the product.
"""

import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(REPO, "deskpilot", "public", "img", "deskpilot_mark.svg")


def svg_text():
    with open(SVG) as fh:
        return fh.read()


class TestMarkGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svg = svg_text()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "render_mark", os.path.join(REPO, "scripts", "render_mark.py"))
        cls.rm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.rm)

    def test_viewbox_matches(self):
        m = re.search(r'viewBox="0 0 (\d+) (\d+)"', self.svg)
        self.assertIsNotNone(m, "no viewBox in the SVG")
        self.assertEqual(float(m.group(1)), self.rm.VIEWBOX)
        self.assertEqual(m.group(1), m.group(2), "the mark must be square")

    def test_ring_matches(self):
        m = re.search(r'<circle cx="(\d+)" cy="(\d+)" r="(\d+)" fill="none" '
                      r'stroke="(#[0-9a-fA-F]{6})" stroke-width="(\d+)"', self.svg)
        self.assertIsNotNone(m, "ring not found in the SVG")
        cx, cy, r, colour, width = m.groups()
        self.assertEqual((int(cx), int(cy), int(r)),
                         (self.rm.RING["cx"], self.rm.RING["cy"], self.rm.RING["r"]))
        self.assertEqual(int(width), self.rm.RING["width"])
        self.assertEqual(colour.lower(), "#%02x%02x%02x" % self.rm.INK)

    def test_polygons_match(self):
        points = re.findall(r'<polygon points="([^"]+)"', self.svg)
        self.assertEqual(len(points), 2, "expected exactly two polygons")
        parsed = [[tuple(float(n) for n in p.split(",")) for p in pts.split()]
                  for pts in points]
        # Order in the file is cross (faint) then pointer (solid).
        self.assertEqual(parsed[0], [tuple(map(float, p)) for p in self.rm.CROSS])
        self.assertEqual(parsed[1], [tuple(map(float, p)) for p in self.rm.POINTER])

    def test_the_mark_is_dark(self):
        """The widget CSS assumes dark ink: it scrims on light, inverts on dark."""
        r, g, b = self.rm.INK
        self.assertLess((r + g + b) / 3, 90, "the mark must stay dark; see copilot.js CSS")

    def test_renders_without_an_svg_library(self):
        img = self.rm.render(64)
        self.assertEqual(img.size, (64, 64))
        # The ring is the part ImageMagick drops. Its top edge sits ~2px in from
        # the bounding box, so a pixel there proves the stroke was drawn.
        alpha = img.split()[-1]
        self.assertGreater(alpha.getpixel((32, 5)), 0,
                           "the ring stroke is missing from the rendered mark")


if __name__ == "__main__":
    unittest.main()
