import os
import re

import httpx

from constants import (
    SYSTEM_PROMPT,
    USER_PROMPT,
    USER_PROMPT_SUFFIX,
    GEMINI_API_URL,
    GEMINI_MODEL,
    GEMINI_TIMEOUT,
)


_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.IGNORECASE | re.DOTALL
)


def neutralize_prompt_delimiters(text: str) -> str:
    """Strip wrapper tags so PDF content can't escape the trust boundary."""
    return (
        text
        .replace("<untrusted_syllabus_text>",  "[removed opening delimiter]")
        .replace("</untrusted_syllabus_text>", "[removed closing delimiter]")
    )


def strip_code_fences(raw: str) -> str:
    """Strip ```json fences if the model wrapped its output."""
    raw = raw.strip()
    match = _CODE_FENCE_RE.match(raw)
    if match:
        return match.group(1).strip()
    return raw


def build_syllabus_prompt(extracted_text: str) -> str:
    safe_text = neutralize_prompt_delimiters(extracted_text)
    return USER_PROMPT + safe_text + USER_PROMPT_SUFFIX


async def word_parser(extracted_text: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    prompt = build_syllabus_prompt(extracted_text)

    async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
        response = await client.post(
            f"{GEMINI_API_URL}/models/{GEMINI_MODEL}:generateContent",
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "systemInstruction": {
                    "parts": [{"text": SYSTEM_PROMPT}],
                },
                "contents": [
                    {"role": "user", "parts": [{"text": prompt}]},
                ],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                },
            },
        )
        response.raise_for_status()

        payload = response.json()
        try:
            raw = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ValueError("Gemini response missing candidates/content/parts")

        return strip_code_fences(raw)
