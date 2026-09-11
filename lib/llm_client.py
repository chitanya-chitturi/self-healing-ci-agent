"""Generic client for any OpenAI-compatible chat-completions endpoint.

Which provider/model to call is entirely config-driven (config/llm.yml) —
this module has no provider-specific knowledge. Swapping Groq for GitHub
Models, OpenAI, or anything else that speaks this format is a config edit,
not a code change.
"""
import json
import os
import re
from pathlib import Path

import requests
import yaml

LLM_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "llm.yml"


def load_llm_config() -> dict:
    return yaml.safe_load(LLM_CONFIG_PATH.read_text())


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"Could not parse JSON from model response: {text!r}")


def chat_json(system_prompt: str, user_prompt: str, temperature: float = 0) -> dict:
    """Sends a chat completion request and returns the parsed JSON object
    the model responded with. Requires the model to be instructed (via
    system_prompt) to respond with JSON only."""
    config = load_llm_config()
    api_key = os.environ[config["api_key_env"]]

    payload = {
        "model": config["model"],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = requests.post(
        config["base_url"],
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    )
    if not resp.ok:
        # Some OpenAI-compatible providers reject an unsupported
        # response_format instead of ignoring it — retry once without it.
        payload.pop("response_format", None)
        resp = requests.post(
            config["base_url"],
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(content)
