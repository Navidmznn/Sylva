const allCourses = [];
let calendarInstance = null;

// ── Per-course color generation (golden-angle HSL, infinite) ─────────────────
function getCourseColors(index) {
  const hue = Math.round((index * 137.508) % 360);
  return {
    assessment: `hsl(${hue}, 62%, 46%)`,
    week:       `hsl(${hue}, 38%, 62%)`
  };
}

// ── Filter state ─────────────────────────────────────────────────────────────
const filterState = {
  types:   new Set(['assessment', 'week']),
  courses: new Set()   // holds numeric course indices
};

function applyFilters() {
  if (!calendarInstance) return;
  calendarInstance.getEvents().forEach(e => {
    const typeOk   = filterState.types.has(e.extendedProps.type);
    const courseOk = filterState.courses.has(e.extendedProps.courseIndex);
    e.setProp('display', typeOk && courseOk ? 'auto' : 'none');
  });
}

// ── Event builder (single source of truth for both init + refresh) ────────────
function buildCourseEvents(course, courseIdx) {
  const colors = getCourseColors(courseIdx);
  return [
    ...(course.assessments || [])
      .filter(a => a.date || a.start)
      .map(a => ({
        title: a.title,
        ...(a.date ? { date: a.date } : { start: a.start, end: a.end }),
        backgroundColor: colors.assessment,
        borderColor:     colors.assessment,
        extendedProps: {
          type: 'assessment',
          description: `Worth ${a.weight_percent}%`,
          time: a.time || null,
          courseIndex: courseIdx
        }
      })),
    ...(course.schedule || []).map(s => ({
      title: `Week ${s.week}: ${s.topic}`,
      start: s.start,
      end:   s.end,
      backgroundColor: colors.week,
      borderColor:     colors.week,
      extendedProps: { type: 'week', description: s.topic, courseIndex: courseIdx }
    }))
  ];
}

// ── Course filter pill builder ────────────────────────────────────────────────
function rebuildCourseFilters() {
  const group     = document.getElementById('course-filter-group');
  const container = document.getElementById('course-filter-pills');
  if (!group || !container) {
    console.warn('[rebuildCourseFilters] filter DOM elements not found — is the page stale? Hard-refresh required.');
    return;
  }
  container.innerHTML = '';

  allCourses.forEach((course, i) => {
    filterState.courses.add(i);
    const colors = getCourseColors(i);
    const label  = course.course_code || course.course_title || `Course ${i + 1}`;

    const btn = document.createElement('button');
    btn.className = 'filter-pill course-pill active';
    btn.dataset.courseIndex = i;
    btn.innerHTML = `<span class="pill-dot" style="background:${colors.assessment}"></span>${label}`;

    btn.addEventListener('click', () => {
      if (filterState.courses.has(i)) {
        filterState.courses.delete(i);
        btn.classList.remove('active');
      } else {
        filterState.courses.add(i);
        btn.classList.add('active');
      }
      applyFilters();
    });

    container.appendChild(btn);
  });

  group.style.display = allCourses.length > 1 ? 'flex' : 'none';
}

document.querySelector('.drop-button').addEventListener('click', () => {
  document.querySelector('input[type="file"]').click();
});

const input = document.querySelector('input[type="file"]');

