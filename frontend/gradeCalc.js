/* ═══════════════════════════════════════════════════════════════════════════
   GRADE CALCULATOR — score input panel + per-grade target panel
═══════════════════════════════════════════════════════════════════════════ */

import { courses } from './state.js';
import { escapeHtml, expandAssessments } from './utils.js';

const sectionEl      = document.getElementById('grade-calc-section');
const courseSelectEl = document.getElementById('gc-course-select');
const scaleSelectEl  = document.getElementById('gc-scale-select');
const inputsEl       = document.getElementById('gc-inputs');
const resultsEl      = document.getElementById('gc-results');

let courseIndex = 0;
let scaleKey    = 'letter-plus';
let _mounted    = false;

// Persistent score inputs across re-renders, keyed by stable assessment id.
// Stable id format: `${courseIndex}::${originalIdx}::${expandedIdx}` where
//   originalIdx  – position in `course.assessments` (survives title/weight edits)
//   expandedIdx  – 0 for non-expanded items, 1..N for multi-date occurrences
// Values are { score, outOf } as the raw input strings (so a half-typed
// "9" doesn't get re-formatted to "9" mid-keystroke).
const scoreInputs = new Map();

function makeAssessmentId(courseIdx, originals, a) {
  const originalIdx = a._parentTitle !== undefined
    ? originals.findIndex(o => o.title === a._parentTitle)
    : originals.indexOf(a);
  return `${courseIdx}::${originalIdx}::${a._expandedIndex ?? 0}`;
}

const GRADE_SCALES = {
  'letter-plus': {
    label: 'A+ to F (Canadian)',
    grades: [
      { label: 'A+', min: 90 }, { label: 'A',  min: 85 }, { label: 'A-', min: 80 },
      { label: 'B+', min: 77 }, { label: 'B',  min: 73 }, { label: 'B-', min: 70 },
      { label: 'C+', min: 67 }, { label: 'C',  min: 63 }, { label: 'C-', min: 60 },
      { label: 'D+', min: 57 }, { label: 'D',  min: 53 }, { label: 'D-', min: 50 },
      { label: 'F',  min: 0  },
    ],
  },
  'letter-simple': {
    label: 'A to F',
    grades: [
      { label: 'A', min: 90 }, { label: 'B', min: 80 },
      { label: 'C', min: 70 }, { label: 'D', min: 60 }, { label: 'F', min: 0 },
    ],
  },
  'percent': {
    label: 'Percentage',
    grades: [
      { label: '90-100%', min: 90 }, { label: '80-89%', min: 80 },
      { label: '70-79%',  min: 70 }, { label: '60-69%', min: 60 },
      { label: '50-59%',  min: 50 }, { label: '<50%',   min: 0  },
    ],
  },
  'gpa-4': {
    label: '4.0 GPA Scale',
    grades: [
      { label: '4.0', min: 90 }, { label: '3.7', min: 87 }, { label: '3.3', min: 83 },
      { label: '3.0', min: 80 }, { label: '2.7', min: 77 }, { label: '2.3', min: 73 },
      { label: '2.0', min: 70 }, { label: '1.7', min: 67 }, { label: '1.3', min: 63 },
      { label: '1.0', min: 60 }, { label: '0.7', min: 57 }, { label: '0.0', min: 0  },
    ],
  },
  'gpa-12': {
    label: '12-Point GPA',
    grades: [
      { label: '12 A+', min: 90 }, { label: '11 A',  min: 85 }, { label: '10 A-', min: 80 },
      { label: '9 B+',  min: 77 }, { label: '8 B',   min: 73 }, { label: '7 B-',  min: 70 },
      { label: '6 C+',  min: 67 }, { label: '5 C',   min: 63 }, { label: '4 C-',  min: 60 },
      { label: '3 D+',  min: 57 }, { label: '2 D',   min: 53 }, { label: '1 D-',  min: 50 },
      { label: '0 F',   min: 0  },
    ],
  },
};

