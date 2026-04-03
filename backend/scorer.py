import re
from constants import COURSE_WORK, ONCE_SCHEDULE_WORDS, REPEATED_SCHEDULE_WORDS, WEIGHT_KEY, PRIMARY_WEIGHT_KEYS, TIME_PATTERN, DATE_PATTERN

def get_importance_score(block):
    text = block.text.lower()
    score = 0
    coursework_count = 0
    schedule_word_count = 0
    has_grading_word = False
    has_schedule_heading = False

    percent_count = text.count("%")

    for word in COURSE_WORK:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, text):
            coursework_count += 1

    date_count = len(re.findall(DATE_PATTERN, text))

    for word in REPEATED_SCHEDULE_WORDS:
        pattern = r"\b" + re.escape(word) + r"\b"
        matches = re.findall(pattern, text)
        schedule_word_count += len(matches)

    time_count = len(re.findall(TIME_PATTERN, text))


    for word in WEIGHT_KEY:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, text):
            has_grading_word = True
            break


    for phrase in ONCE_SCHEDULE_WORDS:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        if re.search(pattern, text):
            has_schedule_heading = True
            break

    word_count = len(text.split())