input.addEventListener('change', async () => {
  const file = input.files[0];
  if (!file) return;

  if (file.size > 20 * 1024 * 1024) {
    alert('File too large. Please upload a PDF under 20MB.');
    input.value = '';
    return;
  }

  const button = document.querySelector('.drop-button');
  button.textContent = 'Uploading...';
  button.disabled = true;
  const modal = document.getElementById('loading-modal');
  modal.style.display = 'flex';

  try {
    console.log('[1] Starting upload');
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('http://localhost:8000/upload', {
      method: 'POST',
      body: formData
    });
    console.log('[2] Fetch status:', response.status);

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || 'Upload failed');
    }

    let result;
    try {
      result = await response.json();
    } catch(e) {
      throw new Error('Failed to parse JSON response: ' + e.message);
    }
    console.log('[3] Full result:', JSON.stringify(result, null, 2));

    if (!result.data) {
      throw new Error('Response missing "data" field. Got: ' + JSON.stringify(result));
    }
    const courses = result.data.courses;
    console.log('[4] Courses:', courses);
    console.log('[5] Courses count:', courses ? courses.length : 'null/undefined');

    if (!courses || courses.length === 0) {
      alert('No course data extracted. Check browser console (F12) for the full API response.');
      return;
    }

    courses.forEach(course => allCourses.push(course));
    updateDropdown();
    rebuildCourseFilters();

    console.log('[6] Calling renderChart, index:', allCourses.length - 1);
    try {
      renderChart(allCourses.length - 1);
      renderAssessmentList();
      renderGradeCalc();
      console.log('[7] renderChart OK');
    } catch(e) {
      console.error('[7] renderChart CRASHED:', e);
      alert('renderChart error: ' + e.message + '\n\nCheck browser console (F12).');
    }

    if (!calendarInstance) {
      document.getElementById('calendar-section').style.display = 'flex';
      try {
        initCalendar();
        console.log('[8] initCalendar OK');
      } catch(e) {
        console.error('[8] initCalendar CRASHED:', e);
      }
    } else {
      refreshCalendarEvents();
    }

  } catch (err) {
    console.error('[ERROR]', err);
    alert('Error: ' + err.message);
  } finally {
    modal.style.display = 'none';
    button.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
        <polyline points="17 8 12 3 7 8"/>
        <line x1="12" y1="3" x2="12" y2="15"/>
      </svg>
      Upload Syllabus`;
    button.disabled = false;
    input.value = '';
  }
});


function refreshCalendarEvents() {
  calendarInstance.getEvents().forEach(e => e.remove());
  allCourses.forEach((course, i) => {
    buildCourseEvents(course, i).forEach(event => calendarInstance.addEvent(event));
  });
  applyFilters();
}


function renderChart(index) {
  console.log('[renderChart] index:', index, 'course:', allCourses[index]);
  const course = allCourses[index];
  if (!course) { console.error('[renderChart] course is undefined!'); return; }
  
  document.getElementById('results').style.display = 'block';

  const assessments = course.assessments || [];
  console.log('[renderChart] assessments:', assessments);

  const colors = ['#5C4033', '#C9A46A', '#D98C8C', '#A3B18A', '#7C8A5B', '#3D4C63', '#FFF8F0', '#C9A46A'];
  const legend = document.getElementById('legend');

  legend.classList.remove('animate');
  void legend.offsetWidth;

  legend.innerHTML = `
  <div class="course-title">${course.course_title}</div>
    ${assessments.map((a, i) => `
      <div class="legend-item">
        <span class="dot" style="background:${colors[i]}"></span>
        <span class="legend-label">${a.title}</span>
        <span class="legend-weight">${a.weight_percent}%</span>
      </div>
    `).join('')}
  `;
  legend.classList.add('animate');

  if (window.pieChart) window.pieChart.destroy();
  window.pieChart = new Chart(document.getElementById('pie-chart'), {
    type: 'pie',
    data: {
      labels: assessments.map(a => a.title),
      datasets: [{
        data: assessments.map(a => a.weight_percent),
        backgroundColor: colors,
        borderWidth: 0
      }]
    },
    options: {
      animation: {
        duration: 800,
        easing: 'easeOutQuart',
        animateScale: true,
        animateRotate: false
      },
      responsive: false,
      maintainAspectRatio: false,
      plugins: {
        legend: {display: false},
        tooltip: {
          callbacks: {
            label: (item) => `${item.parsed}%`
          }
        }
      }
    }
  });

}

// ── Assessment list (always shown, past/future sorted, with calendar buttons) ─

function getAssessmentDate(a) {
  const raw = a.date || a.start || (a.dates && a.dates[0]) || null;
  return raw ? new Date(raw) : null;
}

function formatDisplayDate(a) {
  const raw = a.date || a.start || (a.dates && a.dates[0]) || null;
  if (!raw) return 'No date';
  const d = new Date(raw);
  return d.toLocaleDateString('en-CA', { year: 'numeric', month: 'short', day: 'numeric' });
}

// Module-level ref so the toggle always calls the latest render, regardless of which
// course was active when the listener was first attached.
let _buildAssessmentRows = null;

function renderAssessmentList() {
  const section = document.getElementById('assessment-section');
  const listEl  = document.querySelector('.assessment-list');
  const toggle  = document.getElementById('hide-past-toggle');

  // Aggregate ALL assessments across every uploaded course, tagged with course info
  const assessments = allCourses.flatMap((course, courseIdx) =>
    (course.assessments || []).map(a => ({
      ...a,
      _courseLabel: course.course_code || course.course_title || `Course ${courseIdx + 1}`,
      _courseIdx: courseIdx
    }))
  ).sort((a, b) => {
    const da = getAssessmentDate(a);
    const db = getAssessmentDate(b);
    if (!da && !db) return 0;
    if (!da) return 1;
    if (!db) return -1;
    return da - db;
  });

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  section.style.display = 'block';

  // Reassign the module-level ref — the toggle listener always calls this latest closure
  _buildAssessmentRows = function buildRows() {
    const hidePast = toggle.checked;
    listEl.innerHTML = assessments.map((a, i) => {
      const d    = getAssessmentDate(a);
      const past = d && d < today;
      if (past && hidePast) return '';           // omit entirely — no hidden DOM nodes
      const pastClass = past ? 'is-past' : '';
      const weight    = a.weight_percent != null ? `${a.weight_percent}%` : '';
      const colors    = getCourseColors(a._courseIdx);

      return `
        <div class="assessment-row ${pastClass}" data-index="${i}">
          <div class="past-badge">Past</div>
          <div class="assessment-title">${a.title || 'Untitled'}</div>
          <div class="assessment-meta">
            <span class="assessment-date">${formatDisplayDate(a)}</span>
            ${weight ? `<span class="assessment-weight">${weight}</span>` : ''}
            ${allCourses.length > 1
              ? `<span class="assessment-course-tag" style="background:${colors.assessment}22;border-color:${colors.assessment};color:${colors.assessment}">${a._courseLabel}</span>`
              : ''}
          </div>
          <div class="cal-buttons">
            ${calBtn('google', a)}
            ${calBtn('outlook', a)}
            ${calBtn('apple', a)}
            ${calBtn('yahoo', a)}
          </div>
        </div>
      `;
    }).join('');

    // Wire calendar buttons — read data-index off the rendered rows
    document.querySelectorAll('.assessment-row[data-index]').forEach(row => {
      const a = assessments[parseInt(row.dataset.index)];
      row.querySelector('.cal-btn[data-provider="google"]')
        ?.addEventListener('click', () => addToGoogleCalendar(a));
      ['outlook','apple','yahoo'].forEach(p => {
        row.querySelector(`.cal-btn[data-provider="${p}"]`)
          ?.addEventListener('click', () => addToCalendar(p, a));
      });
    });
  };

  _buildAssessmentRows();

  // Attach once — always delegates to _buildAssessmentRows so it's always current
  if (!toggle.dataset.listenerAttached) {
    toggle.dataset.listenerAttached = 'true';
    toggle.addEventListener('change', () => _buildAssessmentRows());
  }
}

function calBtn(provider, assessment) {
  const icons = {
    google:  `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M21.35 11.1h-9.17v2.73h6.51c-.33 3.81-3.5 5.44-6.5 5.44C8.36 19.27 5 16.25 5 12c0-4.1 3.2-7.27 7.2-7.27 3.09 0 4.9 1.97 4.9 1.97L19 4.72S16.56 2 12.1 2C6.42 2 2.03 6.8 2.03 12c0 5.05 4.13 10 10.22 10 5.33 0 9.98-3.64 9.98-9.58 0-.56-.04-1.23-.18-1.32z"/></svg>Google`,
    outlook: `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M7 6h10a2 2 0 012 2v8a2 2 0 01-2 2H7a2 2 0 01-2-2V8a2 2 0 012-2zm0 2v1.5l5 3 5-3V8H7zm0 3.5V16h10v-4.5l-5 3-5-3z"/></svg>Outlook`,
    apple:   `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/></svg>Apple`,
    yahoo:   `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M20 4l-8 7.5L4 4H2l10 9.5V22h4v-8.5L22 4z"/></svg>Yahoo`,
  };
  return `<button class="cal-btn" data-provider="${provider}">${icons[provider]}</button>`;
}

