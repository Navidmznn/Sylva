import re
import httpx

from constants import (
    SYSTEM_PROMPT,
    USER_PROMPT,
    USER_PROMPT_SUFFIX,
    OLLAMA_MODEL,
    OLLAMA_URL,
    OLLAMA_TIMEOUT,
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


async def word_parser(extracted_text: str, context_size: int) -> str:
    prompt = build_syllabus_prompt(extracted_text)

    # don't let a stuck model hang forever
    timeout = httpx.Timeout(
        timeout=float(OLLAMA_TIMEOUT),
        connect=10.0,
        read=float(OLLAMA_TIMEOUT),
        write=30.0,
        pool=10.0,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "format": "json",
                "stream": False,
                "options": {
                    "num_ctx": context_size,
                    "temperature": 0,
                },
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
            },
        )
        response.raise_for_status()

        payload = response.json()

        try:
            raw = payload["message"]["content"]
        except KeyError:
            raise ValueError("Ollama response did not contain message.content")

        return strip_code_fences(raw)