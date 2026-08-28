"""
OpenAI / Azure OpenAI LLM Provider client for RecoverAI.
Translates tools into OpenAI function/tool calling JSON schemas.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from agent.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMToolCall


class OpenAILLMProvider(LLMProvider):
    """
    OpenAI structured tool-calling provider client.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 15.0,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate_tool_call(
        self,
        messages: List[LLMMessage],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        # Convert tools to OpenAI tool format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

        formatted_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "tools": openai_tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        start_t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                resp_data = json.loads(resp.read().decode("utf-8"))

            choice = resp_data["choices"][0]["message"]
            raw_tool_calls = choice.get("tool_calls", [])
            tool_calls: List[LLMToolCall] = []

            for rtc in raw_tool_calls:
                fn = rtc.get("function", {})
                args = json.loads(fn.get("arguments", "{}"))
                tool_calls.append(
                    LLMToolCall(
                        tool=fn.get("name", ""),
                        arguments=args,
                        tool_call_id=rtc.get("id"),
                    )
                )

            usage = resp_data.get("usage", {})
            return LLMResponse(
                content=choice.get("content"),
                tool_calls=tool_calls,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                latency_ms=latency_ms,
                model=self.model,
                provider="openai",
            )
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            raise RuntimeError(f"OpenAI API Error ({err.code}): {err_body}") from err
        except urllib.error.URLError as err:
            raise TimeoutError(f"OpenAI API connection failed/timed out: {str(err)}") from err
