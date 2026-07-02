from __future__ import annotations

import os
from typing import Any

import requests
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

try:
    from dotenv import load_dotenv
except ImportError:  # Optional dependency for .env file loading.
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

from core.logger import log

URL = "https://openrouter.ai/api/v1/chat/completions"

# Module-level variables removed — values are resolved lazily at call time
# so that tests and environment changes work correctly.

DEFAULT_TIMEOUT = 300
MAX_RETRIES = 3


class LLMError(RuntimeError):
    """Base exception for LLM-related errors."""


class LLM:

    @staticmethod
    def _resolve_api_key() -> str:
        """Read API key lazily so tests can monkeypatch env vars."""
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise LLMError(
                "OPENROUTER_API_KEY is not set. Add it to environment or .env file."
            )
        return key

    @staticmethod
    def _resolve_model() -> str:
        """Read model name lazily so tests can monkeypatch env vars."""
        model = os.getenv("OPENROUTER_MODEL")
        if not model:
            raise LLMError(
                "OPENROUTER_MODEL is not set. Add it to environment or .env file."
            )
        return model

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        before_sleep=before_sleep_log(log, "WARNING"),
        reraise=True,
    )
    def ask(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """Send a prompt to the LLM and return the response text.

        Args:
            prompt: The prompt text.
            model: Override the default model.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum tokens in the response.

        Returns:
            The model's response text.

        Raises:
            LLMError: If the API key, model, or request fails.
        """
        api_key = self._resolve_api_key()
        model_name = model or self._resolve_model()

        if not api_key:
            raise LLMError(
                "OPENROUTER_API_KEY is not set. Add it to environment or .env file."
            )

        if not model_name:
            raise LLMError(
                "OPENROUTER_MODEL is not set. Add it to environment or .env file."
            )

        headers: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        log.debug("LLM request: model={} prompt_len={}", model_name, len(prompt))

        try:
            response = requests.post(
                URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            result: str = response.json()["choices"][0]["message"]["content"]
            log.debug("LLM response received: len={}", len(result))
            return result

        except requests.exceptions.Timeout as exc:
            raise LLMError(f"LLM request timed out after {timeout}s") from exc

        except requests.exceptions.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else "N/A"
            body = exc.response.text[:500] if exc.response is not None else ""
            raise LLMError(
                f"LLM request failed (HTTP {status}): {body}"
            ) from exc

        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response format: {exc}") from exc
