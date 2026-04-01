PRIMARY_WEIGHT_KEYS = {'weight', 'percentage', 'grad', 'total'}
 
WEIGHT_KEY = {
    'assessment', 'evaluation', 'grading', 'grades', 'breakdown',
    'mark', 'scheme', 'weights', 'weighted', 'value', 'worth', 'weighting'
}
 
COURSE_WORK = [
    'lab', 'quiz', 'final exam', 'midterm', 'assignment',
    'quizzes', 'test', 'tests', 'labs', 'report', 'project', 'presentation',
    'participation', 'homework', 'webwork', 'webassign', 'wileyplus',
    'iclicker', 'clicker', 'top hat', 'tophat', 'gradescope', 'crowdmark',
    'zybooks', 'zybook', 'codio', 'github classroom', 'replit', 'möbius',
    'mobius', 'mastering', 'masteringphysics', 'masteringchemistry',
    'mylab', 'mymathlab', 'connect', 'mcgraw hill connect', 'sapling',
    'achieve', 'cengage', 'mindtap', 'expert ta', 'matlab grader',
    'perusall', 'prairielearn', 'kahoot', 'tutorial assessment', 'exam', 'tutorial'
]
 
REPEATED_SCHEDULE_WORDS = [
    'week', 'weeks', 'topic', 'topics', 'chapter', 'chapters',
    'reading', 'readings', 'module', 'modules', 'unit', 'units',
    'lecture', 'lectures', 'lesson', 'lessons', 'ch.'
]
 
ONCE_SCHEDULE_WORDS = [
    'course schedule', 'class schedule', 'weekly schedule',
    'lecture schedule', 'schedule of topics', 'course outline',
    'weekly outline', 'tentative schedule', 'calendar of topics',
    'unit of study'
]
 
MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)"
DAY = r"(?:[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
DAY_RANGE = rf"{DAY}(?:\s*(?:-|–|to)\s*{DAY})?"
YEAR = r"(?:,?\s*\d{4})?"
DATE_PATTERN = rf"(?:\b{MONTHS}\.?\s+{DAY_RANGE}{YEAR}\b|\b{MONTHS}\.?,\s*{DAY_RANGE}{YEAR}\b|\b{DAY_RANGE},?\s+{MONTHS}\.?{YEAR}\b)"


TIME_PATTERN = r'\b\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)\b|\b\d{1,2}\s*(?:am|pm|AM|PM)\b'

TIME_PATTERN = r'\b(?:' \
               r'(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s?(?:[AaPp]\.?[Mm]\.?)' \
               r'|' \
               r'(?:[01]?\d|2[0-3]):[0-5]\d' \
               r'|' \
               r'noon|midnight' \
               r')\b'

CONTEXT_SIZES = {
    "fast": 8192,
    "balanced": 16384,
    "full": 32768
}
 
MIN_BLOCK_LINES = 2