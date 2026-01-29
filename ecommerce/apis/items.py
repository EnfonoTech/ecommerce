from ecommerce.ecommerce.doctype.bundle_category import bundle_category
import frappe
from frappe.utils import getdate
from erpnext.stock.utils import get_stock_balance

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
            "most_sold_items": items
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

        frappe.local.response.update({
            bundle_category: result
        })

        return
    
    except Exception as e:
        return str(e)
    
@frappe.whitelist()
def get_composite_item_by_id(id):
    try:
        combo_item = frappe.get_doc("Product Bundle", id)
        
        components = []

        result = {
            "bundle_id": combo_item.name,
            "bundle_category": combo_item.ecom_product_bundle_category,
            "parent_item_id": combo_item.new_item_code
        }

        for item in combo_item.items:
            components.append({
                "item_id": item.item_code,
                "item_description": item.description,
                "quantity": item.qty,
                "unit": item.uom
            })

        result.update({
            "components": components
        })

        frappe.local.response.update(result)

        return
    
    except Exception as e:
        return str(e)

@frappe.whitelist()
def get_popular_item_groups():
    try:
        item_groups = frappe.db.get_all(
            "Item Group",
            filters={"ecom_is_popular": True},
            fields=["name", "item_group_name", "image"]
        )
        
        result = {"popular_categories":[]}
        for item in item_groups:
            result["popular_categories"].append({
                "category_id": item.name,
                "category_name": item.item_group_name,
                "category_image_url": frappe.utils.get_url(item.image) if item.image else None
            })

        frappe.local.response.update(result)
        
        return

    except Exception as e:
        return {"exception": str(e)}
    
@frappe.whitelist()
def get_product_group_items(group_name):
    """
    List of single items that come under a deal or offer
    """
    try:
        group = frappe.get_doc("Product Group", group_name)

        item_count = len(group.group_items)

        result = {
            "group_name": group_name,
            "item_count": item_count,
            "items": []
        }

        for item in group.group_items:
            result['items'].append({
                "item_id": item.item,
                "item_name": item.item_name,
                "std_sell_price": item.standard_selling_price or 0,
                "discount": group.group_discount_per if group.apply_group_discount else item.group_item_discount_per or 0,
                "dicount_sell_price": item.price_after_discount or 0
            })

        frappe.local.response.update(result)

    except Exception as e:
        return {"exception": str(e)}
    
@frappe.whitelist()
def get_single_item(item_code):
    """
    Fetch details of a single item by item code
    """
    try:
        item = frappe.get_doc("Item", item_code)

        item_price = frappe.db.get_value(
            'Item Price',
            {
                'item_code': item.item_code,
                'selling': 1,
                'price_list': frappe.db.get_single_value('Selling Settings', 'selling_price_list')
            },
            'price_list_rate'
        )

        nutrients_dict = {
            row.get("nutrient"): row.get("quantity")
            for row in item.get("custom_nutritional_highlights", [])
        }

        product_specifications_dict = {
            row.get("product_spec"): row.get("value")
            for row in item.get("custom_product_specifications", [])
        }

        warehouses = frappe.db.get_all(
            "Bin",
            filters={"item_code": item.item_code},
            pluck="warehouse",
        ) or []

        available_stock = 0
        for warehouse in warehouses:
            available_stock += get_stock_balance(item.item_code, warehouse) or 0

        selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
        selling_price = frappe.db.get_value(
            "Item Price",
            {
                "item_code": item.item_code,
                "price_list": selling_price_list,
            },
            "price_list_rate"
        ) or 0

        images_dict = {
            index: {"is_default": row.get("is_default"), "image_title": row.get("image_title"), "image_url": frappe.utils.get_url(row.get("image"))}
            for index, row in enumerate(item.get("custom_item_images"))
        }

        result = {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "brand_name": item.brand,
            "category_name": item.item_group,
            "unit_name": item.stock_uom,
            "is_assured": item.custom_is_assured,
            "base_item_name": item.custom_base_item_name,
            "variants": {
                "flavour": item.custom_flavor_variant or "",
                "weight": item.custom_weight_variant or "" ,
            },
            "specifications": {
                "nutritional_highlights": nutrients_dict,
                "product_specifications": product_specifications_dict,
            },
            "disabled": item.disabled,
            "available_stock": available_stock,
            "minimum_order_quantity": item.min_order_qty or 0,
            "safety_stock": item.safety_stock or 0,
            "selling_price": selling_price or 0,
            "maximum_price": item.custom_max_selling_price or 0,
            "custom_description": {
                "product_overview": item.custom_overview,
                "benefits": item.custom_benefits,
                "suggested_use": item.custom_suggested_use
            },
            "description": item.custom_item_description,
            "images": images_dict
        }

        frappe.local.response.update(result)

        return

    except Exception as e:
        return {"exception": str(e)}


@frappe.whitelist()
def get_items_details(item_codes=None):
    """
    Fetch details of multiple items by item codes
    """
    try:

        # Get from form_dict if not provided
        if not item_codes:
            item_codes = frappe.form_dict.get("item_codes", [])

        item_codes = frappe.parse_json(item_codes)
        
        if len(item_codes) == 0:
            frappe.throw("At least one item_code is required")
        
        selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
        
        result = []
        
        for item_code in item_codes:
            try:
                # Check if item exists
                if not frappe.db.exists("Item", item_code):
                    result.append({
                        "item_code": item_code,
                        "error": "Item not found"
                    })
                    continue
                
                item = frappe.get_doc("Item", item_code)
                
                # Get selling price
                selling_price = frappe.db.get_value(
                    "Item Price",
                    {
                        "item_code": item.item_code,
                        "price_list": selling_price_list,
                    },
                    "price_list_rate"
                ) or 0
                
                # Get warehouses and calculate available stock
                warehouses = frappe.db.get_all(
                    "Bin",
                    filters={"item_code": item.item_code},
                    pluck="warehouse",
                ) or []
                
                available_stock = 0
                for warehouse in warehouses:
                    available_stock += get_stock_balance(item.item_code, warehouse) or 0
                
                # Build item details
                item_details = {
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "base_item_name": item.custom_base_item_name or "",
                    "category_name": item.item_group or "",
                    "unit_name": item.stock_uom or "",
                    "is_assured": item.custom_is_assured,
                    "available_stock": available_stock,
                    "selling_price": selling_price,
                    "maximum_price": item.custom_max_selling_price or 0,
                }
                
                result.append(item_details)

            
                
            except Exception as e:
                result.append({
                    "item_code": item_code,
                    "error": str(e)
                })

        frappe.local.response.update(
            {
                "items": result
            }
        )

        return
        
    except Exception as e:
        frappe.log_error(
            message=f"Error fetching items details: {str(e)}",
            title="Get Items Details Error"
        )
        return {"exception": str(e)}

