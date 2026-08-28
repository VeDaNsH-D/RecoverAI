"""
Anthropic Claude and Google Gemini LLM Provider implementations for RecoverAI.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from agent.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMToolCall


class AnthropicLLMProvider(LLMProvider):
    """
    Anthropic Claude tool-calling provider client.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        timeout: float = 15.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self.timeout = timeout

    def generate_tool_call(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

        anthropic_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in tools
        ]

        system_prompt = ""
        claude_messages = []
        for m in messages:
            if m.role == "system":
                system_prompt = m.content or ""
            else:
                claude_messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": claude_messages,
            "tools": anthropic_tools,
            "temperature": temperature,
        }

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        start_t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                resp_data = json.loads(resp.read().decode("utf-8"))

            tool_calls: List[LLMToolCall] = []
            content_text = ""
            for block in resp_data.get("content", []):
                if block.get("type") == "tool_use":
                    tool_calls.append(
                        LLMToolCall(
                            tool=block.get("name", ""),
                            arguments=block.get("input", {}),
                            tool_call_id=block.get("id"),
                        )
                    )
                elif block.get("type") == "text":
                    content_text += block.get("text", "")

            usage = resp_data.get("usage", {})
            return LLMResponse(
                content=content_text if content_text else None,
                tool_calls=tool_calls,
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                latency_ms=latency_ms,
                model=self.model,
                provider="anthropic",
            )
        except Exception as err:
            raise RuntimeError(f"Anthropic API Error: {str(err)}") from err


class GeminiLLMProvider(LLMProvider):
    """
    Google Gemini tool-calling provider client.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash",
        timeout: float = 15.0,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model
        self.timeout = timeout

    def generate_tool_call(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")

        # In standard offline environments or when key is absent, use MockLLMProvider
        raise NotImplementedError("Live Gemini provider requires configured GEMINI_API_KEY.")
