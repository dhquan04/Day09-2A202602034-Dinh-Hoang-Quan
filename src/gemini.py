"""Minimal Gemini REST client used by every agent."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GeminiAPIError(RuntimeError):
    pass


def load_local_env(project_root: Path) -> None:
    """Load unquoted KEY=VALUE pairs without adding a dotenv dependency."""
    path = project_root / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


class GeminiClient:
    def __init__(self, project_root: Path) -> None:
        load_local_env(project_root)
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        if not self.api_key:
            raise GeminiAPIError("GEMINI_API_KEY is empty. Set it in .env.")

    def generate_json(self, agent_name: str, instruction: str, evidence: dict) -> dict:
        prompt = (
            f"You are {agent_name} in an e-commerce dispute-resolution multi-agent system.\n"
            f"{instruction}\n"
            "Use only the supplied evidence. Return only a valid JSON object; do not use Markdown.\n"
            f"EVIDENCE:\n{json.dumps(evidence, ensure_ascii=False, default=str)}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GeminiAPIError(f"Gemini API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise GeminiAPIError(f"Gemini API connection failed: {exc.reason}") from exc
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise GeminiAPIError(f"Gemini returned no usable JSON for {agent_name}: {body}") from exc
