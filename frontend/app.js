const $ = id => document.getElementById(id);

/* ── CONSTANTS ── */
const BIZ_START = 7;
const BIZ_END   = 19;
const BIZ_HRS   = BIZ_END - BIZ_START;

/* ── STATE ── */
let currentUser = '';
let tickets = [];
let reviewed = new Set();
let reviewMode = false;
let currentDept = 'VoIP';
let currentFilter = 'all';
let timerInterval = null;

/* ── HELPERS ── */
function bizHoursBetween(start, end) {
  if (!start || !end || end <= start) return 0;
  let total = 0;
  let cursor = new Date(start);

  while (cursor < end) {
    const day = cursor.getDay();
    if (day !== 0 && day !== 6) {
      const ds = new Date(cursor); ds.setHours(BIZ_START,0,0,0);
      const de = new Date(cursor); de.setHours(BIZ_END,0,0,0);
      const s = Math.max(cursor, ds);
      const e = Math.min(end, de);
      if (e > s) total += (e - s) / 3600000;
    }
    cursor.setDate(cursor.getDate() + 1);
    cursor.setHours(BIZ_START,0,0,0);
  }
  return total;
}

function fmtDuration(h) {
  if (h < 1) return Math.round(h * 60) + 'm';
  if (h < 24) return h.toFixed(1) + 'h';
  return (h / BIZ_HRS).toFixed(1) + 'd';
}

function fmtAgo(dt) {
  if (!dt) return '—';
  const diff = (Date.now() - dt) / 60000;
  if (diff < 60) return Math.round(diff) + 'm ago';
  if (diff < 1440) return Math.round(diff/60) + 'h ago';
  return Math.round(diff/1440) + 'd ago';
}

/* ── LOGIN ── */
$('login-btn').onclick = () => {
  const email = $('login-email').value.trim().toLowerCase();
  const pass = $('login-pass').value;

  if (!email.endsWith('@adit.com')) {
    $('login-error').textContent = 'Use @adit.com email';
    return;
  }
  if (!pass) {
    $('login-error').textContent = 'Enter password';
    return;
  }

  currentUser = email;
  $('login-screen').style.display = 'none';
  $('main-app').style.display = 'flex';
  $('user-badge').textContent = email;
};

/* ── LOGOUT ── */
$('logout-btn').onclick = () => {
  location.reload();
};

/* ── FILE UPLOAD ── */
$('upload-zone').onclick = () => $('file-input').click();

$('file-input').onchange = e => {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = e => {
    const wb = XLSX.read(e.target.result, { type: 'array' });
    const ws = wb.Sheets[wb.SheetNames[0]];
    const data = XLSX.utils.sheet_to_json(ws);

    tickets = data.map((row, i) => ({
      id: row['Ticket ID'] || i,
      agent: row['Agent'] || 'Unknown',
      subject: row['Subject'] || '',
      status: row['Status'] || 'Open',
      created: new Date(),
      modified: new Date()
    }));

    renderTable();
  };

  reader.readAsArrayBuffer(file);
};

/* ── RENDER TABLE ── */
function renderTable() {
  const tbody = $('ticket-tbody');

  if (!tickets.length) {
    tbody.innerHTML = `<tr><td colspan="8">No data</td></tr>`;
    return;
  }

  tbody.innerHTML = tickets.map(t => `
    <tr>
      <td>#${t.id}</td>
      <td>${t.agent}</td>
      <td>${t.subject}</td>
      <td>${t.status}</td>
      <td>—</td>
      <td>${fmtAgo(t.modified)}</td>
      <td>${fmtDuration(1)}</td>
      <td><button onclick="toggleReview('${t.id}')">Mark</button></td>
    </tr>
  `).join('');
}

/* ── REVIEW ── */
window.toggleReview = id => {
  if (reviewed.has(id)) reviewed.delete(id);
  else reviewed.add(id);
  renderTable();
};
