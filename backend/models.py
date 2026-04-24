from pydantic import BaseModel
from typing import List, Optional
 
 
class ClassMeeting(BaseModel):
    day: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None
 
 
class Assessment(BaseModel):
    title: Optional[str] = None
    weight_percent: Optional[float] = None
    date: Optional[str] = None       # single due date, format YYYY-MM-DD
    dates: Optional[List[str]] = None  
    start: Optional[str] = None      # for range-based assessments
    end: Optional[str] = None
    time: Optional[str] = None       # e.g. "11:59 PM"
    confidence: Optional[float] = None


class ScheduleEntry(BaseModel):
    week: Optional[int] = None       # int, not str
    start: Optional[str] = None      # week start date YYYY-MM-DD
    end: Optional[str] = None        # week end date YYYY-MM-DD
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