// ── Calendar integrations ─────────────────────────────────────────────────────

function buildEventDates(assessment) {
  if (assessment.date) return { start: assessment.date, end: assessment.date, allDay: true };
  if (assessment.start) return { start: assessment.start, end: assessment.end || assessment.start, allDay: true };
  if (assessment.dates && assessment.dates.length) return { start: assessment.dates[0], end: assessment.dates[assessment.dates.length-1], allDay: true };
  return { start: null, end: null, allDay: true };
}

function toISOBasic(dateStr) {
  return dateStr ? dateStr.replace(/-/g, '') : null;
}

function addToCalendar(provider, assessment) {
  const { start, end } = buildEventDates(assessment);
  const title = encodeURIComponent(assessment.title || 'Assessment');
  const details = encodeURIComponent(`Worth ${assessment.weight_percent || '?'}%`);
  const startB = toISOBasic(start);
  const endB   = toISOBasic(end);

  let url = null;

  if (provider === 'outlook') {
    // Outlook web — works without auth for personal; deep link opens compose
    url = `https://outlook.live.com/calendar/0/deeplink/compose?subject=${title}&body=${details}&startdt=${start || ''}&enddt=${end || ''}&allday=true&path=%2Fcalendar%2Faction%2Fcompose`;
  } else if (provider === 'apple') {
    // Apple Calendar via .ics download (works everywhere — iOS, macOS)
    const ics = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//syllabus.ai//EN',
      'BEGIN:VEVENT',
      `SUMMARY:${assessment.title || 'Assessment'}`,
      `DESCRIPTION:Worth ${assessment.weight_percent || '?'}%`,
      `DTSTART;VALUE=DATE:${startB || '19700101'}`,
      `DTEND;VALUE=DATE:${startB || '19700101'}`,
      'END:VEVENT', 'END:VCALENDAR'
    ].join('\r\n');
    const blob = new Blob([ics], { type: 'text/calendar' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${assessment.title || 'assessment'}.ics`;
    link.click();
    URL.revokeObjectURL(link.href);
    return;
  } else if (provider === 'yahoo') {
    url = `https://calendar.yahoo.com/?v=60&title=${title}&desc=${details}&st=${startB || ''}&et=${endB || ''}&dur=allday`;
  }

  if (url) window.open(url, '_blank', 'noopener');
}


function initCalendar() {
  calendarInstance = new FullCalendar.Calendar(document.getElementById('calendar'), {
    initialView: 'dayGridMonth',
    height: 'auto',
    events: allCourses.flatMap((course, i) => buildCourseEvents(course, i)),
    eventClick: function(info) {
      const e = info.event;
      const start = e.startStr;
      const end = e.endStr;
      const dateText = end && end !== start ? `${start} → ${end}` : start;

      document.getElementById('modal-type').textContent = e.extendedProps.type;
      document.getElementById('modal-title').textContent = e.title;
      document.getElementById('modal-date').textContent = dateText;
      document.getElementById('modal-description').textContent = e.extendedProps.time
        ? `${e.extendedProps.description} · Due at ${e.extendedProps.time}`
        : e.extendedProps.description;  
      document.getElementById('event-modal').style.display = 'block';
    }
  });
  calendarInstance.render();
}

document.querySelectorAll('.type-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    const type = btn.dataset.value;
    if (filterState.types.has(type)) {
      filterState.types.delete(type);
      btn.classList.remove('active');
    } else {
      filterState.types.add(type);
      btn.classList.add('active');
    }
    applyFilters();
  });
});

