const btnRec = document.getElementById('btn-record');
const btnStop = document.getElementById('btn-stop');
const btnToggle = document.getElementById('btn-toggle');
const statusEl = document.getElementById('status');
const activeEl = document.getElementById('active-label');
const selector = document.getElementById('selector');
const btnToggleVideo = document.getElementById('btn-toggle-video');

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : null });
  return res.json();
}


btnRec.onclick = async () => {
  btnRec.disabled = true; btnStop.disabled = false;
  const r = await post('/record/start');
  statusEl.textContent = `Recording… writing to ${r.file}`;
};

btnStop.onclick = async () => {
  btnStop.disabled = true; btnRec.disabled = false;
  const r = await post('/record/stop');
  statusEl.innerHTML = `Stopped. Saved: <a href="${r.file}">${r.file}</a>`;
};

btnToggle.onclick = async () => {
  const r = await post('/toggle');
  activeEl.textContent = r.active;
  selector.value = r.active;
  // Force refresh MJPEG stream
  const img = document.getElementById('view');
  const url = new URL(img.src, window.location);
  url.searchParams.set('t', Date.now());
  img.src = url.toString();
};

selector.onchange = async (e) => {
  const r = await post('/select', { label: e.target.value });
  activeEl.textContent = r.active;
  const img = document.getElementById('view');
  const url = new URL(img.src, window.location);
  url.searchParams.set('t', Date.now());
  img.src = url.toString();
};
