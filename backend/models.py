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
    deadline: Optional[str] = None
    confidence: Optional[float] = None
 
 
class ScheduleEntry(BaseModel):
    week: Optional[str] = None
    date: Optional[str] = None
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