document.getElementById('drop-menu').addEventListener('change', (e) => {
  renderChart(parseInt(e.target.value));
});

document.getElementById('modal-close').addEventListener('click', () => {
  document.getElementById('event-modal').style.display = 'none';
});

document.getElementById('modal-overlay').addEventListener('click', () => {
  document.getElementById('event-modal').style.display = 'none';
});


function updateDropdown() {
  const dropdown = document.getElementById('drop-menu');

  if (allCourses.length <= 1) {
    dropdown.style.display = 'none';
    return;
  }

  dropdown.style.display = 'block';
  dropdown.innerHTML = '';

  allCourses.forEach((course, i) => {
    const option = document.createElement('option');
    option.value = i;
    option.textContent = course.course_code + ' – ' + course.course_title;
    dropdown.appendChild(option);
  });

  // Always land on the newest upload (chart render is handled by the caller)
  dropdown.value = allCourses.length - 1;
}


const CLIENT_ID = "527779540782-69q8f06ust49om49b9g36cknv1pes405.apps.googleusercontent.com";
const SCOPES = 'https://www.googleapis.com/auth/calendar.events';

function addToGoogleCalendar(assessment) {
  const { start, end, allDay } = buildEventDates(assessment);

  google.accounts.oauth2.initTokenClient({
    client_id: CLIENT_ID,
    scope: SCOPES,
    callback: (tokenResponse) => {
      const event = {
        summary: assessment.title,
        description: `Worth ${assessment.weight_percent}%`,
        ...(allDay
          ? { start: { date: start || '' }, end: { date: end || start || '' } }
          : { start: { dateTime: start }, end: { dateTime: end } }
        )
      };

      fetch('https://www.googleapis.com/calendar/v3/calendars/primary/events', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenResponse.access_token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(event)
      })
      .then(res => res.json())
      .then(data => {
        console.log('Event created:', data);
        alert(`"${assessment.title}" added to your Google Calendar!`);
      });
    }
  }).requestAccessToken();
}


