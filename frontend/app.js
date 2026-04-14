const $ = id => document.getElementById(id);

/* STATE */
let currentUser = '';
let tickets = [];
let reviewed = new Set();

/* LOGIN */
$('login-btn').onclick = () => {
  const email = $('login-email').value.trim().toLowerCase();
  const pass = $('login-pass').value;

  if (!email.endsWith('@adit.com')) {
    $('login-error').textContent = 'Use @adit.com email';
    return;
  }

  if (!pass) {
    $('login-error').textContent = 'Password required';
    return;
  }

  currentUser = email;
  $('login-screen').style.display = 'none';
  $('main-app').style.display = 'flex';
  $('user-badge').textContent = email;
};

/* LOGOUT */
$('logout-btn').onclick = () => {
  currentUser = '';
  tickets = [];
  reviewed.clear();

  $('main-app').style.display = 'none';
  $('login-screen').style.display = 'flex';
};

/* FILE UPLOAD */
$('file-input').onchange = e => processFile(e.target.files[0]);

function processFile(file){
  if(!file) return;

  const reader = new FileReader();

  reader.onload = e => {
    const text = new TextDecoder().decode(e.target.result);
    const rows = text.split('\n').map(r => r.split(','));

    tickets = rows.slice(1).map((r,i)=>({
      id: r[0],
      agent: r[1],
      subject: r[2],
      status: r[3],
      created: new Date(),
      modified: new Date()
    }));

    renderTable();
  };

  reader.readAsArrayBuffer(file);
}

/* TABLE RENDER */
function renderTable(){
  const tbody = $('ticket-tbody');

  if(!tickets.length){
    tbody.innerHTML = `<tr><td colspan="8">No data</td></tr>`;
    return;
  }

  tbody.innerHTML = tickets.map(t => `
    <tr>
      <td>#${t.id}</td>
      <td>${t.agent}</td>
      <td>${t.subject}</td>
      <td>${statusBadge(t.status)}</td>
      <td>-</td>
      <td>-</td>
      <td class="idle-ok">0h</td>
      <td><button onclick="toggleReview('${t.id}')">Mark</button></td>
    </tr>
  `).join('');
}

function statusBadge(s){
  const sl = (s||'').toLowerCase();
  if(sl.includes('open')) return `<span class="badge badge-open">${s}</span>`;
  if(sl.includes('pending')) return `<span class="badge badge-pending">${s}</span>`;
  if(sl.includes('wait')) return `<span class="badge badge-waiting">${s}</span>`;
  return `<span class="badge badge-closed">${s}</span>`;
}

/* REVIEW */
window.toggleReview = id => {
  if(reviewed.has(id)) reviewed.delete(id);
  else reviewed.add(id);

  renderTable();
};
