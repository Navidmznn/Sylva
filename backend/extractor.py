import base64
import os

import httpx

from block import Block
from constants import MISTRAL_API_URL, MISTRAL_OCR_MODEL, MISTRAL_TIMEOUT


def extract_document(file_path):
    """Send a PDF to Mistral OCR and return its markdown as a single Block."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set")

    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    response = httpx.post(
        f"{MISTRAL_API_URL}/ocr",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MISTRAL_OCR_MODEL,
            "document": {
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64}",
            },
        },
        timeout=MISTRAL_TIMEOUT,
    )
    response.raise_for_status()

    pages = response.json().get("pages", [])
    markdown = "\n\n".join(p.get("markdown", "") for p in pages).strip()

    if not markdown:
        return []
    return [Block(markdown, is_table=False)]
