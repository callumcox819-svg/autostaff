import unittest

from services.aqua_link import _csm_product_price, _price_is_zero


class CsmPriceTests(unittest.TestCase):
    def test_skips_zero_and_keeps_250(self):
        self.assertTrue(_price_is_zero("0"))
        self.assertTrue(_price_is_zero("0.00 €"))
        self.assertFalse(_price_is_zero("250€"))
        self.assertEqual(_csm_product_price("0", "0.00", "250€"), "250")
        self.assertEqual(_csm_product_price("", None, "250"), "250")
        self.assertEqual(_csm_product_price("14.5"), "14.5")
        self.assertEqual(_csm_product_price(""), "")


if __name__ == "__main__":
    unittest.main()
