import re
from block import _ENCODING
from constants import (COURSE_WORK, ONCE_SCHEDULE_WORDS, REPEATED_SCHEDULE_WORDS, WEIGHT_KEY, PRIMARY_WEIGHT_KEYS, TIME_PATTERN,
                        DATE_PATTERN, CONTACT_WORDS, INSTRUCTOR_WORDS, MEETING_WORDS, EMAIL_PATTERN, OFFICE_HOURS, LOCATION_WORDS,
                          CONTEXT_SIZES, SYSTEM_PROMPT, USER_PROMPT
        )

def set_importance_score(block):
    text = block.text.lower()
    score = 0
    coursework_count = 0
    schedule_word_count = 0
    primary_weight_count = 0
    contact_word_count = 0
    instructor_count = 0
    meeting_word_count = 0
    office_hours_count = 0
    location_count = 0

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

    for word in PRIMARY_WEIGHT_KEYS:
        pattern = r"\b" + re.escape(word) + r"\b"
        matches = re.findall(pattern, text)
        primary_weight_count += len(matches)

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

    for word in INSTRUCTOR_WORDS:
        pattern = r"\b" + re.escape(word) + r"\b"
        matches = re.findall(pattern, text)
        instructor_count += len(matches)

    for word in CONTACT_WORDS:
        pattern = r"\b" + re.escape(word) + r"\b"
        matches = re.findall(pattern, text)
        contact_word_count += len(matches)

    for word in MEETING_WORDS:
        pattern = r"\b" + re.escape(word) + r"\b"
        matches = re.findall(pattern, text)
        meeting_word_count += len(matches)

    for phrase in OFFICE_HOURS:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        matches = re.findall(pattern, text)
        office_hours_count += len(matches)

    for word in LOCATION_WORDS:
        pattern = r"\b" + re.escape(word) + r"\b"
        matches = re.findall(pattern, text)
        location_count += len(matches)

    email_count = len(re.findall(EMAIL_PATTERN, text))

    word_count = len(text.split())

    score += min(location_count, 3) * 4
    score += percent_count * 3
    score += min(coursework_count, 3) * 2
    score += date_count * 3
    score += min(schedule_word_count, 3)
    score += time_count * 3
    score += min(primary_weight_count, 4) * 2
    score += min(instructor_count, 3) * 2
    score += min(contact_word_count, 3) * 2
    score += min(meeting_word_count, 4) * 2
    score += min(email_count, 2) * 4
    score += min(office_hours_count, 2) * 4

    if has_grading_word:
        score += 2

    if has_schedule_heading:
        score += 6

    if percent_count > 0 and coursework_count > 0:
        score += 6

    if date_count > 0 and coursework_count > 0:
        score += 4

    if date_count > 0 and schedule_word_count > 0:
        score += 5

    if has_grading_word and percent_count > 0:
        score += 4

    if time_count > 0 and schedule_word_count > 0:
        score += 3

    if word_count > 180 and score < 12:
        score = max(score - 2, 0)
    elif word_count < 60 and score >= 6:
        score += 1

    if primary_weight_count > 0 and percent_count > 0:
        score += 5

    if primary_weight_count > 0 and coursework_count > 0:
        score += 4

    if primary_weight_count > 0 and has_grading_word:
        score += 3

    if contact_word_count > 0 and email_count > 0:
        score += 4

    if instructor_count > 0 and email_count > 0:
        score += 6

    if instructor_count > 0 and contact_word_count > 0:
        score += 4

    if meeting_word_count > 0 and time_count > 0:
        score += 6

    if meeting_word_count > 0 and date_count > 0:
        score += 2

    if office_hours_count > 0 and time_count > 0:
        score += 6

    if office_hours_count > 0 and instructor_count > 0:
        score += 4

    if office_hours_count > 0 and email_count > 0:
        score += 3

    if location_count > 0 and time_count > 0:
        score += 5

    if location_count > 0 and meeting_word_count > 0:
        score += 4

    block.importance_score = score


def score_and_size_blocks(blocks):
    if not blocks:
        return
    
    for block in blocks:
        set_importance_score(block)
        block.set_context_size()


def prune_blocks_to_context_limit(blocks, context_limit):
    if not blocks:
        return []

    total_tokens = sum(block.context_size for block in blocks)
    total_tokens += len(_ENCODING.encode(SYSTEM_PROMPT))
    total_tokens += len(_ENCODING.encode(USER_PROMPT))

    if total_tokens <= context_limit:
        return blocks[:]

    hard_keep_threshold = 18
    removable_blocks = [b for b in blocks if b.importance_score < hard_keep_threshold]

    blocks_sorted_for_removal = sorted(
        removable_blocks,
        key=lambda b: b.context_size / max((b.importance_score + 1) ** 1.2, 1e-9),
        reverse=True
    )

    kept_blocks = blocks[:]

    for block in blocks_sorted_for_removal:
        if total_tokens <= context_limit:
            break

        kept_blocks.remove(block)
        total_tokens -= block.context_size

    return kept_blocks