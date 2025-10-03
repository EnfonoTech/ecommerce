import frappe

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

        frappe.local.response.update(result)

        return
    except Exception as e:
        return str(e)
    
@frappe.whitelist()
def home_page():
    try:
        home_ad_1 = get_image_set("Top Banner - Home")
    except Exception as e:
        return {"exception": str(e)}