// ── Grade Calculator ──────────────────────────────────────────────────────────

const GRADE_SCALES = {
  'letter-plus': {
    label: 'A+ to F (Canadian)',
    grades: [
      { label: 'A+', min: 90 }, { label: 'A',  min: 85 }, { label: 'A-', min: 80 },
      { label: 'B+', min: 77 }, { label: 'B',  min: 73 }, { label: 'B-', min: 70 },
      { label: 'C+', min: 67 }, { label: 'C',  min: 63 }, { label: 'C-', min: 60 },
      { label: 'D+', min: 57 }, { label: 'D',  min: 53 }, { label: 'D-', min: 50 },
      { label: 'F',  min:  0 },
    ]
  },
  'letter-simple': {
    label: 'A to F',
    grades: [
      { label: 'A', min: 90 }, { label: 'B', min: 80 },
      { label: 'C', min: 70 }, { label: 'D', min: 60 }, { label: 'F', min: 0 },
    ]
  },
  'percent': {
    label: 'Percentage',
    grades: [
      { label: '90–100%', min: 90 }, { label: '80–89%', min: 80 },
      { label: '70–79%', min: 70 }, { label: '60–69%', min: 60 },
      { label: '50–59%', min: 50 }, { label: '<50%',   min:  0 },
    ]
  },
  'gpa-4': {
    label: '4.0 GPA Scale',
    grades: [
      { label: '4.0', min: 90 }, { label: '3.7', min: 87 }, { label: '3.3', min: 83 },
      { label: '3.0', min: 80 }, { label: '2.7', min: 77 }, { label: '2.3', min: 73 },
      { label: '2.0', min: 70 }, { label: '1.7', min: 67 }, { label: '1.3', min: 63 },
      { label: '1.0', min: 60 }, { label: '0.7', min: 57 }, { label: '0.0', min:  0 },
    ]
  },
  'gpa-12': {
    label: '12-Point GPA (Waterloo)',
    grades: [
      { label: '12 · A+', min: 90 }, { label: '11 · A',  min: 85 }, { label: '10 · A-', min: 80 },
      { label: '9 · B+',  min: 77 }, { label: '8 · B',   min: 73 }, { label: '7 · B-',  min: 70 },
      { label: '6 · C+',  min: 67 }, { label: '5 · C',   min: 63 }, { label: '4 · C-',  min: 60 },
      { label: '3 · D+',  min: 57 }, { label: '2 · D',   min: 53 }, { label: '1 · D-',  min: 50 },
      { label: '0 · F',   min:  0 },
    ]
  },
};

