// Pie chart of assessment weights with editable legend rows.

import { courses } from './state.js';
import { escapeHtml } from './utils.js';

const CHART_COLORS = [
  '#8FB89E',
  '#F5C9B8',
  '#C9B8E8',
  '#A8D4E6',
  '#F2A6A6',
  '#FFD93D',
  '#B8D4C4',
  '#E8A68F',
];

const resultsEl  = document.getElementById('results');
const legendEl   = document.getElementById('legend');
const canvasEl   = document.getElementById('pie-chart');
const dropdownEl = document.getElementById('drop-menu');

let chartInstance  = null;
let _editingIndex  = null;
let _currentIndex  = 0;

function renderLegendItem(a, i, color) {
  return `
    <div class="legend-item" data-index="${i}">
      <span class="dot" style="background:${color}"></span>
      <span class="legend-label">${escapeHtml(a.title || '')}</span>
      <span class="legend-weight">${a.weight_percent != null ? a.weight_percent + '%' : '—'}</span>
      <button class="legend-edit-btn" data-index="${i}" aria-label="Edit">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
      </button>
    </div>
  `;
}

function renderLegendEditItem(a, i, color) {
  return `
    <div class="legend-item legend-item--editing" data-index="${i}">
      <span class="dot" style="background:${color}"></span>
      <input
        class="legend-edit-input legend-edit-title"
        type="text"
        value="${escapeHtml(a.title || '')}"
        placeholder="Title"
        data-index="${i}"
      />
      <div class="legend-edit-weight-wrap">
        <input
          class="legend-edit-input legend-edit-weight"
          type="number"
          min="0"
          max="100"
          step="0.1"
          value="${a.weight_percent != null ? a.weight_percent : ''}"
          placeholder="0"
          data-index="${i}"
        />
        <span class="legend-edit-pct">%</span>
      </div>
      <div class="legend-edit-actions">
        <button class="legend-save-btn" data-index="${i}" aria-label="Save">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </button>
        <button class="legend-cancel-btn" data-index="${i}" aria-label="Cancel">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
    </div>
  `;
}

function buildLegend(courseIndex) {
  const course      = courses[courseIndex];
  const assessments = course?.assessments || [];

  legendEl.innerHTML = `
    <div class="course-title">${escapeHtml(course?.course_title || course?.course_code || 'Course')}</div>
    ${assessments.map((a, i) => {
      const color = CHART_COLORS[i % CHART_COLORS.length];
      return i === _editingIndex
        ? renderLegendEditItem(a, i, color)
        : renderLegendItem(a, i, color);
    }).join('')}
  `;

  attachLegendListeners(courseIndex, assessments);
}

function attachLegendListeners(courseIndex, assessments) {
  legendEl.querySelectorAll('.legend-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _editingIndex = parseInt(btn.dataset.index);
      buildLegend(courseIndex);
      legendEl.querySelector('.legend-edit-title')?.focus();
    });
  });

  legendEl.querySelector('.legend-save-btn')?.addEventListener('click', () => {
    commitEdit(courseIndex);
  });

  legendEl.querySelector('.legend-cancel-btn')?.addEventListener('click', () => {
    _editingIndex = null;
    buildLegend(courseIndex);
  });

  legendEl.querySelectorAll('.legend-edit-input').forEach(input => {
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter')  commitEdit(courseIndex);
      if (e.key === 'Escape') {
        _editingIndex = null;
        buildLegend(courseIndex);
      }
    });
  });
}

function commitEdit(courseIndex) {
  const i          = _editingIndex;
  const assessment = courses[courseIndex]?.assessments?.[i];
  if (!assessment) return;

  const titleInput  = legendEl.querySelector('.legend-edit-title');
  const weightInput = legendEl.querySelector('.legend-edit-weight');

  const newTitle  = titleInput?.value.trim();
  const newWeight = parseFloat(weightInput?.value);

  if (newTitle)                             assessment.title          = newTitle;
  if (!isNaN(newWeight) && newWeight >= 0)  assessment.weight_percent = newWeight;

  _editingIndex = null;
  rebuildChart(courseIndex);

  window.dispatchEvent(new CustomEvent('sylva:assessmentupdated'));
}

function rebuildChart(courseIndex) {
  const course      = courses[courseIndex];
  const assessments = course?.assessments || [];

  buildLegend(courseIndex);

  if (chartInstance) chartInstance.destroy();
  chartInstance = new Chart(canvasEl, {
    type: 'pie',
    data: {
      labels: assessments.map(a => a.title),
      datasets: [{
        data: assessments.map(a => a.weight_percent),
        backgroundColor: CHART_COLORS,
        borderWidth: 3,
        borderColor: '#FDF8F3',
      }],
    },
    options: {
      animation: { duration: 600, easing: 'easeOutQuart', animateScale: true },
      responsive: false,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#3D3D3D',
          titleFont: { family: "'DM Sans', sans-serif", weight: 600 },
          bodyFont:  { family: "'DM Sans', sans-serif" },
          padding: 12,
          cornerRadius: 8,
          callbacks: { label: (item) => ` ${item.parsed}%` },
        },
      },
    },
  });
}

export function renderChart(index) {
  const course = courses[index];
  if (!course) return;

  _currentIndex = index;
  _editingIndex = null;
  resultsEl.classList.add('show');

  legendEl.classList.remove('animate');
  void legendEl.offsetWidth; // force reflow so the slide-in re-triggers
  rebuildChart(index);
  legendEl.classList.add('animate');
}

export function getCurrentChartIndex() {
  return _currentIndex;
}

export function updateDropdown() {
  if (courses.length <= 1) {
    dropdownEl.classList.remove('show');
    return;
  }
  dropdownEl.classList.add('show');
  dropdownEl.innerHTML = '';
  courses.forEach((course, i) => {
    const option = document.createElement('option');
    option.value = i;
    option.textContent = (course.course_code || '') + ' ' + (course.course_title || '');
    dropdownEl.appendChild(option);
  });
  dropdownEl.value = courses.length - 1;
}

dropdownEl.addEventListener('change', e => {
  renderChart(parseInt(e.target.value));
});