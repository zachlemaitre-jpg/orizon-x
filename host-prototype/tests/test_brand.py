import importlib.util
import os
import unittest

HAVE_QT = importlib.util.find_spec("PySide6") is not None
if HAVE_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app import brand


@unittest.skipUnless(HAVE_QT, "PySide6 absent")
class BrandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_font_family_is_mazagla(self):
        self.assertEqual(brand.load_brand_font(), "MAZAGLA")
        self.assertEqual(brand.load_brand_font(), "MAZAGLA")  # deuxième appel : pas de double chargement

    def test_logo_is_sharp_on_hidpi(self):
        pixmap = brand.logo_pixmap(44, 2.0)
        self.assertFalse(pixmap.isNull())
        self.assertEqual((pixmap.width(), pixmap.height()), (88, 88))
        self.assertEqual(pixmap.devicePixelRatio(), 2.0)

    def test_logo_is_white_with_transparent_corners(self):
        image = brand.logo_pixmap(64, 1.0).toImage()
        centre = image.pixelColor(32, 40)  # dans le X
        self.assertEqual((centre.red(), centre.green(), centre.blue(), centre.alpha()), (255, 255, 255, 255))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)

    def test_missing_font_falls_back_without_crashing(self):
        family = brand.load_brand_font(path=brand.ASSETS / "absent.otf", cache=False)
        self.assertTrue(family)
        self.assertNotEqual(family, "MAZAGLA")

    def test_icons_render_at_dpr_2(self):
        for name in ("etendre_affichage", "dupliquer_affichage", "stop", "position_right", "position_left",
                     "position_above", "position_below", "choose", "interval"):
            pixmap = brand.icon_pixmap(name, 18, 2.0)
            self.assertFalse(pixmap.isNull(), name)
            self.assertEqual((pixmap.width(), pixmap.height()), (36, 36))
            self.assertEqual(pixmap.devicePixelRatio(), 2.0)
            self.assertFalse(brand.icon(name, 18, 2.0).isNull())

    def test_icon_is_white_by_default_and_tintable(self):
        def opaque_colors(color):
            image = brand.icon_pixmap("stop", 48, 1.0, color).toImage()
            return {image.pixelColor(x, y).name() for x in range(48) for y in range(48)
                    if image.pixelColor(x, y).alpha() == 255}
        self.assertEqual(opaque_colors("#FFFFFF"), {"#ffffff"})
        self.assertEqual(opaque_colors("#FF0000"), {"#ff0000"})


if __name__ == "__main__":
    unittest.main()
