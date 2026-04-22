import requests
from constants import SYSTEM_PROMPT, USER_PROMPT




def word_parser(extracted_text, context_size):
    prompt = USER_PROMPT
    prompt += extracted_text

    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen3:8b",
            "format": "json",
            "stream": False,
            "options": {
            "num_ctx": context_size
            },
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]
        }
    )

    answer = response.json()["message"]["content"]
    return answer

