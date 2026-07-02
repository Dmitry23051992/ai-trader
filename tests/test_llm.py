"""Tests for core.llm.LLM."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from core.llm import LLM, LLMError


class TestLLM:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
        llm = LLM()
        with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
            llm.ask("hello")

    def test_missing_model_raises(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
        llm = LLM()
        with pytest.raises(LLMError, match="OPENROUTER_MODEL"):
            llm.ask("hello")

    @patch("core.llm.requests.post")
    def test_successful_response(self, mock_post, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("OPENROUTER_MODEL", "test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}]
        }
        mock_post.return_value = mock_response

        llm = LLM()
        result = llm.ask("Say hello")
        assert result == "Hello world"

    @patch("core.llm.requests.post")
    def test_http_error_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("OPENROUTER_MODEL", "test-model")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        mock_post.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        llm = LLM()
        with pytest.raises(LLMError, match="429"):
            llm.ask("hello")

    @patch("core.llm.requests.post")
    def test_timeout_raises(self, mock_post, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("OPENROUTER_MODEL", "test-model")

        mock_post.side_effect = requests.exceptions.Timeout("timed out")

        llm = LLM()
        with pytest.raises(LLMError, match="timed out"):
            llm.ask("hello")
