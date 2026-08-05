"""Final agent: reject malformed or ungrounded output before it is written."""

from __future__ import annotations

from datetime import datetime


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class VerificationError(ValueError):
    pass


class VerifierAgent:
    LIMITS = {
        ("affected_entities", "order_ids"): 5,
        ("affected_entities", "item_ids"): 5,
        ("affected_entities", "seller_ids"): 3,
        ("affected_entities", "payment_ids"): 5,
        ("customer_context", "related_order_ids"): 5,
        ("product_context", "product_ids"): 5,
        ("product_context", "category_names"): 5,
        ("root_cause_analysis", "ranked_causes"): 3,
        ("root_cause_analysis", "responsible_parties"): 3,
        ("evidence_ids",): 20,
        ("resolution_actions",): 5,
    }

    def verify(self, result: dict) -> None:
        """Validate schema-level constraints and cross-field consistency."""
        confidence = result["case_assessment"]["confidence"]
        if not 0 <= confidence <= 1:
            raise VerificationError("confidence must be between 0 and 1")
        for path, limit in self.LIMITS.items():
            value = result
            for key in path:
                value = value[key]
            if len(value) > limit:
                raise VerificationError(f"{'/'.join(path)} exceeds its limit of {limit}")
        allowed_prefixes = ("order:", "item:", "payment:", "seller:", "policy:")
        if any(not evidence.startswith(allowed_prefixes) for evidence in result["evidence_ids"]):
            raise VerificationError("invalid evidence ID prefix")
        refund = result["financial_resolution"]["recommended_refund_brl"]
        status = result["case_assessment"]["case_status"]
        if (refund > 0) != (status == "action_required"):
            raise VerificationError("refund and case status disagree")

    def verify_against_source_data(self, result: dict, case: dict, repo) -> None:
        """Recompute all scorable facts from CSV data and compare with output.

        This verification is deliberately independent of LLM responses. It prevents
        a customer claim or an agent hallucination from overriding source evidence.
        Confidence is excluded because it is calculated from evidence completeness
        and API-agent agreement rather than copied from a CSV field.
        """
        order_id = case["customer_request"]["claimed_order_id"]
        if order_id not in repo.orders:
            raise VerificationError(f"claimed order does not exist: {order_id}")

        order = repo.orders[order_id]
        items = repo.items_by_order.get(order_id, [])
        payments = repo.payments_by_order.get(order_id, [])
        customer = repo.customers[order["customer_id"]]

        seller_ids = list(dict.fromkeys(item["seller_id"] for item in items))
        product_ids = list(dict.fromkeys(item["product_id"] for item in items))
        category_names = list(dict.fromkeys(
            repo.products[product_id]["product_category_name"]
            for product_id in product_ids
            if product_id in repo.products
            and repo.products[product_id]["product_category_name"]
        ))
        related_order_ids = [
            related["order_id"]
            for related in repo.orders_by_unique_customer[customer["customer_unique_id"]]
            if related["order_id"] != order_id
        ][:5]

        seller_analysis = self._expected_seller_analysis(order, items)
        late_seller_ids = [
            entry["seller_id"] for entry in seller_analysis if entry["late_handoff"]
        ]
        delivery_variance = self._hours_between(
            order["order_delivered_customer_date"],
            order["order_estimated_delivery_date"],
        )

        item_total = round(sum(float(item["price"]) for item in items), 2)
        freight_total = round(sum(float(item["freight_value"]) for item in items), 2)
        payment_total = round(sum(float(payment["payment_value"]) for payment in payments), 2)
        expected_total = round(item_total + freight_total, 2) if items else None
        difference = round(payment_total - expected_total, 2) if items else None
        reconciled = abs(difference) <= 0.10 if difference is not None else None

        primary, cause, parties, refund, main_action = self._expected_decision(
            order=order,
            payment_total=payment_total,
            freight_total=freight_total,
            payment_count=len(payments),
            reconciled=reconciled,
            delivery_variance=delivery_variance,
            late_seller_ids=late_seller_ids,
        )

        secondary = []
        if len(items) >= 2:
            secondary.append("multi_item_order")
        if len(seller_ids) >= 2:
            secondary.append("multi_seller_order")
        if len(payments) >= 2:
            secondary.append("split_payment")
        if related_order_ids:
            secondary.append("repeat_customer")
        if len(category_names) >= 2:
            secondary.append("multiple_categories")

        actions = [main_action]
        if primary == "late_delivery_seller":
            actions.append("review_seller_handoff")
        elif primary == "late_delivery_logistics":
            actions.append("review_carrier_delay")
        if primary in {"canceled_order_paid", "unavailable_order_paid"}:
            actions.append("verify_refund_completion")
        if "multi_seller_order" in secondary:
            actions.append("coordinate_multi_seller_case")
        if "split_payment" in secondary and primary != "valid_split_payment":
            actions.append("verify_payment_allocation")
        actions = actions[:5]

        item_ids = [f"{order_id}:{item['order_item_id']}" for item in items][:5]
        payment_ids = [
            f"{order_id}:{payment['payment_sequential']}" for payment in payments
        ][:5]
        evidence = (
            [f"order:{order_id}"]
            + [f"item:{item_id}" for item_id in item_ids]
            + [f"payment:{payment_id}" for payment_id in payment_ids]
            + [
                f"seller:{party['party_id']}"
                for party in parties
                if party["party_type"] == "seller"
            ]
            + [f"policy:{cause}"]
        )[:20]

        expected_sections = {
            "case_id": case["case_id"],
            "case_assessment.primary_issue": primary,
            "case_assessment.secondary_issues": secondary,
            "case_assessment.case_status": "action_required" if refund > 0 else "no_action",
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids,
                "seller_ids": seller_ids[:3],
                "payment_ids": payment_ids,
            },
            "customer_context": {
                "customer_unique_id": customer["customer_unique_id"],
                "related_order_ids": related_order_ids,
            },
            "product_context": {
                "product_ids": product_ids[:5],
                "category_names": category_names[:5],
            },
            "delivery_analysis": {
                "delivered_at": order["order_delivered_customer_date"] or None,
                "estimated_delivery_at": order["order_estimated_delivery_date"] or None,
                "carrier_handoff_at": order["order_delivered_carrier_date"] or None,
                "delivery_variance_hours": delivery_variance,
                "seller_handoff_analysis": seller_analysis,
                "late_handoff_seller_ids": late_seller_ids,
            },
            "payment_reconciliation": {
                "currency": "BRL",
                "item_total_brl": item_total,
                "freight_total_brl": freight_total,
                "expected_total_brl": expected_total,
                "payment_total_brl": payment_total,
                "difference_brl": difference,
                "reconciled": reconciled,
                "payment_types": list(dict.fromkeys(
                    payment["payment_type"] for payment in payments
                )),
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": cause, "rank": 1}],
                "responsible_parties": parties,
            },
            "evidence_ids": evidence,
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": refund,
            },
            "resolution_actions": actions,
        }

        for path, expected in expected_sections.items():
            actual = self._value_at_path(result, path)
            if actual != expected:
                raise VerificationError(
                    f"{path} does not match source data: expected {expected!r}, got {actual!r}"
                )

    @staticmethod
    def _value_at_path(value: dict, path: str):
        for key in path.split("."):
            value = value[key]
        return value

    @staticmethod
    def _hours_between(later: str, earlier: str) -> float | None:
        if not later or not earlier:
            return None
        later_at = datetime.strptime(later, TIME_FORMAT)
        earlier_at = datetime.strptime(earlier, TIME_FORMAT)
        return round((later_at - earlier_at).total_seconds() / 3600, 2)

    @classmethod
    def _expected_seller_analysis(cls, order: dict, items: list[dict]) -> list[dict]:
        items_by_seller: dict[str, list[dict]] = {}
        for item in items:
            items_by_seller.setdefault(item["seller_id"], []).append(item)

        analysis = []
        for seller_id, seller_items in items_by_seller.items():
            shipping_limit = min(item["shipping_limit_date"] for item in seller_items)
            variance = cls._hours_between(
                order["order_delivered_carrier_date"], shipping_limit
            )
            analysis.append({
                "seller_id": seller_id,
                "shipping_limit_at": shipping_limit,
                "handoff_variance_hours": variance,
                "late_handoff": variance is not None and variance > 0,
            })
        return analysis

    @staticmethod
    def _expected_decision(
        *, order: dict, payment_total: float, freight_total: float,
        payment_count: int, reconciled: bool | None,
        delivery_variance: float | None, late_seller_ids: list[str],
    ) -> tuple[str, str, list[dict], float, str]:
        paid = payment_total > 0
        late_delivery = delivery_variance is not None and delivery_variance > 0
        if order["order_status"] == "canceled" and paid:
            return (
                "canceled_order_paid", "ORDER_CANCELED_AFTER_PAYMENT",
                [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
                payment_total, "issue_full_refund",
            )
        if order["order_status"] == "unavailable" and paid:
            return (
                "unavailable_order_paid", "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
                payment_total, "issue_full_refund",
            )
        if late_delivery and late_seller_ids:
            return (
                "late_delivery_seller", "SELLER_HANDOFF_AFTER_LIMIT",
                [
                    {"party_type": "seller", "party_id": seller_id}
                    for seller_id in late_seller_ids[:3]
                ],
                freight_total, "refund_freight",
            )
        if late_delivery:
            return (
                "late_delivery_logistics", "CARRIER_DELIVERED_AFTER_ESTIMATE",
                [{
                    "party_type": "logistics_provider",
                    "party_id": "LOGISTICS_PROVIDER",
                }],
                freight_total, "refund_freight",
            )
        if payment_count >= 2 and reconciled is True:
            return (
                "valid_split_payment", "MULTIPLE_PAYMENTS_RECONCILED", [],
                0.0, "explain_valid_split_payment",
            )
        if delivery_variance is not None and delivery_variance <= 0 and reconciled is True:
            return (
                "unsupported_late_claim", "DELIVERY_WITHIN_ESTIMATE", [],
                0.0, "reject_late_refund",
            )
        raise VerificationError(
            f"order {order['order_id']} does not match any EC_POLICY_V2 issue"
        )
