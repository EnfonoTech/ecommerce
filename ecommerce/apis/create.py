import frappe
from frappe import _
from frappe.utils import getdate, flt
from erpnext import get_default_company
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return


def _find_customer_by_contact(phone=None, email=None):
    """
    Look up an existing Customer via a linked Contact's phone/email, so a
    repeat website customer doesn't get a duplicate Customer record just
    because the caller no longer knows the ERPNext Customer id.
    """
    if phone:
        contact_names = frappe.get_all("Contact Phone", filters={"phone": phone}, pluck="parent")
        if contact_names:
            existing = frappe.db.get_value(
                "Dynamic Link",
                {"parenttype": "Contact", "link_doctype": "Customer", "parent": ["in", contact_names]},
                "link_name",
            )
            if existing:
                return existing

    if email:
        contact_names = frappe.get_all("Contact Email", filters={"email_id": email}, pluck="parent")
        if contact_names:
            existing = frappe.db.get_value(
                "Dynamic Link",
                {"parenttype": "Contact", "link_doctype": "Customer", "parent": ["in", contact_names]},
                "link_name",
            )
            if existing:
                return existing

    return None


def _get_or_create_customer(customer, customer_details):
    """
    Resolve the Customer to use for an incoming website order.
    `customer` may already be a valid Customer id (repeat order using the
    id we returned last time), or just an identifier like a phone number
    that has no matching Customer yet - in which case one is created.
    """
    if customer and frappe.db.exists("Customer", customer):
        return customer

    phone = customer_details.get("phone") or customer
    email = customer_details.get("email")
    name = customer_details.get("name") or phone or email

    if not name:
        frappe.throw(_("Customer does not exist and no customer_details were provided to create one"))

    existing = _find_customer_by_contact(phone=phone, email=email)
    if existing:
        return existing

    customer_doc = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": name,
        "customer_type": "Individual",
        "customer_group": frappe.db.get_single_value("Selling Settings", "customer_group") or "Individual",
        "territory": frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
    })
    customer_doc.insert(ignore_permissions=True)

    if phone or email:
        contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": name,
        })
        if phone:
            contact.append("phone_nos", {"phone": phone, "is_primary_mobile_no": 1})
        if email:
            contact.append("email_ids", {"email_id": email, "is_primary": 1})
        contact.append("links", {"link_doctype": "Customer", "link_name": customer_doc.name})
        contact.insert(ignore_permissions=True)

    return customer_doc.name


def _get_default_warehouse(item_code, company):
    """
    Resolve the warehouse to deduct stock from for this item: the item's own
    company-specific default first, falling back to Stock Settings.
    update_stock on a Sales Invoice requires every stock item row to carry
    a warehouse, or submit throws (validate_warehouse in selling_controller).
    """
    warehouse = frappe.db.get_value(
        "Item Default", {"parent": item_code, "company": company}, "default_warehouse"
    )
    if not warehouse:
        warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
    if not warehouse:
        msg = _("No default warehouse configured for item {0}. Set one under the item's Item Defaults or in Stock Settings.")
        frappe.throw(msg.format(item_code))
    return warehouse


