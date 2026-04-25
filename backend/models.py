import re
from pydantic import BaseModel, model_validator
from typing import Any, List, Optional


# YYYY-MM-DD only — what the system prompt asks the LLM to emit.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_date_shaped(s: Any) -> bool:
    return isinstance(s, str) and bool(_DATE_RE.match(s.strip()))


def _split_csv_dates(s: Any) -> Optional[List[str]]:
    """
    If `s` is a string of comma-separated YYYY-MM-DD dates, return the parsed
    list. Otherwise return None — we never split arbitrary CSV (a title like
    "Final exam, in person" must not become a list of "dates").
    """
    if not isinstance(s, str):
        return None
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) > 1 and all(_is_date_shaped(p) for p in parts):
        return parts
    return None


class ClassMeeting(BaseModel):
    day: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None


class Assessment(BaseModel):
    title: Optional[str] = None
    weight_percent: Optional[float] = None
    date: Optional[str] = None        # single due date, format YYYY-MM-DD
    dates: Optional[List[str]] = None
    start: Optional[str] = None       # for range-based assessments
    end: Optional[str] = None
    time: Optional[str] = None        # e.g. "11:59 PM"
    confidence: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_date_fields(cls, data: Any) -> Any:
        """
        Enforce mutual exclusivity of {date}, {dates}, {start, end}.

        The system prompt asks the LLM to emit exactly one of these patterns per
        assessment, but a local 8B model violates this regularly. Rather than
        rejecting the whole object (and losing the assessment entirely), we
        coerce the most common LLM mistakes:

          - `date`  arrived as a CSV string of dates  → moved to `dates`
          - `date`  arrived as a list                 → moved to `dates`, or kept if len=1
          - `start` arrived as a CSV string of dates  → moved to `dates`, range cleared
          - `dates` containing a single element       → moved to `date`
          - `dates` empty/whitespace                  → cleared
          - multiple patterns set at once             → resolved by priority

        Priority when multiple patterns are populated:
          dates (multi)  >  date  >  range
        Rationale: a list of dates is the most specific signal the LLM can give;
        a single date is more specific than a range; range is the fallback.
        """
        if not isinstance(data, dict):
            return data

        date = data.get("date")
        dates = data.get("dates")
        start = data.get("start")
        end = data.get("end")

        # ── `date` arrived as a list ────────────────────────────────────────
        if isinstance(date, list):
            cleaned = [d for d in date if isinstance(d, str) and d.strip()]
            if len(cleaned) > 1:
                if dates is None:
                    dates = cleaned
                date = None
            elif len(cleaned) == 1:
                date = cleaned[0]
            else:
                date = None

        # ── `date` arrived as a CSV of dates ────────────────────────────────
        if isinstance(date, str):
            split = _split_csv_dates(date)
            if split:
                if dates is None:
                    dates = split
                date = None

        # ── `start` arrived as a CSV of dates (the prompt's named footgun) ──
        if isinstance(start, str):
            split = _split_csv_dates(start)
            if split:
                if dates is None:
                    dates = split
                start = None
                end = None

        # ── Normalize `dates` list ──────────────────────────────────────────
        if isinstance(dates, list):
            dates = [d.strip() for d in dates if isinstance(d, str) and d.strip()]
            if not dates:
                dates = None
            elif len(dates) == 1:
                if not date:
                    date = dates[0]
                dates = None

        # ── Resolve mutual exclusivity ──────────────────────────────────────
        has_dates = isinstance(dates, list) and len(dates) > 1
        has_date = bool(date)

        if has_dates:
            date = None
            start = None
            end = None
        elif has_date:
            start = None
            end = None
        # else: range stays as-is (or all None)

        data["date"] = date
        data["dates"] = dates
        data["start"] = start
        data["end"] = end
        return data


class ScheduleEntry(BaseModel):
    week: Optional[int] = None
    start: Optional[str] = None
    end: Optional[str] = None
    topic: Optional[str] = None


class Course(BaseModel):
    course_code: Optional[str] = None
    course_title: Optional[str] = None
    term: Optional[str] = None
    section_code: Optional[str] = None
    instructor: Optional[str] = None
    email: Optional[str] = None
    office_hours: Optional[str] = None
    class_meetings: Optional[List[ClassMeeting]] = None
    assessments: Optional[List[Assessment]] = None
    schedule: Optional[List[ScheduleEntry]] = None
    policies: Optional[List[str]] = None


class SyllabusData(BaseModel):
    courses: List[Course]