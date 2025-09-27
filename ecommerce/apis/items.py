import frappe
from frappe.utils import getdate

@frappe.whitelist()
def get_most_sold_items(from_date=None, to_date=None, sort_by="quantity", limit=10):
    try:

        if sort_by not in ["quantity", "value"]:
            frappe.throw("Invalid value for key sort_by")

        order_by_clause = "total_qty DESC" if sort_by == "quantity" else "total_value DESC"

        filters = {
            "limit": int(limit)
        }

        query = f"""
        SELECT 
            i.name as item_code,
            i.item_name,
            i.item_group,
            i.stock_uom,
            COALESCE(sales_data.total_qty, 0) as total_quantity_sold,
            COALESCE(sales_data.total_value, 0) as total_value_sold,
            COALESCE(sales_data.total_orders, 0) as total_sales_orders
        FROM 
            `tabItem` i
        LEFT JOIN (
            SELECT 
                sii.item_code,
                SUM(sii.qty) as total_qty,
                SUM(sii.amount) as total_value,
                COUNT(DISTINCT si.name) as total_orders
            FROM 
                `tabSales Invoice Item` sii
            INNER JOIN 
                `tabSales Invoice` si ON sii.parent = si.name
            WHERE 
                si.docstatus = 1
                AND sii.qty > 0
            GROUP BY 
                sii.item_code
        ) as sales_data ON i.name = sales_data.item_code
        WHERE 
            i.disabled = 0
            AND i.is_sales_item = 1
        ORDER BY 
            {order_by_clause}
        LIMIT {limit}
        """

        items = frappe.db.sql(query, filters, as_dict=True)

        for item in items:
            item_price = frappe.db.get_value(
                'Item Price',
                {
                    'item_code': item.item_code,
                    'selling': 1,
                    'price_list': frappe.db.get_single_value('Selling Settings', 'selling_price_list')
                },
                'price_list_rate'
            )
            
            item['standard_selling_price'] = item_price or 0

        frappe.local.response.update({
            "data": {
                "items": items
            }
        })

        return

    except Exception as e:
        return str(e)
    
@frappe.whitelist()
def get_composite_items(bundle_category):
    try:
        combo_items = frappe.db.get_all("Product Bundle",
                    filters={"ecom_product_bundle_category": bundle_category},
                    fields=["name", "new_item_code"])
        
        result = []
        for item in combo_items:
            result.append({
                "bundle_id": item.name,
                "parent_item": item.new_item_code
            })

        return result
    
    except Exception as e:
        return str(e)
