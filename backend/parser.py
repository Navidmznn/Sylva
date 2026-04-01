import requests
import json
from extractor import doc_recognizer

system_prompt = """
You are a university syllabus parser. Your job is to extract structured information from syllabus text and return it as valid JSON.

Rules:
- Return ONLY valid JSON, nothing else. No explanation, no markdown, no code fences.
- Never return {}.
- If nothing is found, return:
{"courses":[]}
- Each section of a course gets its own entry in the courses array, even if the course code is the same.
- If a field is not found in the text, set it to null.
- Assessments and policies are shared across sections — duplicate them for each section entry.
- Be as accurate as possible. If you are unsure about a value, still include it but set confidence low.

Return JSON in exactly this format:
{
  "courses": [
    {
      "course_code": "BIOL1000",
      "course_title": "Introductory Biology",
      "term": "Fall 2026",
      "section_code": "01",
      "instructor": "Prof. Smith",
      "email": "smith@school.ca",
      "office_hours": "Monday 2-4pm",
      "class_meetings": [
        {
          "day": "Monday",
          "start_time": "10:30",
          "end_time": "11:20",
          "location": "Room A",
          "type": "lecture"
        }
      ],
      "assessments": [
        {
          "title": "Midterm",
          "weight_percent": 25,
          "deadline": "October 14",
          "confidence": 0.95
        }
      ],
      "schedule": [
        {
          "week": 1,
          "topic": "Introduction to cells"
        }
      ],
      "policies": ["No late submissions accepted"]
    }
  ]
}
"""



def word_parser(extracted_text):
    prompt = "Extract all course information from this syllabus text:\n\n"
    prompt += extracted_text

    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "qwen3:8b",
            "format": "json",
            "stream": False,
            "options": {
            "num_ctx": 8192
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
        }
    )

    print("RAW RESPONSE JSON:")
    print(response.json())

    answer = response.json()["message"]["content"]
    print("MODEL ANSWER:")
    print(answer)
    return answer

