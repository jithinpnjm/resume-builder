"""Thin wrapper around the Gemini API for structured JSON generation.

Every call site is responsible for supplying its own schema/prompt; this
module only handles the client, model selection, and JSON-mode plumbing so
call sites never touch raw SDK objects.
"""
from __future__ import annotations

import json
import os
import time

import requests
from google import genai
from google.genai import types

MODEL = "gemini-3.5-flash"
MAX_NETWORK_RETRIES = 2

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set")
        _client = genai.Client(api_key=api_key)
    return _client


def generate_json(system_prompt: str, user_content: str) -> dict:
    """Call Gemini in JSON mode and return the parsed response object.

    Retries on transient local network errors (e.g. macOS ephemeral port
    exhaustion under many rapid outbound HTTPS connections), not on API
    errors — those should surface immediately.
    """
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(MAX_NETWORK_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                ),
            )
            # response_mime_type="application/json" usually yields a clean
            # single object, but Gemini occasionally appends trailing
            # content after it (e.g. a repeated/partial object) even in
            # JSON mode. json.loads rejects that outright with "Extra
            # data", so decode just the first object instead of the whole
            # string.
            text = response.text.strip()
            obj, _ = json.JSONDecoder().raw_decode(text)
            return obj
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            if attempt < MAX_NETWORK_RETRIES:
                time.sleep(1 + attempt)
    raise last_exc


def generate_grounded_text(prompt: str) -> str:
    """Search-grounded generation (Google Search tool) returning prose.

    Grounding can't be combined with JSON mode, so callers structure the
    result with a second generate_json call. Used by the Study Guide curator
    so resource links come from live search, not training-data recall.
    """
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(MAX_NETWORK_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            return response.text
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            if attempt < MAX_NETWORK_RETRIES:
                time.sleep(1 + attempt)
    raise last_exc
