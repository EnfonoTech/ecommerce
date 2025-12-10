import frappe
from frappe.utils import getdate, flt, add_months
from erpnext import get_default_company


@frappe.whitelist()
def sales_order(data=None):
    try:
        # Get data from request if not provided as parameter
        if not data:
            data = frappe.form_dict
        
        data = frappe.parse_json(data)
        
        if not data.get("customer"):
            frappe.throw("Customer is required")
        
        if not data.get("items") or len(data.get("items", [])) == 0:
            frappe.throw("At least one item is required")
        
        # Get default company
        company = get_default_company()
        if not company:
            frappe.throw("Default company is not set. Please set it in Global Defaults.")
        
        # Handle customer details - update customer if details provided
        customer = data.get("customer")
        customer_details = data.get("customer_details", {})
        

        if frappe.db.exists("Customer", customer):
            customer_doc = frappe.get_doc("Customer", customer)
        
        # Compute delivery date: use provided value, else 1 month from today
        delivery_date = (
            getdate(data.get("delivery_date"))
            if data.get("delivery_date")
            else add_months(getdate(), 1)
        )

        # Create Sales Order
        sales_order = frappe.get_doc({
            "doctype": "Sales Order",
            "customer": customer,
            "customer_name": customer_details.get("name"),
            "custom_email": customer_details.get("email"),
            "custom_phone": customer_details.get("phone"),
            "transaction_date": getdate(data.get("transaction_date")) if data.get("transaction_date") else getdate(),
            "delivery_date": delivery_date,
            "company": company,
            "order_type": "Sales",
            "po_no": data.get("order_ref", ""),  # Customer's Purchase Order
        })
        
        # Add items
        for item_data in data.get("items", []):
            item_code = item_data.get("item_code")
            qty = flt(item_data.get("qty", 0))
            rate = flt(item_data.get("rate", 0))
            
            if not item_code:
                frappe.throw("Item code is required for all items")
            
            # Check if item exists
            if not frappe.db.exists("Item", item_code):
                frappe.throw(f"Item {item_code} does not exist")
            
            sales_order.append("items", {
                "item_code": item_code,
                "qty": qty,
                "rate": rate
            })
        
        sales_order.set_missing_values()

        if data.get("discount_amount"):
            sales_order.discount_amount = flt(data.get("discount_amount", 0))
            sales_order.apply_discount_on = "Grand Total"
            sales_order.custom_wallet_points = flt(data.get("wallet_points", 0))
        
        # Insert the document (draft status - docstatus = 0)
        sales_order.insert(ignore_permissions=True)
        
        # Return the created sales order
        return {
            "status": "success",
            "message": "Sales Order created successfully",
            "sales_order": {
                "name": sales_order.name,
                "customer": sales_order.customer,
                "transaction_date": str(sales_order.transaction_date),
                "delivery_date": str(sales_order.delivery_date) if sales_order.delivery_date else None,
                "grand_total": sales_order.grand_total,
                "net_total": sales_order.net_total,
                "discount_amount": sales_order.discount_amount,
                "status": sales_order.status,
                "docstatus": sales_order.docstatus  # Should be 0 for draft
            }
        }
        
    except Exception as e:
        frappe.log_error(
            message=f"Error creating Sales Order: {str(e)}",
            title="Sales Order Creation Error"
        )
        frappe.throw(f"Failed to create Sales Order: {str(e)}")
