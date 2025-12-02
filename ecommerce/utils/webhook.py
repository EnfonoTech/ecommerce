import frappe
import json
from frappe.integrations.utils import make_post_request
from erpnext.stock.utils import get_stock_balance

def sync_item_to_external_api(doc, method):
    """
    Sync item data to external API webhook when item is saved
    Prevents saving if webhook request fails
    """
    item = doc

    # Get item price
    selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
    selling_price = frappe.db.get_value(
        "Item Price",
        {
            "item_code": item.item_code,
            "price_list": selling_price_list,
        },
        "price_list_rate"
    ) or 0

    # Get opening stock
    opening_stock = frappe.db.get_value(
        "Stock Ledger Entry",
        {
            "item_code": item.item_code,
            "is_cancelled": 0,
        },
        "sum(actual_qty)"
    ) or 0

    # Build nutrients dictionary
    nutrients_dict = {
        row.get("nutrient"): row.get("quantity")
        for row in item.get("custom_nutritional_highlights", [])
    }

    # Build product specifications dictionary
    product_specifications_dict = {
        row.get("product_spec"): row.get("value")
        for row in item.get("custom_product_specifications", [])
    }

    # Get warehouses and calculate available stock
    warehouses = frappe.db.get_all(
        "Bin",
        filters={"item_code": item.item_code},
        pluck="warehouse",
    ) or []

    available_stock = 0
    for warehouse in warehouses:
        available_stock += get_stock_balance(item.item_code, warehouse) or 0

    # Build images array (not dictionary)
    images_list = [
        {
            "is_default": bool(row.get("is_default", False)),
            "image_title": row.get("image_title", ""),
            "image": row.get("image", "")  # Use 'image' not 'image_url'
        }
        for row in item.get("custom_item_images", [])
    ]

    # Build result dictionary matching the API's expected format
    result = {
        "item_code": item.item_code,
        "item_name": item.item_name,
        "brand_name": item.brand or "",
        "category_name": item.item_group or "",
        "unit_name": item.stock_uom or "",
        "is_assured": bool(item.custom_is_assured or False),
        "parent_item_code": item.custom_base_item_name or None,  # Changed from base_item_name
        "variants": {
            "flavour": item.custom_flavor_variant or "",
            "weight": item.custom_weight_variant or "",
        },
        "specifications": {
            "nutritional_highlights": nutrients_dict,
            "product_specifications": product_specifications_dict,
        },
        "disabled": item.disabled or 0,
        "opening_stock": opening_stock,
        "available_stock": available_stock,
        "min_order_qty": item.min_order_qty or 0,  # Changed from minimum_order_quantity
        "safety_stock": item.safety_stock or 0,
        "selling_prrice": float(selling_price or 0),  # Note: typo in API (prrice not price)
        "maximum_price": float(item.custom_max_selling_price or 0),
        "reward_point": int(item.custom_reward_point or 0) if hasattr(item, 'custom_reward_point') else 0,
        "reward_type": item.custom_reward_type or "fixed" if hasattr(item, 'custom_reward_type') else "fixed",
        "custom_description": {
            "Product Overview": item.custom_overview or "",  # Capitalized keys
            "Benefits": item.custom_benefits or "",
            "Suggested Use": item.custom_suggested_use or ""
        },
        "description": item.custom_item_description or "",
        "images": images_list  # Changed to array
    }

    # Wrap result in 'data' key as expected by the API
    payload = {
        "data": result
    }

    bearer_token = frappe.utils.password.get_decrypted_password("Ecommerce Settings", "Ecommerce Settings", "api_token")
    if not bearer_token:
        frappe.throw("API token is not set in Ecommerce Settings")
    bearer_token_str = f"Bearer {str(bearer_token)}"

    # Prepare headers with Bearer token
    headers = {
        "Authorization": bearer_token_str,
        "Content-Type": "application/json"
    }

    # Send POST request to webhook endpoint
    website_base_url = frappe.db.get_single_value("Ecommerce Settings", "website_base_url")
    api_path = "/webhooks/product-sync"
    if not website_base_url:
        frappe.throw("Website base URL is not set in Ecommerce Settings")
    webhook_url = f"{website_base_url}{api_path}"
    
    try:
        # IMPORTANT: Use json= not data= to send as JSON
        response = make_post_request(
            url=webhook_url,
            headers=headers,
            json=payload  # Changed from data=payload to json=payload
        )

        frappe.msgprint(f"Item {item.item_code} sucessfully synced", alert=True)

        return response
        
    except Exception as e:
        # Log the error for debugging
        error_message = str(e)
        frappe.log_error(
            message=f"Error syncing item {item.item_code} to external API: {error_message}",
            title="Item Sync Error"
        )
        # Throw validation error to prevent saving
        frappe.throw(
            f"Failed to sync item to external API. Please check the item data and try again. Error: {error_message}",
            title="Webhook Sync Failed"
        )