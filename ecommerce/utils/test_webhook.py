# ecommerce/ecommerce/utils/test_webhook.py
#
# bench --site <site> run-tests --module ecommerce.utils.test_webhook

from frappe.tests.utils import FrappeTestCase

from ecommerce.utils.webhook import _resolve_image_url


class TestResolveImageUrl(FrappeTestCase):
	def test_blank_or_missing_image_returns_none(self):
		self.assertIsNone(_resolve_image_url(None))
		self.assertIsNone(_resolve_image_url(""))
		self.assertIsNone(_resolve_image_url("   "))

	def test_absolute_url_is_untouched_even_with_stray_whitespace(self):
		url = _resolve_image_url("  https://i.ibb.co/abc123/product.jpg  ")
		self.assertEqual(url, "https://i.ibb.co/abc123/product.jpg")

	def test_local_file_path_is_resolved_to_this_site(self):
		url = _resolve_image_url("/files/product.jpg")
		self.assertTrue(url.endswith("/files/product.jpg"))
		self.assertTrue(url.startswith("http"))
