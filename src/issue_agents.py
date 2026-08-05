"""API-backed agents that each evaluate exactly one EC_POLICY_V2 issue."""

from __future__ import annotations


class IssueAgentError(ValueError):
    pass


class BaseIssueAgent:
    agent_name = "BaseIssueAgent"
    primary_issue = ""
    priority = 0
    condition = ""
    fact_names: tuple[str, ...] = ()

    def calculate_match(self, facts: dict) -> bool:
        """Calculate this agent's one business condition."""
        raise NotImplementedError

    def evaluate(self, facts: dict, api) -> dict:
        """Calculate one rule and ask the API model to review that calculation."""
        scoped_facts = {name: facts[name] for name in self.fact_names}
        calculated_match = self.calculate_match(scoped_facts)
        evidence = {
            "policy_version": "EC_POLICY_V2",
            "priority": self.priority,
            "primary_issue": self.primary_issue,
            "condition": self.condition,
            "facts": scoped_facts,
            "calculated_match": calculated_match,
            # Used only by TraceReviewReplay; OpenRouterClient removes private keys.
            "_expected_match_for_replay": calculated_match,
        }
        review = api.generate_json(
            self.agent_name,
            "Review only your assigned EC_POLICY_V2 condition and the supplied "
            "calculated_match. Do not assess another issue, do not trust a customer "
            "claim, and do not invent missing facts. Return JSON with keys verified "
            "(boolean), matches (boolean), and summary (string).",
            evidence,
        )
        model_match = review.get("matches")
        model_agrees = type(model_match) is bool and model_match == calculated_match
        return {
            "agent_name": self.agent_name,
            "primary_issue": self.primary_issue,
            "priority": self.priority,
            "matches": calculated_match,
            "verified": bool(review.get("verified")) and model_agrees,
            "model_matches": model_match,
            "summary": str(review.get("summary", "")),
        }


class CanceledOrderIssueAgent(BaseIssueAgent):
    agent_name = "CanceledOrderIssueAgent"
    primary_issue = "canceled_order_paid"
    priority = 1
    condition = "order_status == canceled AND payment_total_brl > 0"
    fact_names = ("order_status", "payment_total_brl")

    def calculate_match(self, facts: dict) -> bool:
        return facts["order_status"] == "canceled" and facts["payment_total_brl"] > 0


class UnavailableOrderIssueAgent(BaseIssueAgent):
    agent_name = "UnavailableOrderIssueAgent"
    primary_issue = "unavailable_order_paid"
    priority = 2
    condition = "order_status == unavailable AND payment_total_brl > 0"
    fact_names = ("order_status", "payment_total_brl")

    def calculate_match(self, facts: dict) -> bool:
        return (
            facts["order_status"] == "unavailable"
            and facts["payment_total_brl"] > 0
        )


class LateDeliverySellerIssueAgent(BaseIssueAgent):
    agent_name = "LateDeliverySellerIssueAgent"
    primary_issue = "late_delivery_seller"
    priority = 3
    condition = (
        "delivery_variance_hours > 0 AND late_handoff_seller_ids is not empty"
    )
    fact_names = ("delivery_variance_hours", "late_handoff_seller_ids")

    def calculate_match(self, facts: dict) -> bool:
        variance = facts["delivery_variance_hours"]
        return (
            variance is not None
            and variance > 0
            and bool(facts["late_handoff_seller_ids"])
        )


class LateDeliveryLogisticsIssueAgent(BaseIssueAgent):
    agent_name = "LateDeliveryLogisticsIssueAgent"
    primary_issue = "late_delivery_logistics"
    priority = 4
    condition = "delivery_variance_hours > 0 AND late_handoff_seller_ids is empty"
    fact_names = ("delivery_variance_hours", "late_handoff_seller_ids")

    def calculate_match(self, facts: dict) -> bool:
        variance = facts["delivery_variance_hours"]
        return (
            variance is not None
            and variance > 0
            and not facts["late_handoff_seller_ids"]
        )


class ValidSplitPaymentIssueAgent(BaseIssueAgent):
    agent_name = "ValidSplitPaymentIssueAgent"
    primary_issue = "valid_split_payment"
    priority = 5
    condition = "payment_row_count >= 2 AND reconciled == true"
    fact_names = ("payment_row_count", "reconciled")

    def calculate_match(self, facts: dict) -> bool:
        return facts["payment_row_count"] >= 2 and facts["reconciled"] is True


class UnsupportedLateClaimIssueAgent(BaseIssueAgent):
    agent_name = "UnsupportedLateClaimIssueAgent"
    primary_issue = "unsupported_late_claim"
    priority = 6
    condition = "delivery_variance_hours <= 0 AND reconciled == true"
    fact_names = ("delivery_variance_hours", "reconciled")

    def calculate_match(self, facts: dict) -> bool:
        variance = facts["delivery_variance_hours"]
        return (
            variance is not None
            and variance <= 0
            and facts["reconciled"] is True
        )


ISSUE_AGENT_TYPES = (
    CanceledOrderIssueAgent,
    UnavailableOrderIssueAgent,
    LateDeliverySellerIssueAgent,
    LateDeliveryLogisticsIssueAgent,
    ValidSplitPaymentIssueAgent,
    UnsupportedLateClaimIssueAgent,
)


def build_issue_facts(order: dict, payment: dict, delivery: dict) -> dict:
    """Expose only calculated facts needed by the six issue agents."""
    return {
        "order_status": order["order_status"],
        "payment_total_brl": payment["payment_total_brl"],
        "payment_row_count": len(payment["payments"]),
        "reconciled": payment["reconciled"],
        "delivery_variance_hours": delivery["delivery_variance_hours"],
        "late_handoff_seller_ids": delivery["late_handoff_seller_ids"],
    }