let _gcCourseIndex = 0;
let _gcScaleKey    = 'letter-plus';

/**
 * Pure calculation: given assessments, entered scores, and a grade scale,
 * returns grade targets plus summary context for the UI.
 *
 * @param {Array}  assessments  - course.assessments array
 * @param {Array}  scores       - [{ index: number, value: 0-100 }]  (value already in %)
 * @param {string} scaleKey     - key into GRADE_SCALES
 * @returns {{ grades: Array, meta: Object }}
 */
function computeGradeResults(assessments, scores, scaleKey) {
  const scale = GRADE_SCALES[scaleKey];
  if (!scale || !assessments.length) return { grades: [], meta: null };

  const scoreMap = Object.fromEntries(scores.map(s => [s.index, s.value]));

  let earnedWeighted  = 0;
  let completedWeight = 0;
  const remainingAssessments = [];

  assessments.forEach((a, i) => {
    const w = a.weight_percent || 0;
    if (scoreMap[i] !== undefined) {
      earnedWeighted  += (scoreMap[i] / 100) * w;
      completedWeight += w;
    } else {
      remainingAssessments.push({ title: a.title, weight: w, index: i });
    }
  });

  const remainingWeight = remainingAssessments.reduce((s, a) => s + a.weight, 0);
  const totalWeight     = completedWeight + remainingWeight;

  // Current grade expressed as % of total course weight (not of completed work)
  const currentPct = completedWeight > 0
    ? Math.round((earnedWeighted / totalWeight) * 1000) / 10
    : null;

  const currentGradeLabel = currentPct !== null
    ? (scale.grades.find(g => currentPct >= g.min) || scale.grades[scale.grades.length - 1]).label
    : null;

  const meta = {
    currentPct,
    currentGradeLabel,
    completedWeight: Math.round(completedWeight * 10) / 10,
    remainingWeight: Math.round(remainingWeight * 10) / 10,
    completedCount:  scores.length,
    remainingCount:  remainingAssessments.length,
    remainingAssessments,
    allComplete:     remainingWeight === 0 && completedWeight > 0,
  };

  const grades = scale.grades.map(grade => {
    if (remainingWeight === 0) {
      const finalGrade = totalWeight > 0 ? (earnedWeighted / totalWeight) * 100 : 0;
      return { ...grade, allComplete: true, finalGrade, achieved: finalGrade >= grade.min };
    }

    // earnedWeighted + (needed/100 * remainingWeight) = (grade.min/100) * totalWeight
    const needed  = ((grade.min / 100) * totalWeight - earnedWeighted) / remainingWeight * 100;
    const rounded = Math.round(needed * 10) / 10;

    return {
      ...grade,
      needed,
      neededRounded: rounded,
      guaranteed:    rounded <= 0,
      impossible:    rounded > 100,
      tight:         rounded > 80 && rounded <= 100,
    };
  });

  return { grades, meta };
}

function renderGradeCalc() {
  const section = document.getElementById('grade-calc-section');
  if (!allCourses.length) return;
  section.style.display = 'block';

  const courseSelect = document.getElementById('gc-course-select');
  courseSelect.innerHTML = allCourses.map((c, i) =>
    `<option value="${i}">${c.course_code || c.course_title || 'Course ' + (i + 1)}</option>`
  ).join('');

  _gcCourseIndex = allCourses.length - 1;
  courseSelect.value = _gcCourseIndex;

  renderGcBody();
}

