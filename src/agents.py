"""Specialist agents. Each returns evidence only from its assigned data domain."""

from __future__ import annotations

from .calculations import calculate_delivery_analysis, calculate_payment_reconciliation
from .repository import OlistRepository
from .openrouter import OpenRouterClient


class CustomerAgent:
    def investigate(self, order: dict[str, str], repo: OlistRepository, api: OpenRouterClient) -> dict:
        customer = repo.customers[order["customer_id"]]
        # Preserve orders.csv source order while linking identities through customer_unique_id.
        related = [
            row["order_id"]
            for row in repo.orders_by_unique_customer[customer["customer_unique_id"]]
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
        result = {
            "payments": payments,
            **calculate_payment_reconciliation(items, payments),
        }
        result["api_handoff"] = api.generate_json("PaymentAgent", "Review payment reconciliation. Return JSON with keys verified (boolean) and summary (string).", result)
        return result


class DeliveryAgent:
    def investigate(self, order: dict[str, str], items: list[dict[str, str]], api: OpenRouterClient) -> dict:
        result = calculate_delivery_analysis(order, items)
        result["api_handoff"] = api.generate_json("DeliveryAgent", "Review delivery and seller handoff timing facts. Return JSON with keys verified (boolean) and summary (string).", result)
        return result
