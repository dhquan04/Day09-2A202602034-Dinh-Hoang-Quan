"""Explicit EC_POLICY_V2 issue priority and resolution functions."""

from __future__ import annotations

from dataclasses import dataclass


ISSUE_PRIORITY = (
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
)


@dataclass(frozen=True)
class IssueDecision:
    primary_issue: str
    cause: str
    responsible_parties: list[dict]
    recommended_refund_brl: float
    main_action: str


def evaluate_issue_rules(order: dict, payment: dict, delivery: dict) -> list[dict]:
    """Evaluate every primary rule without changing the mandatory priority."""
    payment_total = payment["payment_total_brl"]
    paid = payment_total > 0
    delivery_variance = delivery["delivery_variance_hours"]
    late_delivery = delivery_variance is not None and delivery_variance > 0
    late_seller_ids = delivery["late_handoff_seller_ids"]
    reconciled = payment["reconciled"] is True
    return [
        {
            "priority": 1,
            "primary_issue": "canceled_order_paid",
            "matches": order["order_status"] == "canceled" and paid,
        },
        {
            "priority": 2,
            "primary_issue": "unavailable_order_paid",
            "matches": order["order_status"] == "unavailable" and paid,
        },
        {
            "priority": 3,
            "primary_issue": "late_delivery_seller",
            "matches": late_delivery and bool(late_seller_ids),
        },
        {
            "priority": 4,
            "primary_issue": "late_delivery_logistics",
            "matches": late_delivery and not late_seller_ids,
        },
        {
            "priority": 5,
            "primary_issue": "valid_split_payment",
            "matches": len(payment["payments"]) >= 2 and reconciled,
        },
        {
            "priority": 6,
            "primary_issue": "unsupported_late_claim",
            "matches": (
                delivery_variance is not None
                and delivery_variance <= 0
                and reconciled
            ),
        },
    ]


def classify_primary_issue(
    order: dict, payment: dict, delivery: dict
) -> IssueDecision:
    """Apply EC_POLICY_V2 in its mandatory order and calculate the refund.

    The first matching rule wins. Reordering these checks changes responsibility
    and can change the refund, so the sequence mirrors ``ISSUE_PRIORITY``.
    """
    payment_total = payment["payment_total_brl"]
    freight_total = payment["freight_total_brl"] or 0.0
    rule_matches = {
        rule["primary_issue"]: rule["matches"]
        for rule in evaluate_issue_rules(order, payment, delivery)
    }
    late_seller_ids = delivery["late_handoff_seller_ids"]

    # Priority 1: canceled order with captured payment.
    if rule_matches["canceled_order_paid"]:
        return IssueDecision(
            "canceled_order_paid",
            "ORDER_CANCELED_AFTER_PAYMENT",
            [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
            payment_total,
            "issue_full_refund",
        )

    # Priority 2: unavailable order with captured payment.
    if rule_matches["unavailable_order_paid"]:
        return IssueDecision(
            "unavailable_order_paid",
            "ORDER_UNAVAILABLE_AFTER_PAYMENT",
            [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}],
            payment_total,
            "issue_full_refund",
        )

    # Priority 3: delivered late after at least one seller missed handoff limit.
    if rule_matches["late_delivery_seller"]:
        return IssueDecision(
            "late_delivery_seller",
            "SELLER_HANDOFF_AFTER_LIMIT",
            [
                {"party_type": "seller", "party_id": seller_id}
                for seller_id in late_seller_ids[:3]
            ],
            freight_total,
            "refund_freight",
        )

    # Priority 4: delivered late although every seller handed off on time.
    if rule_matches["late_delivery_logistics"]:
        return IssueDecision(
            "late_delivery_logistics",
            "CARRIER_DELIVERED_AFTER_ESTIMATE",
            [{
                "party_type": "logistics_provider",
                "party_id": "LOGISTICS_PROVIDER",
            }],
            freight_total,
            "refund_freight",
        )

    # Priority 5: multiple payment rows that reconcile with item + freight.
    if rule_matches["valid_split_payment"]:
        return IssueDecision(
            "valid_split_payment",
            "MULTIPLE_PAYMENTS_RECONCILED",
            [],
            0.0,
            "explain_valid_split_payment",
        )

    # Priority 6: the late claim is contradicted by delivery/payment evidence.
    if rule_matches["unsupported_late_claim"]:
        return IssueDecision(
            "unsupported_late_claim",
            "DELIVERY_WITHIN_ESTIMATE",
            [],
            0.0,
            "reject_late_refund",
        )

    raise ValueError(
        f"Order {order['order_id']} does not match any EC_POLICY_V2 primary issue"
    )


def calculate_secondary_issues(
    product: dict, payment: dict, customer: dict
) -> list[str]:
    """Calculate all related issues in the required business order."""
    issues = []
    if len(product["items"]) >= 2:
        issues.append("multi_item_order")
    if len(product["seller_ids"]) >= 2:
        issues.append("multi_seller_order")
    if len(payment["payments"]) >= 2:
        issues.append("split_payment")
    if customer["related_order_ids"]:
        issues.append("repeat_customer")
    if len(product["category_names"]) >= 2:
        issues.append("multiple_categories")
    return issues


def calculate_resolution_actions(
    decision: IssueDecision, secondary_issues: list[str]
) -> list[str]:
    """Build actions in the required order, starting with the primary action."""
    actions = [decision.main_action]
    if decision.primary_issue == "late_delivery_seller":
        actions.append("review_seller_handoff")
    elif decision.primary_issue == "late_delivery_logistics":
        actions.append("review_carrier_delay")
    if decision.primary_issue in {"canceled_order_paid", "unavailable_order_paid"}:
        actions.append("verify_refund_completion")
    if "multi_seller_order" in secondary_issues:
        actions.append("coordinate_multi_seller_case")
    if (
        "split_payment" in secondary_issues
        and decision.primary_issue != "valid_split_payment"
    ):
        actions.append("verify_payment_allocation")
    return actions[:5]
