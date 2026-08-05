"""EC_POLICY_V2 decision agent."""

from __future__ import annotations


class PolicyAgent:
    @staticmethod
    def _confidence(primary: str, order: dict, product: dict, payment: dict,
                    delivery: dict, customer: dict, policy_review: dict) -> float:
        """Score evidence completeness (80%) and API-agent agreement (20%)."""
        api_agrees = bool(policy_review.get("verified")) and policy_review.get("primary_issue") == primary
        checks = [
            bool(order.get("order_id") and order.get("order_status")),
            bool(customer.get("customer_unique_id")),
            bool(payment.get("payments")),
            bool(customer.get("api_handoff", {}).get("verified")),
            api_agrees,
        ]
        if primary in {"late_delivery_seller", "late_delivery_logistics", "unsupported_late_claim"}:
            checks.extend([
                bool(product.get("api_handoff", {}).get("verified")),
                bool(payment.get("api_handoff", {}).get("verified")),
                bool(delivery.get("api_handoff", {}).get("verified")),
                delivery.get("delivered_at") is not None,
                delivery.get("estimated_delivery_at") is not None,
            ])
        if primary == "unsupported_late_claim":
            checks.append(payment.get("reconciled") is True)
        if primary == "late_delivery_seller":
            checks.extend([bool(delivery.get("carrier_handoff_at")), bool(delivery.get("late_handoff_seller_ids"))])
        elif primary == "late_delivery_logistics":
            checks.extend([bool(delivery.get("carrier_handoff_at")), not delivery.get("late_handoff_seller_ids")])
        elif primary == "valid_split_payment":
            checks.extend([
                bool(product.get("api_handoff", {}).get("verified")),
                bool(payment.get("api_handoff", {}).get("verified")),
                len(payment.get("payments", [])) >= 2,
                payment.get("reconciled") is True,
            ])
        elif primary in {"canceled_order_paid", "unavailable_order_paid"}:
            checks.extend([
                bool(payment.get("api_handoff", {}).get("verified")),
                payment.get("payment_total_brl", 0) > 0,
            ])
        evidence_score = sum(checks) / len(checks)
        # Reserve 1.00 for certainty unavailable in an LLM-assisted workflow.
        return round(min(0.99, evidence_score), 2)

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
        elif delivery["delivery_variance_hours"] is not None and delivery["delivery_variance_hours"] <= 0 and payment["reconciled"]:
            primary, cause, main_action = "unsupported_late_claim", "DELIVERY_WITHIN_ESTIMATE", "reject_late_refund"
        else:
            raise ValueError(f"Order {order['order_id']} does not match any EC_POLICY_V2 primary issue")

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
                "confidence": 0.0, "cause": cause, "responsible_parties": parties, "recommended_refund_brl": round(refund, 2), "actions": actions[:5]}
        result["api_handoff"] = api.generate_json("PolicyAgent", "Review all specialist handoffs and assess the supplied EC_POLICY_V2 decision. Return JSON with keys verified (boolean), primary_issue (string), and summary (string).", {"order": order, "customer": customer, "product": product, "payment": payment, "delivery": delivery, "proposed_decision": result})
        result["confidence"] = self._confidence(primary, order, product, payment, delivery, customer, result["api_handoff"])
        return result
