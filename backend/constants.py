PRIMARY_WEIGHT_KEYS = {'weight', 'percentage', 'grade', 'total'}

WEIGHT_KEY = {
    'assessment', 'evaluation', 'grading', 'grades', 'breakdown',
    'mark', 'scheme', 'weights', 'weighted', 'value', 'worth', 'weighting'
}

CONTACT_WORDS = {
    'contact', 'email', 'e-mail', 'phone', 'telephone', 'office hours'
}

INSTRUCTOR_WORDS = {
    'instructor', 'professor', 'prof', 'lecturer', 'teaching assistant',
    'ta', 'course director', 'lab coordinator', 'instructional team',
    'teaching team', 'dr', 'mr', 'ms', 'mrs', 'ia', 'instruction assistant',
    'course coordinator', 'course instructor', 'course lecturer', 'doctor'
}

MEETING_WORDS = {
    'class meeting', 'meeting days', 'meeting time', 'lecture', 'lectures',
    'tutorial', 'tutorials', 'lab', 'labs', 'seminar', 'discussion',
    'office hours'
}

COURSE_WORK = {
    'lab', 'quiz', 'final exam', 'midterm', 'assignment',
    'quizzes', 'test', 'tests', 'labs', 'report', 'project', 'presentation',
    'participation', 'homework', 'webwork', 'webassign', 'wileyplus',
    'iclicker', 'clicker', 'top hat', 'tophat', 'gradescope', 'crowdmark',
    'zybooks', 'zybook', 'codio', 'github classroom', 'replit', 'möbius',
    'mobius', 'mastering', 'masteringphysics', 'masteringchemistry',
    'mylab', 'mymathlab', 'connect', 'mcgraw hill connect', 'sapling',
    'achieve', 'cengage', 'mindtap', 'expert ta', 'matlab grader',
    'perusall', 'prairielearn', 'kahoot', 'tutorial assessment', 'exam', 'tutorial'
}

REPEATED_SCHEDULE_WORDS = {
    'week', 'weeks', 'topic', 'topics', 'chapter', 'chapters',
    'reading', 'readings', 'module', 'modules', 'unit', 'units',
    'lecture', 'lectures', 'lesson', 'lessons', 'ch.'
}

ONCE_SCHEDULE_WORDS = {
    'course schedule', 'class schedule', 'weekly schedule',
    'lecture schedule', 'schedule of topics', 'course outline',
    'weekly outline', 'tentative schedule', 'calendar of topics',
    'unit of study'
}

OFFICE_HOURS = {
    'office hours', 'contact hours', 'consultation hours', 'help sessions', 'office hour'
}

LOCATION_WORDS = {
    'room', 'rm', 'rm.', 'building', 'bldg', 'bldg.', 'hall',
    'campus', 'classroom', 'lecture hall', 'lab room'
}

MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)"
DAY = r"(?:[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
DAY_RANGE = rf"{DAY}(?:\s*(?:-|–|to)\s*{DAY})?"
YEAR = r"(?:,?\s*\d{4})?"
DATE_PATTERN = rf"(?:\b{MONTHS}\.?\s+{DAY_RANGE}{YEAR}\b|\b{MONTHS}\.?,\s*{DAY_RANGE}{YEAR}\b|\b{DAY_RANGE},?\s+{MONTHS}\.?{YEAR}\b)"

TIME_PATTERN = r'\b(?:' \
               r'(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s?(?:[AaPp]\.?[Mm]\.?)' \
               r'|' \
               r'(?:[01]?\d|2[0-3]):[0-5]\d' \
               r'|' \
               r'noon|midnight' \
               r')\b'

EMAIL_PATTERN = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"

WEEKDAY_PATTERN = r"""
(?ix)
(?<!\w)
(?:

    (?:mwf|mtwrf|tr|tth)
    |

    (?:
        monday|mon\.?|
        tuesday|tues?\.?|
        wednesday|wed\.?|
        thursday|thurs?\.?|thur\.?|thu\.?|
        friday|fri\.?|
        saturday|sat\.?|
        sunday|sun\.?|
        m|t|tu|w|th|r|f|sa|su|u
    )
    (?:\s*(?:/|,|&|and|-)\s*
        (?:
            monday|mon\.?|
            tuesday|tues?\.?|
            wednesday|wed\.?|
            thursday|thurs?\.?|thur\.?|thu\.?|
            friday|fri\.?|
            saturday|sat\.?|
            sunday|sun\.?|
            m|t|tu|w|th|r|f|sa|su|u
        )
    )+
    |
    # single day styles
    (?:
        monday|mon\.?|
        tuesday|tues?\.?|
        wednesday|wed\.?|
        thursday|thurs?\.?|thur\.?|thu\.?|
        friday|fri\.?|
        saturday|sat\.?|
        sunday|sun\.?|
        m|t|tu|w|th|r|f|sa|su|u
    )
)
(?!\w)
"""

LOCATION_PATTERN = r"""
(?ix)
(?:
    # explicit room labels
    \b(?:room|rm\.?|bldg\.?|building|hall)\s*[a-z]?\d{1,4}[a-z]?\b
    |

    \b[a-z]{2,6}\s*-?\s*\d{2,5}[a-z]?\b
)
"""

CONTEXT_SIZES = {
    "fast": 8192,
    "balanced": 16384,
    "full": 32768
}

MIN_BLOCK_LINES = 2

OLLAMA_TIMEOUT = 300
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434"

SYSTEM_PROMPT = """
You are a university syllabus parser. Your job is to extract structured information from syllabus text and return it as valid JSON.

Rules:
- Return ONLY valid JSON, nothing else. No explanation, no markdown, no code fences.
- Only extract information that appears in the syllabus text.
- Do not copy placeholder values from the schema.
- Do not invent course codes, titles, assignments, dates, or weights.
- If a value is unclear or missing, use null.
- Never return {}.
- If nothing is found, return:
{"courses":[]}
- Each section of a course gets its own entry in the courses array, even if the course code is the same.
- If a field is not found in the text, set it to null.
- Assessments and policies are shared across sections — duplicate them for each section entry.
- Be as accurate as possible. If you are unsure about a value, still include it but set confidence low.
- For assessment dates, follow these rules exactly:
- Use "date" when there is a single specific due date (e.g. an essay, a midterm on one day)
- Use "dates" when there are multiple separate dates (e.g. tutorials on Jan 15, Jan 29, Feb 12)
- Use "start" and "end" when there is a window or range (e.g. final exam period Apr 9-24)
- Never put multiple dates in the "start" field as a comma-separated string
- Never use "dates" for a range — that is what "start" and "end" are for
- Only one of these patterns should be used per assessment, leave the others as null

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
          "title": "Essay",
          "weight_percent": 20,
          "date": "2026-10-14",
          "dates": null,
          "start": null,
          "end": null,
          "time": "11:59 PM",
          "confidence": 0.95
        },
        {
          "title": "Tutorial assessments",
          "weight_percent": 30,
          "date": null,
          "dates": ["2026-01-15", "2026-01-29", "2026-02-12"],
          "start": null,
          "end": null,
          "time": null,
          "confidence": 0.85
        }
      ],
      "schedule": [
        {
          "week": 1,
          "start": "2026-09-08",
          "end": "2026-09-14",
          "topic": "Introduction to cells"
        }
      ],
      "policies": ["No late submissions accepted"]
    }
  ]
}
"""

USER_PROMPT = "Extract all course information from this syllabus text:\n\n"