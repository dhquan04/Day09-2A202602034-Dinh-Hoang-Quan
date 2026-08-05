"""Coordinator entry point: python -m src.main."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from datetime import datetime, timezone
import sys

from .agents import CustomerAgent, DeliveryAgent, OrderProductAgent, PaymentAgent
from .policy import PolicyAgent
from .repository import OlistRepository
from .verifier import VerifierAgent
from .openrouter import OpenRouterClient

ROOT = Path(__file__).resolve().parents[1]


def build_case(case: dict, repo: OlistRepository, api: OpenRouterClient) -> tuple[dict, dict[str, bool]]:
    order_id = case["customer_request"]["claimed_order_id"]
    order = repo.orders[order_id]
    customer = CustomerAgent().investigate(order, repo, api)
    product = OrderProductAgent().investigate(order_id, repo, api)
    payment = PaymentAgent().investigate(order_id, product["items"], repo, api)
    delivery = DeliveryAgent().investigate(order, product["items"], api)
    policy = PolicyAgent().decide(order, product, payment, delivery, customer, api)
    item_ids = [f"{order_id}:{item['order_item_id']}" for item in product["items"]][:5]
    payment_ids = [f"{order_id}:{row['payment_sequential']}" for row in payment["payments"]][:5]
    evidence = [f"order:{order_id}"] + [f"item:{value}" for value in item_ids] + [f"payment:{value}" for value in payment_ids]
    evidence += [f"seller:{party['party_id']}" for party in policy["responsible_parties"] if party["party_type"] == "seller"]
    evidence.append(f"policy:{policy['cause']}")
    result = {"case_id": case["case_id"], "case_assessment": {key: policy[key] for key in ("primary_issue", "secondary_issues", "case_status", "confidence")},
            "affected_entities": {"order_ids": [order_id], "item_ids": item_ids, "seller_ids": product["seller_ids"], "payment_ids": payment_ids},
            "customer_context": {"customer_unique_id": customer["customer_unique_id"], "related_order_ids": customer["related_order_ids"]}, "product_context": {"product_ids": product["product_ids"], "category_names": product["category_names"]},
            "delivery_analysis": {key: delivery[key] for key in ("delivered_at", "estimated_delivery_at", "carrier_handoff_at", "delivery_variance_hours", "seller_handoff_analysis", "late_handoff_seller_ids")},
            "payment_reconciliation": {"currency": "BRL", **{key: payment[key] for key in ("item_total_brl", "freight_total_brl", "expected_total_brl", "payment_total_brl", "difference_brl", "reconciled")}, "payment_types": list(dict.fromkeys(row["payment_type"] for row in payment["payments"]))},
            "root_cause_analysis": {"ranked_causes": [{"cause_code": policy["cause"], "rank": 1}], "responsible_parties": policy["responsible_parties"]},
            "evidence_ids": evidence[:20], "financial_resolution": {"currency": "BRL", "recommended_refund_brl": policy["recommended_refund_brl"]}, "resolution_actions": policy["actions"]}
    VerifierAgent().verify(result)
    api_reviews = {name: bool(value.get("api_handoff", {}).get("verified")) for name, value in (("customer", customer), ("product", product), ("payment", payment), ("delivery", delivery), ("policy", policy))}
    return result, api_reviews


def main() -> None:
    repo = OlistRepository(ROOT / "data")
    api = OpenRouterClient(ROOT)
    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    trace_lines = []
    for input_file in sorted((ROOT / "input").glob("EC_*.json")):
        case = json.loads(input_file.read_text(encoding="utf-8"))
        result, api_reviews = build_case(case, repo, api)
        (output_dir / input_file.name).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        trace_lines.append(json.dumps({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "case_id": case["case_id"],
            "claimed_order_id": case["customer_request"]["claimed_order_id"],
            "handoff": ["CustomerAgent", "OrderProductAgent", "PaymentAgent", "DeliveryAgent", "PolicyAgent", "VerifierAgent"],
            "api_model": api.model,
            "api_reviews": api_reviews,
            "primary_issue": result["case_assessment"]["primary_issue"],
            "verification": "passed",
        }, ensure_ascii=False))
    logging_dir = ROOT / "logging"
    logging_dir.mkdir(exist_ok=True)
    (logging_dir / "trace.jsonl").write_text("\n".join(trace_lines) + "\n", encoding="utf-8")
    metadata = {
        "model": api.model,
        "parameter_size": "8B parameters",
        "framework": "Python standard library + OpenRouter Chat Completions API",
        "runtime": {"python": sys.version.split()[0], "platform": platform.platform()},
        "run_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "cases_processed": len(trace_lines),
    }
    (logging_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
