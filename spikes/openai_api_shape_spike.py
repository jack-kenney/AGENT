import asyncio
import json
import os
from pathlib import Path

import aiohttp
from dotenv import load_dotenv


def _short_text(s: str, n: int = 220) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "..."


async def call_chat_completions(session: aiohttp.ClientSession, url: str, key: str, model: str) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply in one short line."},
            {"role": "user", "content": "Say OPENAI_CHAT_OK"},
        ],
        "max_completion_tokens": 32,
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    async with session.post(url + "/chat/completions", headers=headers, json=payload) as resp:
        raw = await resp.text()
        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            pass
        return {
            "endpoint": "chat/completions",
            "status": resp.status,
            "finish_reason": ((data or {}).get("choices") or [{}])[0].get("finish_reason") if isinstance(data, dict) else None,
            "content": _short_text((((data or {}).get("choices") or [{}])[0].get("message") or {}).get("content") if isinstance(data, dict) else ""),
            "error": ((data or {}).get("error") if isinstance(data, dict) else None) or _short_text(raw),
        }


async def call_responses(session: aiohttp.ClientSession, url: str, key: str, model: str) -> dict:
    payload = {
        "model": model,
        "input": "Say OPENAI_RESPONSES_OK",
        "max_output_tokens": 32,
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    async with session.post(url + "/responses", headers=headers, json=payload) as resp:
        raw = await resp.text()
        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            pass

        output_text = ""
        if isinstance(data, dict):
            output_text = data.get("output_text") or ""
            if not output_text:
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        for part in item.get("content", []):
                            if part.get("type") == "output_text" and part.get("text"):
                                output_text += part.get("text")

        return {
            "endpoint": "responses",
            "status": resp.status,
            "status_field": (data or {}).get("status") if isinstance(data, dict) else None,
            "incomplete_reason": ((data or {}).get("incomplete_details") or {}).get("reason") if isinstance(data, dict) else None,
            "content": _short_text(output_text),
            "error": ((data or {}).get("error") if isinstance(data, dict) else None) or _short_text(raw),
        }


async def call_model_retrieve(session: aiohttp.ClientSession, url: str, key: str, model: str) -> dict:
    headers = {"Authorization": f"Bearer {key}"}
    async with session.get(url + f"/models/{model}", headers=headers) as resp:
        raw = await resp.text()
        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            pass
        return {
            "endpoint": f"models/{model}",
            "status": resp.status,
            "id": (data or {}).get("id") if isinstance(data, dict) else None,
            "owned_by": (data or {}).get("owned_by") if isinstance(data, dict) else None,
            "error": ((data or {}).get("error") if isinstance(data, dict) else None) or _short_text(raw),
        }


async def main() -> None:
    load_dotenv(dotenv_path=Path(".env"))

    key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-sol")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    print("OPENAI API SHAPE SPIKE")
    print(f"Model: {model}")
    print(f"Base URL: {base_url}")

    if not key:
        print("FAIL: OPENAI_API_KEY missing")
        return

    timeout = aiohttp.ClientTimeout(connect=10, total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        model_probe = await call_model_retrieve(session, base_url, key, model)
        chat_probe = await call_chat_completions(session, base_url, key, model)
        resp_probe = await call_responses(session, base_url, key, model)

    print("\nMODEL RETRIEVE")
    print(json.dumps(model_probe, indent=2))

    print("\nCHAT COMPLETIONS")
    print(json.dumps(chat_probe, indent=2))

    print("\nRESPONSES")
    print(json.dumps(resp_probe, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
