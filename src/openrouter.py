"""OpenRouter chat-completions client for API-backed agents."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .gemini import load_local_env


class OpenRouterAPIError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, project_root: Path) -> None:
        load_local_env(project_root)
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")
        if not self.api_key:
            raise OpenRouterAPIError("OPENROUTER_API_KEY is empty. Set a rotated key in .env.")

    def generate_json(self, agent_name: str, instruction: str, evidence: dict) -> dict:
        prompt = (
            f"You are {agent_name} in an e-commerce dispute-resolution multi-agent system.\n"
            f"{instruction}\n"
            "Use only the supplied evidence. Return one valid JSON object and no Markdown.\n"
            f"EVIDENCE:\n{json.dumps(evidence, ensure_ascii=False, default=str)}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        request = Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenRouterAPIError(f"OpenRouter API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise OpenRouterAPIError(f"OpenRouter API connection failed: {exc.reason}") from exc
        try:
            content = body["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content[content.find("{") : content.rfind("}") + 1]
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise OpenRouterAPIError(f"OpenRouter returned no usable JSON for {agent_name}: {body}") from exc
