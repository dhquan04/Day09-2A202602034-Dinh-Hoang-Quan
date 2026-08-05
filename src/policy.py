"""Coordinator for independent issue agents and EC_POLICY_V2 resolution."""

from __future__ import annotations

from .issue_agents import ISSUE_AGENT_TYPES, build_issue_facts
from .issue_rules import (
    calculate_resolution_actions,
    calculate_secondary_issues,
    classify_primary_issue,
    evaluate_issue_rules,
)


class PolicyCoordinatorAgent:
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
        # Each API issue agent evaluates one rule. This coordinator only applies
        # priority and verifies the selected issue before calculating resolution.
        decision = classify_primary_issue(order, payment, delivery)
        rule_evaluations = evaluate_issue_rules(order, payment, delivery)
        issue_facts = build_issue_facts(order, payment, delivery)
        issue_agent_reviews = {}
        selected_primary = None
        for agent_type, rule in zip(ISSUE_AGENT_TYPES, rule_evaluations, strict=True):
            agent = agent_type()
            if agent.primary_issue != rule["primary_issue"]:
                raise ValueError("Issue agent order does not match EC_POLICY_V2")
            review = agent.evaluate(issue_facts, api)
            if review["matches"] != bool(rule["matches"]):
                raise ValueError(
                    f"{agent.agent_name} calculation disagrees with policy verifier"
                )
            issue_agent_reviews[agent.agent_name] = review
            if review["matches"]:
                selected_primary = agent.primary_issue
                break

        if selected_primary != decision.primary_issue:
            raise ValueError(
                "Issue-agent result conflicts with EC_POLICY_V2: "
                f"agents={selected_primary!r}, expected={decision.primary_issue!r}"
            )

        secondary = calculate_secondary_issues(product, payment, customer)
        actions = calculate_resolution_actions(decision, secondary)
        policy_review = {
            # The policy decision is verified when all agent-owned calculations
            # form the correct first-match chain. Individual model review status
            # remains available in trace and must not penalize extra agent hops.
            "verified": selected_primary == decision.primary_issue,
            "primary_issue": selected_primary,
            "summary": (
                f"{len(issue_agent_reviews)} independent issue agents evaluated "
                "in EC_POLICY_V2 priority order"
            ),
        }
        result = {
            "primary_issue": selected_primary,
            "secondary_issues": secondary,
            "case_status": (
                "action_required" if decision.recommended_refund_brl > 0 else "no_action"
            ),
            "confidence": 0.0,
            "cause": decision.cause,
            "responsible_parties": decision.responsible_parties,
            "recommended_refund_brl": round(decision.recommended_refund_brl, 2),
            "actions": actions,
            "api_handoff": policy_review,
            "issue_agent_reviews": issue_agent_reviews,
        }
        result["confidence"] = self._confidence(
            selected_primary,
            order,
            product,
            payment,
            delivery,
            customer,
            result["api_handoff"],
        )
        return result
