"""
Google Gemini LLM Provider adapter for RecoverAI.
Implements structured tool-calling for Gemini 2.0 / 1.5 models.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

from agent.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMToolCall


class GeminiLLMProvider(LLMProvider):
    """
    Google Gemini tool-calling provider client using REST API.
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

        # Translate tools to Gemini function declarations
        function_declarations = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
            for t in tools
        ]

        # Assemble Gemini contents
        contents = []
        system_instruction = None
        for m in messages:
            if m.role == "system":
                system_instruction = {"parts": [{"text": m.content or ""}]}
            elif m.role == "assistant":
                contents.append({"role": "model", "parts": [{"text": m.content or ""}]})
            else:
                contents.append({"role": "user", "parts": [{"text": m.content or ""}]})

        payload: Dict[str, Any] = {
            "contents": contents,
            "tools": [{"functionDeclarations": function_declarations}],
            "generationConfig": {"temperature": temperature},
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        start_t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                resp_data = json.loads(resp.read().decode("utf-8"))

            tool_calls: List[LLMToolCall] = []
            content_text = ""

            candidates = resp_data.get("candidates", [])
            if candidates:
                candidate = candidates[0]
                content = candidate.get("content", {})
                parts = content.get("parts", [])
                for part in parts:
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        tool_calls.append(
                            LLMToolCall(
                                tool=fc.get("name", ""),
                                arguments=fc.get("args", {}),
                            )
                        )
                    elif "text" in part:
                        content_text += part["text"]

            usage = resp_data.get("usageMetadata", {})
            prompt_tokens = usage.get("promptTokenCount", 0)
            completion_tokens = usage.get("candidatesTokenCount", 0)

            return LLMResponse(
                content=content_text if content_text else None,
                tool_calls=tool_calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                latency_ms=latency_ms,
                model=self.model,
                provider="gemini",
            )
        except Exception as err:
            raise RuntimeError(f"Google Gemini API Error: {str(err)}") from err
