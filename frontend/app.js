const SAMPLE = {
  filename: "1020e-650_su25-devereux_public.pdf",
  data: {
    courses: [{
      course_code: "ENG1020E",
      course_title: "English Literature",
      term: "2025",
      section_code: "650",
      instructor: "Dr. Devereux",
      email: "jdevereu@uwo.ca",
      office_hours: "Tuesdays and Thursdays at 10 AM to 11 AM Ontario time or by appointment",
      class_meetings: [],
      assessments: [
        { title: "Discussion Forum Participation", weight_percent: 15, confidence: 0.95 },
        { title: "Essay 1", weight_percent: 15, date: "2026-05-26", time: "11:59 PM", confidence: 0.95 },
        { title: "Online Midterm Test", weight_percent: 10, start: "2026-06-16", end: "2026-06-17", confidence: 0.95 },
        { title: "Essay 2", weight_percent: 25, date: "2026-07-07", time: "11:59 PM", confidence: 0.95 },
        { title: "Final Exam", weight_percent: 35, start: "2026-07-28", end: "2026-07-31", confidence: 0.95 }
      ],
      schedule: [
        { week: 1, topic: "Prosody and Verse", start: "2025-05-05", end: "2025-05-11" },
        { week: 2, topic: "Sonnets", start: "2025-05-12", end: "2025-05-18" },
        { week: 3, topic: "Sir Gawain and the Green Knight", start: "2025-05-19", end: "2025-05-25" },
        { week: 4, topic: "Shakespeare, As You Like It", start: "2025-05-26", end: "2025-06-01" },
        { week: 5, topic: "Drew Hayden Taylor, In a World created by a Drunken God", start: "2025-06-02", end: "2025-06-08" },
        { week: 6, topic: "Téa Mutonji, Shut Up You're Pretty", start: "2025-06-09", end: "2025-06-15" },
        { week: 7, topic: "Wordsworth and Keats", start: "2025-06-16", end: "2025-06-22" },
        { week: 8, topic: "Tennyson, 'Mariana,' 'Lady of Shalott,' 'Tithonus'", start: "2025-06-23", end: "2025-06-29" },
        { week: 9, topic: "Charlotte Brontë, Jane Eyre", start: "2025-06-30", end: "2025-07-06" },
        { week: 10, topic: "Mary Seacole, Wonderful Adventures", start: "2025-07-07", end: "2025-07-13" },
        { week: 11, topic: "Gwendolyn Brooks, poems", start: "2025-07-14", end: "2025-07-20" },
        { week: 12, topic: "Browning, 'My Last Duchess'; W.B. Yeats", start: "2025-07-21", end: "2025-07-27" }
      ],
      policies: [
        "Academic Integrity Tutorial is mandatory. Certificate must be uploaded by second week.",
        "All instances of plagiarism will be reported and result in a grade of zero for the assignment. Subsequent offences will result in failure for the course.",
        "Use of generative AI is not permitted and will be considered a scholastic offence.",
        "Late essays will receive a penalty of 1% per day late including weekends. Late essays will forfeit instructor feedback.",
        "Western is committed to reducing incidents of gender-based and sexual violence (GBSV) and providing support services for survivors.",
        "Requests linked to examinations require formal supporting documentation.",
        "All instructor-written materials are the instructor's intellectual property. Unauthorized distribution is a copyright infringement and academic integrity violation."
      ]
    }]
  }
};

const allCourses = [];
let calendarInstance = null;

document.querySelector('.drop-button').addEventListener('click', () => {
  document.querySelector('input[type="file"]').click();
});

const input = document.querySelector('input[type="file"]');

input.addEventListener('change', () => {
  const file = input.files[0];
  if (!file) return;
  allCourses.push(SAMPLE.data.courses[0]);
  updateDropdown();
  renderChart(allCourses.length - 1);
  if (allCourses.length === 1) {
    document.getElementById('calendar-section').style.display = 'block';
    initCalendar();
  }
});

function renderChart(index) {
  const course = allCourses[index];
  const assessments = course.assessments;

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

  document.getElementById('results').style.display = 'block';

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
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const upcoming = course.assessments
    .filter(a => {
      if (!a.date && !a.start) return false;
      const d = new Date(a.date || a.start);
      return d >= today;
    })
    .sort((a, b) => new Date(a.date || a.start) - new Date(b.date || b.start));

  const listEl = document.querySelector('.assessment-list');
  listEl.style.display = 'block';
  listEl.innerHTML = upcoming.map((a, i) => `
    <div class="assessment-row">
      <span class="assessment-title">${a.title}</span>
      <span class="assessment-date">${a.date || a.start}</span>
      <button class="add-btn" data-index="${i}">+ Add to Calendar</button>
    </div>
  `).join('');

  document.querySelectorAll('.add-btn').forEach((btn, i) => {
    btn.addEventListener('click', () => addToGoogleCalendar(upcoming[i]));
  });
}


function initCalendar() {
  calendarInstance = new FullCalendar.Calendar(document.getElementById('calendar'), {
    initialView: 'dayGridMonth',
    events: allCourses.flatMap(course => [
      ...course.assessments
        .filter(a => a.date || a.start)
        .map(a => a.date
          ? { title: a.title, date: a.date, color: '#9E3B3B', extendedProps: { type: 'assessment', description: `Worth ${a.weight_percent}%`, time: a.time || null } }
          : { title: a.title, start: a.start, end: a.end, color: '#9E3B3B', extendedProps: { type: 'assessment', description: `Worth ${a.weight_percent}%`, time: a.time || null } }
        ),
      ...course.schedule.map(s => ({
        title: `Week ${s.week}: ${s.topic}`,
        start: s.start,
        end: s.end,
        color: '#A3B18A',
        extendedProps: { type: 'week', description: s.topic }
      }))
    ]),
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

document.getElementById('calendar-filters').addEventListener('change', () => {
  const checked = [...document.querySelectorAll('#calendar-filters input:checked')].map(i => i.value);
  calendarInstance.getEvents().forEach(e => {
    e.setProp('display', checked.includes(e.extendedProps.type) ? 'auto' : 'none');
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
}


const CLIENT_ID = "527779540782-69q8f06ust49om49b9g36cknv1pes405.apps.googleusercontent.com";
const SCOPES = 'https://www.googleapis.com/auth/calendar.events';

function addToGoogleCalendar(assessment) {
  google.accounts.oauth2.initTokenClient({
    client_id: CLIENT_ID,
    scope: SCOPES,
    callback: (tokenResponse) => {
      const event = {
        summary: assessment.title,
        description: `Worth ${assessment.weight_percent}%`,
        ...(assessment.date
          ? { start: { date: assessment.date }, end: { date: assessment.date } }
          : { start: { date: assessment.start }, end: { date: assessment.end } }
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