function renderGcBody() {
  const course = allCourses[_gcCourseIndex];
  if (!course) return;
  const assessments = course.assessments || [];

  document.getElementById('gc-inputs').innerHTML = `
    <div class="gc-panel-title">Your Scores</div>
    <p class="gc-hint">
      Enter each score you've received. Change the denominator if your exam
      wasn't out of 100 — the percentage is calculated automatically.
      Leave blank for upcoming assessments.
    </p>
    <div class="gc-input-list">
      ${assessments.map((a, i) => `
        <div class="gc-input-row">
          <div class="gc-input-info">
            <span class="gc-input-name">${a.title || 'Assessment'}</span>
            <span class="gc-input-weight">${a.weight_percent != null ? a.weight_percent + '% of final grade' : 'weight unknown'}</span>
          </div>
          <div class="gc-input-field-wrap">
            <input
              type="number"
              class="gc-score-input"
              data-index="${i}"
              placeholder="—"
              min="0" step="0.1"
              aria-label="Score for ${a.title}"
            />
            <span class="gc-input-sep">/</span>
            <input
              type="number"
              class="gc-outof-input"
              data-index="${i}"
              value="100"
              min="0.1" step="0.1"
              aria-label="Out of"
            />
            <span class="gc-pct-preview" id="gc-preview-${i}">—</span>
          </div>
        </div>
      `).join('')}
    </div>
  `;

  // Wire inputs: any change on either field updates the preview + results
  assessments.forEach((_, i) => {
    const scoreEl = document.querySelector(`.gc-score-input[data-index="${i}"]`);
    const outofEl = document.querySelector(`.gc-outof-input[data-index="${i}"]`);
    const preview = document.getElementById(`gc-preview-${i}`);

    function syncPreview() {
      const s = parseFloat(scoreEl.value);
      const o = parseFloat(outofEl.value) || 100;
      if (!isNaN(s) && s >= 0) {
        const pct = Math.round((s / o) * 1000) / 10;
        preview.textContent = `${pct}%`;
        preview.classList.add('has-value');
      } else {
        preview.textContent = '—';
        preview.classList.remove('has-value');
      }
      refreshGcResults();
    }

    scoreEl.addEventListener('input', syncPreview);
    outofEl.addEventListener('input', syncPreview);
  });

  refreshGcResults();
}

