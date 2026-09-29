# ecommerce/ecommerce/apis/test_create.py
#
# bench --site <site> run-tests --module ecommerce.apis.test_create

import frappe
from frappe.tests.utils import FrappeTestCase

from ecommerce.apis.create import (
	_get_or_create_customer,
	create_credit_note,
	create_sales_invoice,
)


class TestCreateOrder(FrappeTestCase):
	def setUp(self):
		self.test_warehouse = frappe.db.get_value(
			"Warehouse", {"is_group": 0}, "name"
		)
		self.test_item = "_Test Ecom Stock Item"
		if not frappe.db.exists("Item", self.test_item):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": self.test_item,
				"item_name": self.test_item,
				"item_group": frappe.db.get_value("Item Group", {}, "name") or "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}).insert(ignore_permissions=True)
			frappe.get_doc({
				"doctype": "Stock Reconciliation",
				"purpose": "Opening Stock",
				"items": [{
					"item_code": self.test_item,
					"warehouse": self.test_warehouse,
					"qty": 100,
					"valuation_rate": 10,
				}],
			}).submit()

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

	def test_create_sales_invoice_submits_and_deducts_stock(self):
		phone = "9999900003"
		stock_before = frappe.db.get_value(
			"Bin", {"item_code": self.test_item, "warehouse": self.test_warehouse}, "actual_qty"
		) or 0

		result = create_sales_invoice({
			"customer": phone,
			"customer_details": {
				"name": "Endpoint Test Customer",
				"phone": phone,
				"email": "endpoint.test@example.com",
			},
			"items": [{"item_code": self.test_item, "qty": 2, "rate": 50}],
		})

		self.assertEqual(result["status"], "success")
		si_name = result["sales_invoice"]["name"]
		self.assertEqual(frappe.db.get_value("Sales Invoice", si_name, "docstatus"), 1)
		self.assertEqual(result["sales_invoice"]["update_stock"], 1)
		self.assertTrue(frappe.db.exists("Customer", result["sales_invoice"]["customer"]))

		stock_after = frappe.db.get_value(
			"Bin", {"item_code": self.test_item, "warehouse": self.test_warehouse}, "actual_qty"
		)
		self.assertEqual(stock_after, stock_before - 2)

		# cleanup: cancel then delete
		frappe.get_doc("Sales Invoice", si_name).cancel()
		frappe.delete_doc("Sales Invoice", si_name, force=True, ignore_permissions=True)

	def test_create_credit_note_reverses_stock(self):
		phone = "9999900004"
		result = create_sales_invoice({
			"customer": phone,
			"customer_details": {"name": "Return Test Customer", "phone": phone},
			"items": [{"item_code": self.test_item, "qty": 3, "rate": 50}],
		})
		si_name = result["sales_invoice"]["name"]
		stock_after_sale = frappe.db.get_value(
			"Bin", {"item_code": self.test_item, "warehouse": self.test_warehouse}, "actual_qty"
		)

		credit_result = create_credit_note({"invoice": si_name, "reason": "Customer return"})

		self.assertEqual(credit_result["status"], "success")
		cn_name = credit_result["credit_note"]["name"]
		self.assertEqual(frappe.db.get_value("Sales Invoice", cn_name, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Sales Invoice", cn_name, "return_against"), si_name)

		stock_after_return = frappe.db.get_value(
			"Bin", {"item_code": self.test_item, "warehouse": self.test_warehouse}, "actual_qty"
		)
		self.assertEqual(stock_after_return, stock_after_sale + 3)

		# cleanup
		frappe.get_doc("Sales Invoice", cn_name).cancel()
		frappe.delete_doc("Sales Invoice", cn_name, force=True, ignore_permissions=True)
		frappe.get_doc("Sales Invoice", si_name).cancel()
		frappe.delete_doc("Sales Invoice", si_name, force=True, ignore_permissions=True)
