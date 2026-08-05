"""Pure calculation functions used by specialist agents.

The API model reviews evidence, but it never performs authoritative arithmetic.
All scorable numbers are derived here from CSV rows with the formulas in README.
"""

from __future__ import annotations

from datetime import datetime


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
RECONCILIATION_TOLERANCE_BRL = 0.10


def calculate_hours_between(later: str | None, earlier: str | None) -> float | None:
    """Return ``later - earlier`` in hours; return null when it cannot be calculated."""
    if not later or not earlier:
        return None
    later_at = datetime.strptime(later, TIME_FORMAT)
    earlier_at = datetime.strptime(earlier, TIME_FORMAT)
    return round((later_at - earlier_at).total_seconds() / 3600, 2)


def calculate_payment_reconciliation(
    items: list[dict[str, str]], payments: list[dict[str, str]]
) -> dict:
    """Calculate every payment parameter from all item and payment rows.

    Empty item input has zero sums, but no item ledger exists for reconciliation.
    """
    item_total = round(sum(float(item["price"]) for item in items), 2)
    freight_total = round(sum(float(item["freight_value"]) for item in items), 2)
    payment_total = round(
        sum(float(payment["payment_value"]) for payment in payments), 2
    )

    if not items:
        return {
            "item_total_brl": 0.0,
            "freight_total_brl": 0.0,
            "expected_total_brl": None,
            "payment_total_brl": payment_total,
            "difference_brl": None,
            "reconciled": None,
        }

    expected_total = round(item_total + freight_total, 2)
    difference = round(payment_total - expected_total, 2)
    return {
        "item_total_brl": item_total,
        "freight_total_brl": freight_total,
        "expected_total_brl": expected_total,
        "payment_total_brl": payment_total,
        "difference_brl": difference,
        "reconciled": abs(difference) <= RECONCILIATION_TOLERANCE_BRL,
    }


def calculate_seller_handoff_analysis(
    order: dict[str, str], items: list[dict[str, str]]
) -> list[dict]:
    """Calculate carrier handoff variance against each seller's earliest limit."""
    items_by_seller: dict[str, list[dict[str, str]]] = {}
    for item in items:
        items_by_seller.setdefault(item["seller_id"], []).append(item)

    analysis = []
    for seller_id, seller_items in items_by_seller.items():
        shipping_limit = min(item["shipping_limit_date"] for item in seller_items)
        variance = calculate_hours_between(
            order["order_delivered_carrier_date"], shipping_limit
        )
        analysis.append({
            "seller_id": seller_id,
            "shipping_limit_at": shipping_limit,
            "handoff_variance_hours": variance,
            "late_handoff": variance is not None and variance > 0,
        })
    return analysis


def calculate_delivery_analysis(
    order: dict[str, str], items: list[dict[str, str]]
) -> dict:
    """Calculate delivery and seller-handoff parameters from order/item rows."""
    seller_analysis = calculate_seller_handoff_analysis(order, items)
    return {
        "delivered_at": order["order_delivered_customer_date"] or None,
        "estimated_delivery_at": order["order_estimated_delivery_date"] or None,
        "carrier_handoff_at": order["order_delivered_carrier_date"] or None,
        "delivery_variance_hours": calculate_hours_between(
            order["order_delivered_customer_date"],
            order["order_estimated_delivery_date"],
        ),
        "seller_handoff_analysis": seller_analysis,
        "late_handoff_seller_ids": [
            entry["seller_id"] for entry in seller_analysis if entry["late_handoff"]
        ],
    }
