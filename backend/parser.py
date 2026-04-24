import httpx
from constants import SYSTEM_PROMPT, USER_PROMPT, OLLAMA_MODEL, OLLAMA_URL


async def word_parser(extracted_text: str, context_size: int) -> str:
    prompt = USER_PROMPT + extracted_text

    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "format": "json",
                "stream": False,
                "options": {"num_ctx": context_size},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ]
            }
        )
        response.raise_for_status()
        raw = response.json()["message"]["content"]
        # Strip markdown code fences if the model added them
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[-1]  # remove opening fence
            raw = raw.rsplit("```", 1)[0]  # remove closing fence
            raw = raw.strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        return raw