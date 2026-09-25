# ecommerce/ecommerce/apis/test_create.py
#
# bench --site <site> run-tests --module ecommerce.apis.test_create

import frappe
from frappe.tests.utils import FrappeTestCase

from ecommerce.apis.create import _get_or_create_customer, sales_order


class TestSalesOrderCreation(FrappeTestCase):
	def setUp(self):
		self.test_item = "_Test Ecom Item"
		if not frappe.db.exists("Item", self.test_item):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": self.test_item,
				"item_name": self.test_item,
				"item_group": frappe.db.get_value("Item Group", {}, "name") or "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}).insert(ignore_permissions=True)

	def test_new_customer_is_created_from_customer_details(self):
		phone = "9999900001"
		self.assertFalse(frappe.db.exists("Customer", phone))

		customer_name = _get_or_create_customer(phone, {
			"name": "Test Ecom Customer",
			"phone": phone,
			"email": "test.ecom.customer@example.com",
		})

		self.assertTrue(frappe.db.exists("Customer", customer_name))
		self.assertEqual(
			frappe.db.get_value("Customer", customer_name, "customer_name"),
			"Test Ecom Customer",
		)

	def test_repeat_order_reuses_customer_by_phone(self):
		phone = "9999900002"
		first = _get_or_create_customer(phone, {"name": "Repeat Customer", "phone": phone})
		# Second order arrives with a fresh/unknown identifier (e.g. the
		# phone number again) rather than the Customer id we returned - it
		# must resolve back to the same Customer, not create a duplicate.
		second = _get_or_create_customer(phone, {"name": "Repeat Customer", "phone": phone})

		self.assertEqual(first, second)

	def test_sales_order_endpoint_creates_customer_and_order(self):
		phone = "9999900003"
		result = sales_order({
			"customer": phone,
			"customer_details": {
				"name": "Endpoint Test Customer",
				"phone": phone,
				"email": "endpoint.test@example.com",
			},
			"items": [{"item_code": self.test_item, "qty": 1, "rate": 10}],
		})

		self.assertEqual(result["status"], "success")
		so_name = result["sales_order"]["name"]
		self.assertEqual(frappe.db.get_value("Sales Order", so_name, "docstatus"), 0)
		self.assertTrue(frappe.db.exists("Customer", result["sales_order"]["customer"]))

		frappe.delete_doc("Sales Order", so_name, force=True, ignore_permissions=True)
