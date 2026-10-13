"""Call third-party LLM APIs from a workflow.

``LLMAPICall`` speaks the OpenAI-compatible ``/chat/completions`` protocol,
which is supported by OpenAI, DeepSeek, Moonshot/Kimi, Qwen (DashScope
compatible mode), SiliconFlow, Groq, OpenRouter, and self-hosted servers
such as Ollama, vLLM and LM Studio.  The provider is fully user-defined:
base URL, API key and model name are plain inputs — no vendor list, no
hardcoded endpoints.

No extra Python dependency: the request is made with the standard library
``urllib``.  The API key is a normal widget value and is stored in the
workflow JSON like any other input — prefer a throwaway/limited key, or
leave it empty when the endpoint does not need one (e.g. local Ollama).
"""

import json
import urllib.error
import urllib.request

from ..utils.optional_values import has_value


class LLMAPICall:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_url": ("STRING", {"default": "https://api.deepseek.com/v1",
                                        "tooltip": "Provider base URL, e.g. https://api.openai.com/v1, http://127.0.0.1:11434/v1 (Ollama)"}),
                "model": ("STRING", {"default": "deepseek-chat",
                                     "tooltip": "Model name as the provider expects it, e.g. gpt-4o-mini / deepseek-chat / qwen2.5:7b"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "system_prompt": ("STRING", {"default": "", "multiline": True}),
                "api_key": ("STRING", {"default": "",
                                       "tooltip": "API key sent as 'Authorization: Bearer <key>'. Leave empty for endpoints that need none (e.g. local Ollama). Stored in the workflow JSON — prefer a limited key."}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.05}),
                "max_tokens": ("INT", {"default": 1024, "min": 0, "max": 1000000,
                                       "tooltip": "Response token cap; 0 = provider default"}),
                "timeout": ("FLOAT", {"default": 60.0, "min": 1.0, "max": 600.0, "step": 1.0,
                                      "tooltip": "Request timeout in seconds"}),
            },
        }

    CATEGORY = "Optional Inputs/LLM"
    DESCRIPTION = (
        "Call any OpenAI-compatible chat completion API with a fully custom "
        "provider: base URL, API key and model. Works with OpenAI, DeepSeek, "
        "Moonshot, Qwen, SiliconFlow, Groq, OpenRouter, and local Ollama / "
        "vLLM / LM Studio. Returns the assistant message text."
    )

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("response",)
    FUNCTION = "call"

    def call(self, base_url, model, prompt, system_prompt, api_key,
             temperature, max_tokens, timeout):
        url = base_url.rstrip("/") + "/chat/completions"

        messages = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens > 0:
            body["max_tokens"] = max_tokens

        headers = {"Content-Type": "application/json"}
        if api_key.strip():
            headers["Authorization"] = "Bearer {}".format(api_key.strip())

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            raise RuntimeError(
                "LLM API returned HTTP {}: {}".format(e.code, detail or e.reason)
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                "Could not reach LLM API at {}: {}. Check base_url and "
                "network.".format(url, e.reason)
            ) from e
        except json.JSONDecodeError as e:
            raise RuntimeError(
                "LLM API response was not JSON: {}".format(e)
            ) from e

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(
                "Unexpected LLM API response structure: {}".format(
                    json.dumps(payload, ensure_ascii=False)[:500]
                )
            ) from e

        if isinstance(content, list):
            # Some providers return content parts (e.g. with reasoning models)
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if not has_value(content):
            content = ""
        return (str(content),)
