import frappe
from frappe.integrations.utils import make_post_request
from erpnext.stock.utils import get_stock_balance
from frappe.utils import now


def _resolve_image_url(raw_image):
    """
    Item Image rows sometimes have stray whitespace around a pasted external
    URL, or no image at all. Returns None for anything unusable; passes an
    already-absolute URL through unchanged and resolves a local file path
    against this site so the website always gets a fetchable address.
    """
    value = (raw_image or "").strip()
    if not value:
        return None
    return frappe.utils.get_url(value)


def _build_item_payload(item):
    """
    Build the JSON payload describing a single Item, in the shape the
    website's /webhooks/product-sync endpoint expects.
    """
    selling_price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
    selling_price = frappe.db.get_value(
        "Item Price",
        {
            "item_code": item.item_code,
            "price_list": selling_price_list,
        },
        "price_list_rate"
    ) or 0

    opening_stock = frappe.db.get_value(
        "Stock Ledger Entry",
        {
            "item_code": item.item_code,
            "is_cancelled": 0,
        },
        "sum(actual_qty)"
    ) or 0

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

    images_list = []
    for row in item.get("custom_item_images", []):
        image_url = _resolve_image_url(row.get("image"))
        if not image_url:
            continue
        images_list.append({
            "is_default": bool(row.get("is_default", False)),
            "image_title": row.get("image_title", ""),
            "image": image_url,
        })

    return {
        "item_code": item.item_code,
        "item_name": item.item_name,
        "base_item_name": item.custom_base_item_name or None,
        "brand_name": item.brand or "",
        "category_name": item.item_group or "",
        "unit_name": item.stock_uom or "",
        "is_assured": bool(item.custom_is_assured or False),
        "parent_item_code": item.custom_base_item_name or None,
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
        "min_order_qty": item.min_order_qty or 0,
        "safety_stock": item.safety_stock or 0,
        "selling_prrice": float(selling_price or 0),  # Note: typo matches the website API's expected key
        "maximum_price": float(item.custom_max_selling_price or 0),
        "reward_point": int(item.custom_reward_point or 0) if hasattr(item, "custom_reward_point") else 0,
        "reward_type": item.custom_reward_type or "fixed" if hasattr(item, "custom_reward_type") else "fixed",
        "custom_description": {
            "Product Overview": item.custom_overview or "",
            "Benefits": item.custom_benefits or "",
            "Suggested Use": item.custom_suggested_use or ""
        },
        "description": item.custom_item_description or "",
        "images": images_list,
    }


def _post_to_product_sync_webhook(payload):
    bearer_token = frappe.utils.password.get_decrypted_password("Ecommerce Settings", "Ecommerce Settings", "api_token")
    if not bearer_token:
        frappe.throw("API token is not set in Ecommerce Settings")

    website_base_url = frappe.db.get_single_value("Ecommerce Settings", "website_base_url")
    if not website_base_url:
        frappe.throw("Website base URL is not set in Ecommerce Settings")

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }
    webhook_url = f"{website_base_url}/webhooks/product-sync"

    return make_post_request(url=webhook_url, headers=headers, json=payload)


def _sync_item_job(item_code):
    """
    Background job: push one Item's current state to the website.
    Runs after the triggering transaction has committed, so it always reads
    the saved data, and never blocks or fails the ERPNext save/submit that
    triggered it - failures are logged, not raised.
    """
    try:
        item = frappe.get_doc("Item", item_code)
        payload = {"data": _build_item_payload(item)}
        _post_to_product_sync_webhook(payload)
        frappe.logger("ecommerce").info(f"Item {item_code} synced successfully to external API")
    except Exception as e:
        frappe.log_error(
            message=f"Error syncing item {item_code} to external API: {e}",
            title="Item Sync Error"
        )


def _enqueue_item_sync(item_code):
    frappe.enqueue(
        "ecommerce.utils.webhook._sync_item_job",
        queue="short",
        enqueue_after_commit=True,
        job_name=f"ecom_item_sync_{item_code}",
        item_code=item_code,
    )


def sync_item_to_external_api(doc, method):
    """
    Hook for Item: after_insert, on_update.
    Queues a background sync so a slow/unreachable website can never block
    saving the Item in ERPNext.
    """
    _enqueue_item_sync(doc.item_code)


def sync_items_on_material_receipt(doc, method):
    """
    Hook for Stock Entry on_submit.
    If purpose is 'Material Receipt', queue a sync for every item in the entry.
    """
    if getattr(doc, "purpose", None) != "Material Receipt":
        return

    item_codes = {row.get("item_code") for row in doc.get("items", []) if row.get("item_code")}
    for item_code in item_codes:
        _enqueue_item_sync(item_code)


def sync_item_on_price_change(doc, method):
    """
    Hook for Item Price: after_insert, on_update.
    Queues a sync of the related Item when its price changes.
    """
    item_code = doc.item_code if hasattr(doc, "item_code") else None
    if not item_code:
        return
    _enqueue_item_sync(item_code)


def _sync_item_deletion_job(item_code):
    try:
        payload = {"data": {"item_code": item_code, "deleted_at": now()}}
        _post_to_product_sync_webhook(payload)
        frappe.logger("ecommerce").info(f"Item deletion {item_code} synced successfully to external API")
    except Exception as e:
        frappe.log_error(
            message=f"Error syncing item deletion {item_code} to external API: {e}",
            title="Item Deletion Sync Error"
        )


def sync_item_on_deletion(doc, method):
    """
    Hook for Item: after_delete.
    Queues a deletion notification to the website.
    """
    item_code = doc.item_code if hasattr(doc, "item_code") else None
    if not item_code:
        return

    frappe.enqueue(
        "ecommerce.utils.webhook._sync_item_deletion_job",
        queue="short",
        enqueue_after_commit=True,
        job_name=f"ecom_item_delete_sync_{item_code}",
        item_code=item_code,
    )
