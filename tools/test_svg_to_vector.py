"""Run from the tools folder:  py -m unittest"""
import math
import unittest

import svg_to_vector as conv


def svg(body, extra=""):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">{extra}{body}</svg>'


class RectTest(unittest.TestCase):
    def test_plain_rect(self):
        self.assertEqual(conv.rect_path(2, 3, 10, 6), "M2,3H12V9H2Z")

    def test_rounded_rect_uses_four_arcs_clockwise(self):
        d = conv.rect_path(2.46, 12.46, 43.09, 23.08, 9.22, 9.22)
        self.assertEqual(d.count("A9.22,9.22,0,0,1,"), 4)
        self.assertTrue(d.startswith("M11.68,12.46H36.33A"))
        self.assertTrue(d.endswith("Z"))

    def test_radius_is_clamped_to_half_the_size(self):
        d = conv.rect_path(0, 0, 10, 4, rx=9)
        self.assertIn("A5,2,0,0,1,", d)  # ry copies rx (9) then both are clamped: 5 and 2

    def test_xml_rect_with_rx_ry(self):
        xml = conv.convert_svg(svg('<rect x="1" y="2" width="20" height="10" rx="3" ry="3"/>'))
        self.assertIn('android:pathData="M4,2H18A3,3,0,0,1,21,5V9A3,3,0,0,1,18,12H4A3,3,0,0,1,1,9V5A3,3,0,0,1,4,2Z"', xml)
        self.assertNotIn("<group", xml)


class CircleTest(unittest.TestCase):
    def test_circle_is_two_half_arcs(self):
        self.assertEqual(conv.circle_path(24, 10, 4), "M20,10A4,4,0,1,0,28,10A4,4,0,1,0,20,10Z")

    def test_xml_circle(self):
        xml = conv.convert_svg(svg('<circle cx="24" cy="24" r="9.22"/>'))
        self.assertIn("M14.78,24A9.22,9.22,0,1,0,33.22,24A9.22,9.22,0,1,0,14.78,24Z", xml)
        self.assertIn('android:viewportWidth="48"', xml)
        self.assertIn('android:width="24dp"', xml)


class TransformTest(unittest.TestCase):
    def apply(self, m, x, y):
        a, b, c, d, e, f = m
        return a * x + c * y + e, b * x + d * y + f

    def test_translate_then_rotate_matches_svg_semantics(self):
        m = conv.parse_transform("translate(10 20) rotate(90)")
        x, y = self.apply(m, 1, 0)  # rotate(90) maps (1,0) -> (0,1), then translate
        self.assertAlmostEqual(x, 10)
        self.assertAlmostEqual(y, 21)

    def test_rotate_about_a_point(self):
        m = conv.parse_transform("rotate(180 5 5)")
        x, y = self.apply(m, 4, 5)
        self.assertAlmostEqual(x, 6)
        self.assertAlmostEqual(y, 5)

    def test_decompose_reproduces_the_matrix_like_android_does(self):
        # Android group: translate(tx, ty) * rotate(r) * scale(sx, sy), pivot (0, 0).
        m = conv.parse_transform("translate(-5.63 13.58) rotate(-45) scale(1 -1)")
        tx, ty, rot, sx, sy = conv.decompose(m)
        rad = math.radians(rot)
        built = (sx * math.cos(rad), sx * math.sin(rad), -sy * math.sin(rad), sy * math.cos(rad), tx, ty)
        for got, want in zip(built, m):
            self.assertAlmostEqual(got, want, places=6)

    def test_skew_is_rejected(self):
        with self.assertRaises(ValueError):
            conv.decompose(conv.parse_transform("matrix(1 0 0.5 1 0 0)"))

    def test_rotated_rect_becomes_a_group(self):
        xml = conv.convert_svg(
            svg('<rect x="10.91" y="9.72" width="5.34" height="7.71" rx="2.67" ry="2.67" '
                'transform="translate(-5.63 13.58) rotate(-45)"/>')
        )
        self.assertIn('<group android:rotation="-45" android:translateX="-5.63" android:translateY="13.58">', xml)
        self.assertIn("</group>", xml)
        # The path itself is untransformed rect geometry.
        self.assertIn("M13.58,9.72H13.58", xml)

    def test_translate_only_has_no_rotation_attribute(self):
        xml = conv.convert_svg(svg('<rect x="0" y="0" width="4" height="4" transform="translate(3 2)"/>'))
        self.assertIn('<group android:translateX="3" android:translateY="2">', xml)
        self.assertNotIn("rotation", xml)


class OpacityTest(unittest.TestCase):
    STYLE = "<defs><style>.cls-1 { opacity: .3; }</style></defs>"

    def test_class_opacity_becomes_fill_alpha(self):
        xml = conv.convert_svg(svg('<path class="cls-1" d="M0,0H4V4Z"/><path d="M1,1H2V2Z"/>', self.STYLE))
        self.assertEqual(xml.count("android:fillAlpha"), 1)
        self.assertIn('android:fillAlpha="0.3"', xml)

    def test_group_opacity_multiplies(self):
        xml = conv.convert_svg(svg('<g opacity=".5"><path opacity=".5" d="M0,0H4V4Z"/></g>'))
        self.assertIn('android:fillAlpha="0.25"', xml)

    def test_duplicate_layer_is_dropped(self):
        body = '<path class="cls-1" d="M0,0H4V4Z"/><path class="cls-1" d="M0,0H4V4Z"/>'
        xml = conv.convert_svg(svg(body, self.STYLE))
        self.assertEqual(xml.count("android:pathData"), 1)


class RejectTest(unittest.TestCase):
    def test_stroke_is_rejected(self):
        with self.assertRaises(ValueError):
            conv.convert_svg(svg('<path stroke="#000" d="M0,0H4"/>'))

    def test_unknown_element_is_rejected(self):
        with self.assertRaises(ValueError):
            conv.convert_svg(svg('<text>hi</text>'))


if __name__ == "__main__":
    unittest.main()