@frappe.whitelist()
def create_sales_invoice(data=None):
    """
    Auto-create (and submit) a Sales Invoice from a website order, with
    update_stock=1 so stock deducts automatically on submit - per the BRD's
    e-commerce integration requirement. Returns the submitted invoice.
    """
    try:
        if not data:
            data = frappe.form_dict

        data = frappe.parse_json(data)

        if not data.get("customer"):
            frappe.throw(_("Customer is required"))

        if not data.get("items") or len(data.get("items", [])) == 0:
            frappe.throw(_("At least one item is required"))

        company = get_default_company()
        if not company:
            frappe.throw(_("Default company is not set. Please set it in Global Defaults."))

        customer_details = data.get("customer_details", {}) or {}
        customer = _get_or_create_customer(data.get("customer"), customer_details)

        sales_invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": customer,
            "customer_name": customer_details.get("name"),
            "custom_email": customer_details.get("email"),
            "custom_phone": customer_details.get("phone"),
            "posting_date": getdate(data.get("transaction_date")) if data.get("transaction_date") else getdate(),
            "company": company,
            "po_no": data.get("order_ref", ""),  # Customer's website order id
            "update_stock": 1,
        })

        common_warehouse = None
        for item_data in data.get("items", []):
            item_code = item_data.get("item_code")
            qty = flt(item_data.get("qty", 0))
            rate = flt(item_data.get("rate", 0))

            if not item_code:
                frappe.throw(_("Item code is required for all items"))

            item_meta = frappe.db.get_value("Item", item_code, ["name", "is_stock_item"], as_dict=True)
            if not item_meta:
                not_exist_msg = _("Item {0} does not exist")
                frappe.throw(not_exist_msg.format(item_code))

            row = {"item_code": item_code, "qty": qty, "rate": rate}
            if item_meta.is_stock_item:
                warehouse = _get_default_warehouse(item_code, company)
                common_warehouse = common_warehouse or warehouse
                row["warehouse"] = warehouse

            sales_invoice.append("items", row)

        sales_invoice.set_warehouse = common_warehouse
        sales_invoice.set_missing_values()

        if data.get("discount_amount"):
            sales_invoice.discount_amount = flt(data.get("discount_amount", 0))
            sales_invoice.apply_discount_on = "Grand Total"
            sales_invoice.custom_wallet_points = flt(data.get("wallet_points", 0))

        sales_invoice.insert(ignore_permissions=True)
        sales_invoice.submit()

        return {
            "status": "success",
            "message": "Sales Invoice created and submitted successfully",
            "sales_invoice": {
                "name": sales_invoice.name,
                "customer": sales_invoice.customer,
                "posting_date": str(sales_invoice.posting_date),
                "grand_total": sales_invoice.grand_total,
                "net_total": sales_invoice.net_total,
                "outstanding_amount": sales_invoice.outstanding_amount,
                "discount_amount": sales_invoice.discount_amount,
                "update_stock": sales_invoice.update_stock,
                "docstatus": sales_invoice.docstatus,  # 1 = submitted, stock + GL posted
            }
        }

    except Exception as e:
        error_detail = str(e)
        frappe.log_error(
            message="Error creating Sales Invoice: " + error_detail,
            title="Sales Invoice Creation Error"
        )
        fail_msg = _("Failed to create Sales Invoice: {0}")
        frappe.throw(fail_msg.format(error_detail))


@frappe.whitelist()
def create_credit_note(data=None):
    """
    Reverse a submitted Sales Invoice for a return or cancellation, by
    creating and submitting a credit note (a return Sales Invoice,
    is_return=1) against it. update_stock reverses automatically since the
    return mirrors the original invoice's update_stock setting.

    `items` is optional: omit it for a full return of everything on the
    original invoice, or pass a subset with qty to return only part of it.
    """
    try:
        if not data:
            data = frappe.form_dict
        data = frappe.parse_json(data)

        invoice_name = data.get("invoice")
        if not invoice_name:
            frappe.throw(_("Sales Invoice name (invoice) is required"))

        if not frappe.db.exists("Sales Invoice", invoice_name):
            not_exist_msg = _("Sales Invoice {0} does not exist")
            frappe.throw(not_exist_msg.format(invoice_name))

        source = frappe.get_doc("Sales Invoice", invoice_name)
        if source.docstatus != 1:
            not_submitted_msg = _("Sales Invoice {0} is not submitted, nothing to reverse")
            frappe.throw(not_submitted_msg.format(invoice_name))
        if source.is_return:
            already_return_msg = _("Sales Invoice {0} is already a credit note")
            frappe.throw(already_return_msg.format(invoice_name))

        credit_note = make_sales_return(invoice_name)

        requested_items = data.get("items")
        if requested_items:
            requested_qty = {
                i["item_code"]: flt(i.get("qty"))
                for i in requested_items
                if i.get("item_code")
            }
            kept_rows = []
            for row in credit_note.items:
                if row.item_code in requested_qty:
                    row.qty = -abs(requested_qty[row.item_code])
                    kept_rows.append(row)
            if not kept_rows:
                no_match_msg = _("None of the requested items match Sales Invoice {0}")
                frappe.throw(no_match_msg.format(invoice_name))
            credit_note.items = kept_rows
            credit_note.set_missing_values()

        if data.get("reason"):
            credit_note.remarks = data.get("reason")

        credit_note.insert(ignore_permissions=True)
        credit_note.submit()

        return {
            "status": "success",
            "message": "Credit note created and submitted successfully",
            "credit_note": {
                "name": credit_note.name,
                "return_against": credit_note.return_against,
                "grand_total": credit_note.grand_total,
                "update_stock": credit_note.update_stock,
                "docstatus": credit_note.docstatus,
            }
        }

    except Exception as e:
        error_detail = str(e)
        invoice_ref = data.get("invoice") if data else None
        frappe.log_error(
            message="Error creating credit note for " + str(invoice_ref) + ": " + error_detail,
            title="Credit Note Creation Error"
        )
        fail_msg = _("Failed to create credit note: {0}")
        frappe.throw(fail_msg.format(error_detail))
