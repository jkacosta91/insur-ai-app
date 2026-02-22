from __future__ import annotations

import os
from typing import Any, Dict

import requests


OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def send_openai_prompt(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float = 0.0,
    timeout: int = 45,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "status_code": None,
            "text": "",
            "error": "missing_api_key",
            "raw": None,
            "error_text": "",
        }

    body = {
        "model": model,
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": "Responde de forma precisa y sigue el formato solicitado."},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }

    try:
        response = requests.post(OPENAI_URL, headers=headers, json=body, timeout=timeout)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "text": "",
            "error": f"network_error:{type(exc).__name__}",
            "raw": None,
            "error_text": str(exc),
        }

    if response.status_code != 200:
        return {
            "ok": False,
            "status_code": response.status_code,
            "text": "",
            "error": "http_error",
            "raw": None,
            "error_text": response.text or "",
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "status_code": response.status_code,
            "text": "",
            "error": "invalid_json_response",
            "raw": None,
            "error_text": response.text or "",
        }

    return {
        "ok": True,
        "status_code": response.status_code,
        "text": extract_openai_text(payload),
        "error": None,
        "raw": payload,
        "error_text": "",
    }


def extract_openai_text(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if isinstance(choices, list) and choices:
        first = choices[0] or {}
        message = first.get("message", {}) if isinstance(first, dict) else {}
        if isinstance(message, dict):
            return message.get("content", "") or ""
    return ""


# Backward compatible alias for older imports.
send_anthropic_prompt = send_openai_prompt
