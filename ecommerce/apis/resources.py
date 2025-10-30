import frappe
from .items import get_most_sold_items, get_composite_items, get_popular_item_groups, get_product_group_items

@frappe.whitelist(allow_guest=True)
def get_image_set(set_name):
    """
    Fetch images from an Image Set and return their public URLs
    """
    try:
        image_set = frappe.get_doc("Image Set", set_name)

        result = {
            "name": image_set.name,
            "images": []
        }

        for item in image_set.images:
            result["images"].append({
                "image_name": item.image_name if item.image_name else "",
                "image_url": frappe.utils.get_url(item.image) if item.image else None
            })

        frappe.local.response.update({
            "top_banner_images": result
        })

        return
    except Exception as e:
        return str(e)
    
@frappe.whitelist()
def home_page():
    try:
        get_image_set("Top Banner")

        get_most_sold_items()

        get_composite_items("Mega Deal Pack")

        get_popular_item_groups()

        get_product_group_items("Block Buster Deals")
    
    except Exception as e:
        return {"exception": str(e)}
