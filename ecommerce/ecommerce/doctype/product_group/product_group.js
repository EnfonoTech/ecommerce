frappe.ui.form.on("Product Group", {
    validate: function(frm) {
        if(frm.doc.apply_group_discount) {
            (frm.doc.group_items || []).forEach(row=>{
                row.group_item_discount_per = frm.doc.group_discount_per;
                let discount = (row.standard_selling_price * (frm.doc.group_discount_per || 0)) / 100;
                row.price_after_discount = row.standard_selling_price - discount;
            })
            frm.refresh_field('group_items');
        }
    }
});


frappe.ui.form.on("Product Group Item", {
    item: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.item) return;

        frappe.db.get_single_value("Selling Settings", "selling_price_list").then(price_list => {
            if (!price_list) {
                frappe.msgprint("Please set a Selling Price List in Selling Settings");
                return;
            }

            frappe.db.get_value("Item Price",
                { item_code: row.item, price_list: price_list },
                "price_list_rate"
            ).then(price_r => {
                let price = (price_r && price_r.message && price_r.message.price_list_rate) ? price_r.message.price_list_rate : 0;
                frappe.model.set_value(cdt, cdn, "standard_selling_price", price);

                // find discount and set discounted price
                set_discount_and_price_after_discount(frm, cdt, cdn, price);
                
            });
        });
    },

    group_item_discount_per: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // only recalc if group discount is NOT applied globally
        if (!frm.doc.apply_group_discount && row.standard_selling_price) {
            let discount = (row.standard_selling_price * (row.group_item_discount_per || 0)) / 100;
            frappe.model.set_value(cdt, cdn, "price_after_discount", row.standard_selling_price - discount);
        }
    },
});

function set_discount_and_price_after_discount(frm, cdt, cdn, price){
    row = locals[cdt][cdn]
    if (frm.doc.apply_group_discount) {
        // case 1: apply group discount
        frappe.model.set_value(cdt, cdn, "group_item_discount_per", frm.doc.group_discount_per || 0);
        let discount = (price * (frm.doc.group_discount_per || 0)) / 100;
        frappe.model.set_value(cdt, cdn, "price_after_discount", price - discount);

    } else {
        // case 2: use max_discount from item master
        frappe.db.get_value("Item", row.item, "max_discount").then(item_r => {
            let max_discount = (item_r && item_r.message && item_r.message.max_discount) ? item_r.message.max_discount : 0;
            frappe.model.set_value(cdt, cdn, "group_item_discount_per", max_discount);
            let discount = (price * max_discount) / 100;
            frappe.model.set_value(cdt, cdn, "price_after_discount", price - discount);
        });
    }
}
