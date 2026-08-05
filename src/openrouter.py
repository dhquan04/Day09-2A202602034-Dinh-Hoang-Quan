"""OpenRouter chat-completions client for API-backed agents."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .gemini import load_local_env


OPENROUTER_MODEL = "meta-llama/llama-3.1-8b-instruct"
MODEL_PARAMETER_SIZE_BILLIONS = 8
MAX_ALLOWED_PARAMETER_SIZE_BILLIONS = 10
MAX_API_ATTEMPTS = 3

if MODEL_PARAMETER_SIZE_BILLIONS > MAX_ALLOWED_PARAMETER_SIZE_BILLIONS:
    raise RuntimeError("Configured OpenRouter model exceeds the 10B parameter limit")


class OpenRouterAPIError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, project_root: Path) -> None:
        load_local_env(project_root)
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        # The assignment requires the model name in source code, not in .env.
        self.model = OPENROUTER_MODEL
        if not self.api_key:
            raise OpenRouterAPIError("OPENROUTER_API_KEY is empty. Set a rotated key in .env.")

    def generate_json(self, agent_name: str, instruction: str, evidence: dict) -> dict:
        public_evidence = {
            key: value for key, value in evidence.items() if not key.startswith("_")
        }
        prompt = (
            f"You are {agent_name} in an e-commerce dispute-resolution multi-agent system.\n"
            f"{instruction}\n"
            "Use only the supplied evidence. Return one valid JSON object and no Markdown.\n"
            f"EVIDENCE:\n{json.dumps(public_evidence, ensure_ascii=False, default=str)}"
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
        body = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                with urlopen(request, timeout=90) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == MAX_API_ATTEMPTS:
                    raise OpenRouterAPIError(
                        f"OpenRouter API HTTP {exc.code}: {detail}"
                    ) from exc
            except (URLError, TimeoutError) as exc:
                if attempt == MAX_API_ATTEMPTS:
                    reason = getattr(exc, "reason", str(exc))
                    raise OpenRouterAPIError(
                        f"OpenRouter API failed after {MAX_API_ATTEMPTS} attempts: {reason}"
                    ) from exc
            time.sleep(2 ** (attempt - 1))

        if body is None:
            raise OpenRouterAPIError("OpenRouter API returned no response body")
        try:
            content = body["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content[content.find("{") : content.rfind("}") + 1]
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise OpenRouterAPIError(f"OpenRouter returned no usable JSON for {agent_name}: {body}") from exc