function refreshGcResults() {
  const course = allCourses[_gcCourseIndex];
  if (!course) return;
  const assessments = course.assessments || [];

  // Collect scores — convert from raw/outOf to percentage
  const scores = [];
  assessments.forEach((_, i) => {
    const scoreEl = document.querySelector(`.gc-score-input[data-index="${i}"]`);
    const outofEl = document.querySelector(`.gc-outof-input[data-index="${i}"]`);
    if (!scoreEl) return;
    const raw   = parseFloat(scoreEl.value);
    const outOf = parseFloat(outofEl?.value) || 100;
    if (!isNaN(raw) && raw >= 0) {
      scores.push({ index: i, value: Math.min(100, (raw / outOf) * 100) });
    }
  });

  const { grades, meta } = computeGradeResults(assessments, scores, _gcScaleKey);

  // ── Standing card ──────────────────────────────────────────────────────
  let standingHTML;
  if (!meta || scores.length === 0) {
    standingHTML = `
      <div class="gc-standing-card">
        <div class="gc-standing-empty">Enter your scores on the left to see your standing.</div>
      </div>`;
  } else if (meta.allComplete) {
    const achieved = grades.find(g => g.achieved) || grades[grades.length - 1];
    standingHTML = `
      <div class="gc-standing-card">
        <div class="gc-standing-label">Final Grade</div>
        <div class="gc-standing-row">
          <span class="gc-standing-pct">${meta.currentPct !== null ? meta.currentPct.toFixed(1) : '—'}%</span>
          <span class="gc-standing-grade-badge">${achieved?.label ?? '—'}</span>
        </div>
        <div class="gc-standing-sub">All ${assessments.length} assessments entered. This is your final grade.</div>
      </div>`;
  } else {
    standingHTML = `
      <div class="gc-standing-card">
        <div class="gc-standing-label">Current Standing</div>
        <div class="gc-standing-row">
          <span class="gc-standing-pct">${meta.currentPct !== null ? meta.currentPct.toFixed(1) : '—'}%</span>
          ${meta.currentGradeLabel ? `<span class="gc-standing-grade-badge">${meta.currentGradeLabel} range</span>` : ''}
        </div>
        <div class="gc-standing-sub">
          Based on <strong>${meta.completedCount} assessment${meta.completedCount !== 1 ? 's' : ''}</strong>
          worth <strong>${meta.completedWeight}%</strong> of your grade.
          <strong>${meta.remainingWeight}%</strong> still ahead across
          ${meta.remainingCount} remaining assessment${meta.remainingCount !== 1 ? 's' : ''}.
        </div>
      </div>`;
  }

  // ── Grade target rows ──────────────────────────────────────────────────
  const gradesHTML = grades.map(r => {
    let status, displayVal, detail, barPct;

    if (r.allComplete) {
      status     = r.achieved ? 'achieved' : 'missed';
      displayVal = `${r.finalGrade.toFixed(1)}% — ${r.achieved ? 'Achieved ✓' : 'Not reached'}`;
      detail     = '';
      barPct     = r.finalGrade;
    } else if (!meta || scores.length === 0) {
      status     = r.impossible ? 'impossible' : r.tight ? 'tight' : 'achievable';
      displayVal = r.impossible ? 'Not achievable' : `Need ${r.neededRounded}% avg`;
      detail     = r.impossible
        ? `Requires more than 100% on remaining work`
        : `Average across ${meta?.remainingCount ?? '?'} remaining assessment${(meta?.remainingCount ?? 0) !== 1 ? 's' : ''} (${meta?.remainingWeight ?? '?'}% of grade)`;
      barPct     = r.impossible ? 100 : r.neededRounded;
    } else if (r.guaranteed) {
      status     = 'guaranteed';
      displayVal = 'Already secured ✓';
      detail     = `You've locked this in — even 0% on everything remaining gets you here.`;
      barPct     = 100;
    } else if (r.impossible) {
      status     = 'impossible';
      displayVal = 'Not achievable';
      detail     = `Would need more than 100% on remaining work.`;
      barPct     = 100;
    } else {
      status     = r.tight ? 'tight' : 'achievable';
      displayVal = `Need ${r.neededRounded}% avg`;
      detail     = `Average needed across ${meta.remainingCount} remaining assessment${meta.remainingCount !== 1 ? 's' : ''} (worth ${meta.remainingWeight}% of your grade)`;
      barPct     = r.neededRounded;
    }

    return `
      <div class="gc-result-row gc-status-${status}">
        <div class="gc-result-left">
          <span class="gc-result-grade">${r.label}</span>
          <span class="gc-result-min">≥ ${r.min}%</span>
        </div>
        <div class="gc-result-right">
          <span class="gc-result-value">${displayVal}</span>
          ${detail ? `<span class="gc-result-detail">${detail}</span>` : ''}
          <div class="gc-result-bar-track">
            <div class="gc-result-bar-fill" style="width:${Math.min(100, Math.max(0, barPct))}%"></div>
          </div>
        </div>
      </div>`;
  }).join('');

  // ── Remaining assessments breakdown ────────────────────────────────────
  let remainingHTML = '';
  if (meta && meta.remainingAssessments.length > 0) {
    remainingHTML = `
      <div class="gc-remaining-section">
        <div class="gc-remaining-title">Remaining Assessments</div>
        <div class="gc-remaining-list">
          ${meta.remainingAssessments.map(a => `
            <div class="gc-remaining-row">
              <span class="gc-remaining-name">${a.title || 'Untitled'}</span>
              <span class="gc-remaining-weight">${a.weight}% of grade</span>
            </div>`).join('')}
        </div>
      </div>`;
  }

  document.getElementById('gc-results').innerHTML = `
    <div class="gc-panel-title">Grade Targets</div>
    ${standingHTML}
    <div class="gc-results-list">${gradesHTML}</div>
    ${remainingHTML}
  `;
}

// Static listeners for gc controls
document.getElementById('gc-course-select').addEventListener('change', e => {
  _gcCourseIndex = parseInt(e.target.value);
  renderGcBody();
});
document.getElementById('gc-scale-select').addEventListener('change', e => {
  _gcScaleKey = e.target.value;
  refreshGcResults();
});