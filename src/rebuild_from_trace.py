"""Rebuild deterministic output fields while replaying the latest real API reviews."""

from __future__ import annotations

import json

from .main import ROOT, build_case
from .openrouter import OPENROUTER_MODEL
from .repository import OlistRepository


class TraceReviewReplay:
    LEGACY_AGENT_KEYS = {
        "CustomerAgent": "customer",
        "OrderProductAgent": "product",
        "PaymentAgent": "payment",
        "DeliveryAgent": "delivery",
    }

    def __init__(self, reviews: dict[str, bool]) -> None:
        self.reviews = reviews
        self.model = OPENROUTER_MODEL

    def generate_json(self, agent_name: str, instruction: str, evidence: dict) -> dict:
        legacy_name = self.LEGACY_AGENT_KEYS.get(agent_name)
        verified = self.reviews.get(
            agent_name, self.reviews.get(legacy_name, True)
        )
        result = {
            "verified": bool(verified),
            "summary": "replayed from latest API trace",
        }
        if agent_name.endswith("IssueAgent"):
            result["matches"] = bool(evidence["_expected_match_for_replay"])
        return result


def main() -> None:
    traces = {
        row["case_id"]: row
        for row in (
            json.loads(line)
            for line in (ROOT / "logging" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    repo = OlistRepository(ROOT / "data")
    for input_file in sorted((ROOT / "input").glob("EC_*.json")):
        case = json.loads(input_file.read_text(encoding="utf-8"))
        trace = traces[case["case_id"]]
        result, _ = build_case(case, repo, TraceReviewReplay(trace["api_reviews"]))
        (ROOT / "output" / input_file.name).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
