const $ = (s) => document.querySelector(s);
const player = $('#player');

let queue = [];
let pos = -1;
let seeking = false;
let repeat = 'off';
let currentUser = null;

/* пагинация поиска */
let searchQuery = '';
let searchOffset = 0;
const PAGE = 50;

/* debounce таймеры */
let volSaveTimer = null;
let repeatSaveTimer = null;

/* ---------- auth ---------- */

async function initAuth() {
  try {
    const r = await fetch('/api/me');
    if (!r.ok) { location.href = '/login'; return; }
    currentUser = await r.json();
    $('#username').textContent = currentUser.username;
    repeat = currentUser.repeat || 'off';
    updateRepeatIcon();
    // восстанавливаем громкость
    player.volume = (currentUser.volume || 100) / 100;
    $('#vol').value = player.volume;
    loadHome();
  } catch {
    location.href = '/login';
  }
}

$('#btn-logout').onclick = async () => {
  await fetch('/api/logout', { method: 'POST' });
  location.href = '/login';
};

/* ---------- экраны ---------- */

function show(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  $(viewId).classList.add('active');
}

/* ---------- главная ---------- */

async function loadHome() {
  show('#view-home');
  const [history, playlists] = await Promise.all([
    fetch('/api/history').then(r => r.ok ? r.json() : []),
    fetch('/api/playlists').then(r => r.ok ? r.json() : []),
  ]);
  renderHistory(history);
  renderPlaylists(playlists);
}

