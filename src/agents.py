"""Specialist agents. Each returns evidence only from its assigned data domain."""

from __future__ import annotations

from datetime import datetime

from .repository import OlistRepository
from .openrouter import OpenRouterClient

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _timestamp(value: str | None) -> datetime | None:
    return datetime.strptime(value, TIME_FORMAT) if value else None


def _rounded_hours(later: datetime | None, earlier: datetime | None) -> float | None:
    if not later or not earlier:
        return None
    return round((later - earlier).total_seconds() / 3600, 2)


class CustomerAgent:
    def investigate(self, order: dict[str, str], repo: OlistRepository, api: OpenRouterClient) -> dict:
        customer = repo.customers[order["customer_id"]]
        related = [
            row["order_id"]
            for row in repo.orders_by_customer[customer["customer_id"]]
            if row["order_id"] != order["order_id"]
        ]
        # customer_id is one order in Olist, so find other orders by unique identity.
        same_person_customer_ids = [
            cid for cid, row in repo.customers.items()
            if row["customer_unique_id"] == customer["customer_unique_id"]
        ]
        related = [
            row["order_id"]
            for cid in same_person_customer_ids
            for row in repo.orders_by_customer[cid]
            if row["order_id"] != order["order_id"]
        ]
        result = {"customer_unique_id": customer["customer_unique_id"], "related_order_ids": related[:5]}
        result["api_handoff"] = api.generate_json("CustomerAgent", "Confirm the customer identity and whether this customer has previous order IDs. Return JSON with keys verified (boolean) and summary (string).", result)
        return result


class OrderProductAgent:
    def investigate(self, order_id: str, repo: OlistRepository, api: OpenRouterClient) -> dict:
        items = repo.items_by_order.get(order_id, [])
        products = [repo.products[item["product_id"]] for item in items if item["product_id"] in repo.products]
        sellers = list(dict.fromkeys(item["seller_id"] for item in items))
        categories = list(
            dict.fromkeys(
                product["product_category_name"]
                for product in products
                if product["product_category_name"]
            )
        )
        result = {
            "items": items,
            "product_ids": list(dict.fromkeys(item["product_id"] for item in items))[:5],
            "seller_ids": sellers[:3],
            "category_names": categories[:5],
        }
        result["api_handoff"] = api.generate_json("OrderProductAgent", "Review the supplied item, seller, product and category facts. Return JSON with keys verified (boolean) and summary (string).", result)
        return result


class PaymentAgent:
    def investigate(self, order_id: str, items: list[dict[str, str]], repo: OlistRepository, api: OpenRouterClient) -> dict:
        payments = repo.payments_by_order.get(order_id, [])
        if not items:
            result = {"payments": payments, "item_total_brl": 0.0, "freight_total_brl": 0.0,
                    "expected_total_brl": None, "payment_total_brl": round(sum(float(p["payment_value"]) for p in payments), 2),
                    "difference_brl": None, "reconciled": None}
            result["api_handoff"] = api.generate_json("PaymentAgent", "Review payment evidence and null handling. Return JSON with keys verified (boolean) and summary (string).", result)
            return result
        item_total = round(sum(float(item["price"]) for item in items), 2)
        freight_total = round(sum(float(item["freight_value"]) for item in items), 2)
        expected = round(item_total + freight_total, 2)
        paid = round(sum(float(payment["payment_value"]) for payment in payments), 2)
        difference = round(paid - expected, 2)
        result = {"payments": payments, "item_total_brl": item_total, "freight_total_brl": freight_total,
                "expected_total_brl": expected, "payment_total_brl": paid, "difference_brl": difference,
                "reconciled": abs(difference) <= 0.10}
        result["api_handoff"] = api.generate_json("PaymentAgent", "Review payment reconciliation. Return JSON with keys verified (boolean) and summary (string).", result)
        return result


class DeliveryAgent:
    def investigate(self, order: dict[str, str], items: list[dict[str, str]], api: OpenRouterClient) -> dict:
        delivered = _timestamp(order["order_delivered_customer_date"])
        estimated = _timestamp(order["order_estimated_delivery_date"])
        handoff = _timestamp(order["order_delivered_carrier_date"])
        by_seller: dict[str, list[dict[str, str]]] = {}
        for item in items:
            by_seller.setdefault(item["seller_id"], []).append(item)
        seller_analysis = []
        for seller_id, seller_items in by_seller.items():
            limit = min(_timestamp(item["shipping_limit_date"]) for item in seller_items)
            variance = _rounded_hours(handoff, limit)
            seller_analysis.append({"seller_id": seller_id, "shipping_limit_at": limit.strftime(TIME_FORMAT),
                                    "handoff_variance_hours": variance, "late_handoff": bool(variance is not None and variance > 0)})
        result = {"delivered_at": order["order_delivered_customer_date"] or None,
                "estimated_delivery_at": order["order_estimated_delivery_date"] or None,
                "carrier_handoff_at": order["order_delivered_carrier_date"] or None,
                "delivery_variance_hours": _rounded_hours(delivered, estimated),
                "seller_handoff_analysis": seller_analysis,
                "late_handoff_seller_ids": [entry["seller_id"] for entry in seller_analysis if entry["late_handoff"]],}
        result["api_handoff"] = api.generate_json("DeliveryAgent", "Review delivery and seller handoff timing facts. Return JSON with keys verified (boolean) and summary (string).", result)
        return result
