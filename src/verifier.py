"""Final agent: reject malformed output before it is written to disk."""

from __future__ import annotations


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