function computeGradeResults(assessments, scores, key) {
  const scale = GRADE_SCALES[key];
  if (!scale || !assessments.length) return { grades: [], meta: null };

  const scoreMap = Object.fromEntries(scores.map(s => [s.index, s.value]));

  let earnedWeighted = 0;
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

  const currentPct = completedWeight > 0
    ? Math.round((earnedWeighted / completedWeight) * 1000) / 10
    : null;

  const currentGradeLabel = currentPct !== null
    ? (scale.grades.find(g => currentPct >= g.min) || scale.grades[scale.grades.length - 1]).label
    : null;

  const meta = {
    currentPct,
    currentGradeLabel,
    completedWeight: Math.round(completedWeight * 10) / 10,
    remainingWeight: Math.round(remainingWeight * 10) / 10,
    completedCount: scores.length,
    remainingCount: remainingAssessments.length,
    remainingAssessments,
    allComplete: remainingWeight === 0 && completedWeight > 0,
  };

  const grades = scale.grades.map(grade => {
    if (remainingWeight === 0) {
      const finalGrade = totalWeight > 0 ? (earnedWeighted / totalWeight) * 100 : 0;
      return { ...grade, allComplete: true, finalGrade, achieved: finalGrade >= grade.min };
    }

    const needed = ((grade.min / 100) * totalWeight - earnedWeighted) / remainingWeight * 100;
    const rounded = Math.round(needed * 10) / 10;

    return {
      ...grade,
      needed,
      neededRounded: rounded,
      guaranteed: rounded <= 0,
      impossible: rounded > 100,
      tight: rounded > 80 && rounded <= 100,
    };
  });

  return { grades, meta };
}

export function renderGradeCalc() {
  if (!courses.length) return;
  sectionEl.classList.add('show');

  courseSelectEl.innerHTML = courses.map((c, i) =>
    `<option value="${i}">${escapeHtml(c.course_code || c.course_title || 'Course ' + (i + 1))}</option>`
  ).join('');

  // Only reset on first mount or when the previously-selected index is no
  // longer valid (e.g. courses were cleared and reloaded with fewer entries).
  // Otherwise the user's selection is preserved across re-renders.
  if (!_mounted || courseIndex >= courses.length || courseIndex < 0) {
    courseIndex = courses.length - 1;
    _mounted = true;
  }
  courseSelectEl.value = courseIndex;

  renderGcBody();
}

function renderGcBody() {
  const course = courses[courseIndex];
  if (!course) return;
  // Expand multi-date assessments so each occurrence has its own input row
  // and its own (proportionally divided) weight.
  const originals   = course.assessments || [];
  const assessments = expandAssessments(originals);
  const ids         = assessments.map(a => makeAssessmentId(courseIndex, originals, a));

  inputsEl.innerHTML = `
    <div class="gc-panel-title">Your Scores</div>
    <p class="gc-hint">
      Enter each score you have received. Leave blank for upcoming assessments.
    </p>
    <div class="gc-input-list">
      ${assessments.map((a, i) => `
        <div class="gc-input-row">
          <div class="gc-input-info">
            <span class="gc-input-name">${escapeHtml(a.title || 'Assessment')}</span>
            <span class="gc-input-weight">${a.weight_percent != null ? a.weight_percent + '% of grade' : ''}</span>
          </div>
          <div class="gc-input-field-wrap">
            <input
              type="number"
              class="gc-score-input"
              data-index="${i}"
              data-id="${ids[i]}"
              placeholder="-"
              min="0" step="0.1"
            />
            <span class="gc-input-sep">/</span>
            <input
              type="number"
              class="gc-outof-input"
              data-index="${i}"
              data-id="${ids[i]}"
              value="100"
              min="0.1" step="0.1"
            />
            <span class="gc-pct-preview" id="gc-preview-${i}">-</span>
          </div>
        </div>
      `).join('')}
    </div>
  `;

  assessments.forEach((_, i) => {
    const scoreEl = document.querySelector(`.gc-score-input[data-index="${i}"]`);
    const outofEl = document.querySelector(`.gc-outof-input[data-index="${i}"]`);
    const preview = document.getElementById(`gc-preview-${i}`);
    const id      = ids[i];

    // Restore previously-entered values for this assessment (if any).
    const saved = scoreInputs.get(id);
    if (saved) {
      if (saved.score !== undefined) scoreEl.value = saved.score;
      if (saved.outOf !== undefined) outofEl.value = saved.outOf;
    }

    function syncPreview() {
      // Persist current raw values before recomputing — Map is the source of
      // truth across re-renders triggered by edits in other panels.
      scoreInputs.set(id, { score: scoreEl.value, outOf: outofEl.value });

      const s = parseFloat(scoreEl.value);
      const o = parseFloat(outofEl.value) || 100;
      if (!isNaN(s) && s >= 0) {
        const pct = Math.round((s / o) * 1000) / 10;
        preview.textContent = `${pct}%`;
        preview.classList.add('has-value');
      } else {
        preview.textContent = '-';
        preview.classList.remove('has-value');
      }
      refreshGcResults(assessments);
    }

    // Sync the preview once on mount so restored values render correctly.
    if (saved) syncPreview();

    scoreEl.addEventListener('input', syncPreview);
    outofEl.addEventListener('input', syncPreview);
  });

  refreshGcResults(assessments);
}

