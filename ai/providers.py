"""Small, dependency-free provider adapters for AIPP's AI executor.

Secrets are read only from environment variables. No provider is called unless
the runtime explicitly enables semantic analysis and a matching key exists.
"""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    pass


def _post_json(url, headers, payload, timeout=90):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        # Provider response details are useful for quota fallback telemetry,
        # but never include request headers or API keys.
        raise ProviderError(f"AI provider HTTP {exc.code}: {detail[:1000]}") from exc


def _task_prompt(task):
    return str(task.get("prompt") or task.get("description") or task.get("input") or "")


def _openai_compatible_execute(api_key, base_url, model_name, task, extra_headers=None):
    if not api_key:
        raise ProviderError("AI provider API key is missing")
    payload = {
        "model": model_name,
        "messages": [],
        "temperature": 0.1,
        "max_tokens": int(task.get("max_output_tokens", 4096)),
    }
    system = str(task.get("system") or "")
    if system:
        payload["messages"].append({"role": "system", "content": system})
    payload["messages"].append({"role": "user", "content": _task_prompt(task)})
    if task.get("json_output"):
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {api_key}"}
    headers.update(extra_headers or {})
    result = _post_json(base_url.rstrip("/") + "/chat/completions", headers, payload)
    try:
        text = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("AI provider response did not contain message text") from exc
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("AI provider returned empty message text")
    return json.loads(text) if task.get("json_output") else text


class GeminiAdapter:
    """REST adapter for Gemini generateContent."""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY is missing")

    def execute(self, model, task):
        model_name = os.environ.get("AIPP_GEMINI_PRO_MODEL" if model.model == "pro" else "AIPP_GEMINI_FLASH_MODEL")
        model_name = model_name or {
            "pro": "gemini-3.1-pro-preview",
            "flash": "gemini-3.7-flash",
        }.get(model.model, model.model)
        payload = {
            "systemInstruction": {"parts": [{"text": str(task.get("system") or "")}]},
            "contents": [{"role": "user", "parts": [{"text": _task_prompt(task)}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": int(task.get("max_output_tokens", 4096)),
                "responseMimeType": "application/json" if task.get("json_output") else "text/plain",
            },
        }
        result = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
            {"x-goog-api-key": self.api_key},
            payload,
        )
        try:
            text = result["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Gemini response did not contain candidate text") from exc
        return json.loads(text) if task.get("json_output") else text


class ClaudeAdapter:
    """REST adapter for Anthropic Messages API."""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is missing")

    def execute(self, model, task):
        model_name = os.environ.get("AIPP_CLAUDE_MODEL") or (
            "claude-sonnet-5" if model.model == "sonnet" else model.model
        )
        payload = {
            "model": model_name,
            "max_tokens": int(task.get("max_output_tokens", 4096)),
            "messages": [{"role": "user", "content": _task_prompt(task)}],
        }
        system = task.get("system")
        if system:
            payload["system"] = system
        result = _post_json(
            os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com") + "/v1/messages",
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            payload,
        )
        try:
            text = "".join(
                block["text"] for block in result["content"] if block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise ProviderError("Claude response did not contain text content") from exc
        if not text:
            raise ProviderError("Claude returned an empty response")
        return json.loads(text) if task.get("json_output") else text


class GroqAdapter:
    """OpenAI-compatible adapter for Groq's hosted inference API."""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "").strip()
        if not self.api_key:
            raise ProviderError("GROQ_API_KEY is missing")

    def execute(self, model, task):
        model_name = os.environ.get("AIPP_GROQ_MODEL") or model.model
        return _openai_compatible_execute(
            self.api_key,
            os.environ.get("AIPP_GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            model_name,
            task,
        )


class OpenRouterAdapter:
    """OpenAI-compatible adapter for OpenRouter model routing."""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not self.api_key:
            raise ProviderError("OPENROUTER_API_KEY is missing")

    def execute(self, model, task):
        model_name = os.environ.get("AIPP_OPENROUTER_MODEL") or model.model
        return _openai_compatible_execute(
            self.api_key,
            os.environ.get("AIPP_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            model_name,
            task,
            extra_headers={
                "HTTP-Referer": os.environ.get("AIPP_OPENROUTER_SITE_URL", "https://aipp-control-panel.onrender.com"),
                "X-Title": "AIPP",
            },
        )


def configured_adapter(provider):
    if provider == "gemini":
        return GeminiAdapter()
    if provider == "groq":
        return GroqAdapter()
    if provider == "openrouter":
        return OpenRouterAdapter()
    if provider == "claude":
        return ClaudeAdapter()
    raise ProviderError(f"Unsupported AI provider: {provider}")
