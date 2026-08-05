"""EC_POLICY_V2 decision agent."""

from __future__ import annotations


class PolicyAgent:
    def decide(self, order: dict, product: dict, payment: dict, delivery: dict, customer: dict, api) -> dict:
        late_delivery = delivery["delivery_variance_hours"] is not None and delivery["delivery_variance_hours"] > 0
        paid = payment["payment_total_brl"] > 0
        primary, cause, parties, refund, main_action = (None, None, [], 0.0, None)
        if order["order_status"] == "canceled" and paid:
            primary, cause, parties, refund, main_action = "canceled_order_paid", "ORDER_CANCELED_AFTER_PAYMENT", [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}], payment["payment_total_brl"], "issue_full_refund"
        elif order["order_status"] == "unavailable" and paid:
            primary, cause, parties, refund, main_action = "unavailable_order_paid", "ORDER_UNAVAILABLE_AFTER_PAYMENT", [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}], payment["payment_total_brl"], "issue_full_refund"
        elif late_delivery and delivery["late_handoff_seller_ids"]:
            primary, cause, refund, main_action = "late_delivery_seller", "SELLER_HANDOFF_AFTER_LIMIT", payment["freight_total_brl"] or 0.0, "refund_freight"
            parties = [{"party_type": "seller", "party_id": seller} for seller in delivery["late_handoff_seller_ids"][:3]]
        elif late_delivery:
            primary, cause, parties, refund, main_action = "late_delivery_logistics", "CARRIER_DELIVERED_AFTER_ESTIMATE", [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}], payment["freight_total_brl"] or 0.0, "refund_freight"
        elif len(payment["payments"]) >= 2 and payment["reconciled"]:
            primary, cause, main_action = "valid_split_payment", "MULTIPLE_PAYMENTS_RECONCILED", "explain_valid_split_payment"
        else:
            primary, cause, main_action = "unsupported_late_claim", "DELIVERY_WITHIN_ESTIMATE", "reject_late_refund"

        secondary = []
        if len(product["items"]) >= 2: secondary.append("multi_item_order")
        if len(product["seller_ids"]) >= 2: secondary.append("multi_seller_order")
        if len(payment["payments"]) >= 2: secondary.append("split_payment")
        if customer["related_order_ids"]: secondary.append("repeat_customer")
        if len(product["category_names"]) >= 2: secondary.append("multiple_categories")
        actions = [main_action]
        if primary == "late_delivery_seller": actions.append("review_seller_handoff")
        elif primary == "late_delivery_logistics": actions.append("review_carrier_delay")
        if primary in {"canceled_order_paid", "unavailable_order_paid"}: actions.append("verify_refund_completion")
        if "multi_seller_order" in secondary: actions.append("coordinate_multi_seller_case")
        if "split_payment" in secondary and primary != "valid_split_payment": actions.append("verify_payment_allocation")
        result = {"primary_issue": primary, "secondary_issues": secondary, "case_status": "action_required" if refund else "no_action",
                "confidence": 1.0, "cause": cause, "responsible_parties": parties, "recommended_refund_brl": round(refund, 2), "actions": actions[:5]}
        result["api_handoff"] = api.generate_json("PolicyAgent", "Review all specialist handoffs and assess the supplied EC_POLICY_V2 decision. Return JSON with keys verified (boolean), primary_issue (string), and summary (string).", {"order": order, "customer": customer, "product": product, "payment": payment, "delivery": delivery, "proposed_decision": result})
        return result