function refreshGcResults(assessments) {
  const course = courses[courseIndex];
  if (!course) return;
  // Accept a pre-expanded list (from renderGcBody) or build one on the fly
  // when called from the scale/course selectors without an explicit list.
  if (!assessments) assessments = expandAssessments(course.assessments || []);

  const scores = [];
  assessments.forEach((_, i) => {
    const scoreEl = document.querySelector(`.gc-score-input[data-index="${i}"]`);
    const outofEl = document.querySelector(`.gc-outof-input[data-index="${i}"]`);
    if (!scoreEl) return;
    const raw   = parseFloat(scoreEl.value);
    const outOf = parseFloat(outofEl?.value) || 100;
    if (!isNaN(raw) && raw >= 0) {
      scores.push({ index: i, value: (raw / outOf) * 100 });
    }
  });

  const { grades, meta } = computeGradeResults(assessments, scores, scaleKey);

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
          <span class="gc-standing-pct">${meta.currentPct !== null ? meta.currentPct.toFixed(1) : '-'}%</span>
          <span class="gc-standing-grade-badge">${achieved?.label ?? '-'}</span>
        </div>
        <div class="gc-standing-sub">All ${assessments.length} assessments entered.</div>
      </div>`;
  } else {
    standingHTML = `
      <div class="gc-standing-card">
        <div class="gc-standing-label">Current Standing</div>
        <div class="gc-standing-row">
          <span class="gc-standing-pct">${meta.currentPct !== null ? meta.currentPct.toFixed(1) : '-'}%</span>
          ${meta.currentGradeLabel ? `<span class="gc-standing-grade-badge">${meta.currentGradeLabel}</span>` : ''}
        </div>
        <div class="gc-standing-sub">
          Based on <strong>${meta.completedCount} assessment${meta.completedCount !== 1 ? 's' : ''}</strong>
          worth <strong>${meta.completedWeight}%</strong>.
          <strong>${meta.remainingWeight}%</strong> remaining.
        </div>
      </div>`;
  }

  const gradesHTML = grades.map(r => {
    let status, displayVal, detail, barPct;

    if (r.allComplete) {
      status     = r.achieved ? 'achieved' : 'missed';
      displayVal = r.achieved ? 'Achieved' : 'Not reached';
      detail     = '';
      barPct     = r.finalGrade;
    } else if (!meta || scores.length === 0) {
      status     = r.impossible ? 'impossible' : r.tight ? 'tight' : 'achievable';
      displayVal = r.impossible ? 'Not achievable' : `Need ${r.neededRounded}% avg`;
      detail     = '';
      barPct     = r.impossible ? 100 : r.neededRounded;
    } else if (r.guaranteed) {
      status     = 'guaranteed';
      displayVal = 'Already secured';
      detail     = '';
      barPct     = 100;
    } else if (r.impossible) {
      status     = 'impossible';
      displayVal = 'Not achievable';
      detail     = '';
      barPct     = 100;
    } else {
      status     = r.tight ? 'tight' : 'achievable';
      displayVal = `Need ${r.neededRounded}% avg`;
      detail     = `on ${meta.remainingCount} remaining`;
      barPct     = r.neededRounded;
    }

    return `
      <div class="gc-result-row gc-status-${status}">
        <div class="gc-result-left">
          <span class="gc-result-grade">${r.label}</span>
          <span class="gc-result-min">${r.min}%+</span>
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

  let remainingHTML = '';
  if (meta && meta.remainingAssessments.length > 0) {
    remainingHTML = `
      <div class="gc-remaining-section">
        <div class="gc-remaining-title">Remaining Assessments</div>
        <div class="gc-remaining-list">
          ${meta.remainingAssessments.map(a => `
            <div class="gc-remaining-row">
              <span class="gc-remaining-name">${escapeHtml(a.title || 'Untitled')}</span>
              <span class="gc-remaining-weight">${a.weight}%</span>
            </div>`).join('')}
        </div>
      </div>`;
  }

  resultsEl.innerHTML = `
    <div class="gc-panel-title">Grade Targets</div>
    ${standingHTML}
    <div class="gc-results-list">${gradesHTML}</div>
    ${remainingHTML}
  `;
}

// ── Static listeners ────────────────────────────────────────────────────────
courseSelectEl.addEventListener('change', e => {
  courseIndex = parseInt(e.target.value);
  renderGcBody();
});

scaleSelectEl.addEventListener('change', e => {
  scaleKey = e.target.value;
  refreshGcResults();
});