function renderHistory(history) {
  const wrap = $('#history-wrap');
  const ul = $('#history');
  ul.innerHTML = '';
  const recent = history.slice(0, 10);
  if (!recent.length) { wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  recent.forEach((t, i) => ul.appendChild(trackRow(t, i, recent)));
}

function renderPlaylists(playlists) {
  const box = $('#playlists');
  box.innerHTML = '';
  if (!playlists.length) {
    box.innerHTML = '<p class="hint">Пока пусто. Создай плейлист — он появится здесь.</p>';
    return;
  }
  playlists.forEach(p => {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="card-icon">🎧</div>
      <div class="card-name">${esc(p.name)}</div>
      <div class="card-meta">${p.count} трек.</div>`;
    card.onclick = () => openPlaylist(p.name);
    box.appendChild(card);
  });
}

/* ---------- списки треков ---------- */

function trackRow(t, index, list) {
  const li = document.createElement('li');
  li.className = 'track';
  li.dataset.url = t.url;
  li.innerHTML = `
    <span class="t-play"></span>
    <span class="t-title">${esc(t.title)}</span>
    <span class="t-artist">${esc(t.uploader)}</span>
    <span class="t-dur">${fmtTime(t.duration)}</span>`;
  li.onclick = () => { queue = list; play(index); };
  return li;
}

function markPlaying(url) {
  document.querySelectorAll('.track').forEach(li =>
    li.classList.toggle('playing', li.dataset.url === url));
}

/* ---------- поиск с пагинацией ---------- */

async function search(append = false) {
  const q = append ? searchQuery : $('#q').value.trim();
  if (!q) return;
  searchQuery = q;

  if (!append) {
    show('#view-results');
    $('#results-title').textContent = '⏳ Ищу…';
    $('#results').innerHTML = '';
    queue = [];
    searchOffset = 0;
  }

  const url = `/api/search?q=${encodeURIComponent(q)}&offset=${searchOffset}&limit=${PAGE}`;
  const tracks = await fetch(url).then(r => r.json());

  const start = queue.length;
  for (const t of tracks) queue.push(t);

  $('#results-title').textContent = `Результаты: ${q} (${queue.length})`;
  const ul = $('#results');
  tracks.forEach((t, i) => ul.appendChild(trackRow(t, start + i, queue)));
  if (!append && !tracks.length) ul.innerHTML = '<li class="hint">Ничего не найдено</li>';

  searchOffset += tracks.length;
  $('#more').hidden = tracks.length < PAGE;
}

/* ---------- плейлист ---------- */

async function openPlaylist(name) {
  show('#view-playlist');
  $('#playlist-title').textContent = name;
  $('#playlist-tracks').innerHTML = '<li class="hint">⏳ Загрузка…</li>';

  const tracks = await fetch('/api/playlists/' + encodeURIComponent(name)).then(r => r.json());
  queue = tracks;

  const ul = $('#playlist-tracks');
  ul.innerHTML = '';
  tracks.forEach((t, i) => ul.appendChild(trackRow(t, i, tracks)));
  if (!tracks.length) ul.innerHTML = '<li class="hint">Плейлист пуст</li>';
  $('#more').hidden = true;
}

/* ---------- плеер ---------- */

async function play(i) {
  const t = queue[i];
  if (!t) return;
  pos = i;
  $('#pb-title').textContent = t.title;
  $('#pb-artist').textContent = t.uploader;
  markPlaying(t.url);

  const { stream_url } = await fetch('/api/track?url=' + encodeURIComponent(t.url)).then(r => r.json());
  if (!stream_url) { $('#pb-title').textContent = '❌ Нет стрима'; return; }

  player.src = '/api/stream?url=' + encodeURIComponent(stream_url);
  player.play().catch(e => console.warn('play error:', e));

  // записываем трек в историю
  fetch('/api/history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(t),
  }).catch(e => console.warn('history error:', e));
}

player.addEventListener('ended', () => {
  if (repeat === 'one') {
    player.currentTime = 0;
    player.play();
  } else if (repeat === 'all') {
    play((pos + 1) % queue.length);
  } else if (pos + 1 < queue.length) {
    play(pos + 1);
  }
});

const btnPlay = $('#btn-play');
function setPlayIcon() { btnPlay.textContent = player.paused ? '▶' : '⏸'; }
btnPlay.onclick = () => { if (player.src) player.paused ? player.play() : player.pause(); };
player.addEventListener('play', setPlayIcon);
player.addEventListener('pause', setPlayIcon);

$('#btn-next').onclick = () => {
  if (pos + 1 < queue.length) play(pos + 1);
  else if (repeat === 'all' && queue.length) play(0);
};
$('#btn-prev').onclick = () => {
  if (player.currentTime > 3) { player.currentTime = 0; return; }
  if (pos - 1 >= 0) play(pos - 1);
};

/* repeat с debounce */
const btnRepeat = $('#btn-repeat');
function updateRepeatIcon() {
  if (repeat === 'off') { btnRepeat.textContent = '🔁'; btnRepeat.classList.remove('active'); }
  else if (repeat === 'all') { btnRepeat.textContent = '🔁'; btnRepeat.classList.add('active'); }
  else { btnRepeat.textContent = '🔂'; btnRepeat.classList.add('active'); }
}
btnRepeat.onclick = () => {
  repeat = repeat === 'off' ? 'all' : (repeat === 'all' ? 'one' : 'off');
  updateRepeatIcon();
  // debounce 300мс (чтобы быстрые клики не спамили)
  clearTimeout(repeatSaveTimer);
  repeatSaveTimer = setTimeout(() => {
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repeat }),
    });
  }, 300);
};

/* прогресс и время */
const seek = $('#seek');
player.addEventListener('loadedmetadata', () => {
  const dur = player.duration || 0;
  seek.max = dur;
  $('#t-total').textContent = fmtTime(Math.round(dur));
  const t = queue[pos];
  if (t && !t.duration && dur) {
    t.duration = Math.round(dur);
    document.querySelectorAll('.track.playing .t-dur')
      .forEach(el => el.textContent = fmtTime(t.duration));
  }
});
player.addEventListener('timeupdate', () => {
  if (!seeking) seek.value = player.currentTime;
  $('#t-cur').textContent = fmtTime(Math.round(player.currentTime));
});
seek.addEventListener('input', () => {
  seeking = true;
  player.currentTime = parseFloat(seek.value);
  $('#t-cur').textContent = fmtTime(Math.round(seek.value));
});
seek.addEventListener('change', () => { seeking = false; });

/* громкость: debounce 1000мс */
const vol = $('#vol');
function saveVolume() {
  clearTimeout(volSaveTimer);
  volSaveTimer = setTimeout(() => {
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ volume: Math.round(player.volume * 100) }),
    });
  }, 1000);
}
function updateMuteIcon() {
  $('#btn-mute').textContent = (player.muted || player.volume === 0) ? '🔇' : '🔊';
}
vol.addEventListener('input', () => {
  player.volume = parseFloat(vol.value);
  player.muted = false;
  updateMuteIcon();
  saveVolume();
});
$('#btn-mute').onclick = () => { player.muted = !player.muted; updateMuteIcon(); };

/* клавиатура */
document.addEventListener('keydown', (e) => {
  const tag = document.activeElement.tagName;
  if (e.code === 'Space' && !['INPUT', 'BUTTON', 'TEXTAREA'].includes(tag)) {
    e.preventDefault();
    if (player.src) player.paused ? player.play() : player.pause();
  }
});

player.addEventListener('error', () => {
  $('#pb-title').textContent = '❌ Ошибка воспроизведения';
  $('#pb-artist').textContent = 'формат не поддерживается';
});

/* ---------- утилиты ---------- */

function fmtTime(sec) {
  if (!sec || !isFinite(sec)) return '--:--';
  sec = Math.round(sec);
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str ?? '';
  return d.innerHTML;
}

/* ---------- привязки ---------- */

$('#logo').onclick = (e) => { e.preventDefault(); loadHome(); };
$('#back').onclick = loadHome;
$('#play-all').onclick = () => { if (queue.length) play(0); };
$('#go').onclick = () => search(false);
$('#more').onclick = () => search(true);
$('#q').addEventListener('keydown', (e) => { if (e.key === 'Enter') search(false); });

initAuth();
