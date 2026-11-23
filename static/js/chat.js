/**
 * Xiaozhi CE — Chat & IoT Sync client
 */

// =========================================================
// CONFIG & DEVICE
// =========================================================
const DEVICE_ID = (() => {
  let id = localStorage.getItem('device_id');
  if (!id) { id = 'web-' + crypto.randomUUID(); localStorage.setItem('device_id', id); }
  return id;
})();
function getSessionId() { const v = localStorage.getItem('session_id'); return v ? parseInt(v, 10) : null; }
function setSessionId(id) { if (id != null) localStorage.setItem('session_id', String(id)); }
function clearSession() { localStorage.removeItem('session_id'); }

// =========================================================
// STATE & DOM
// =========================================================
const State = {
  isProcessing: false,
  isPlayingAudio: false,
  isRecording: false,
  currentBotEl: null,
  currentBotText: '',
  currentUserEl: null,
  streamingTimeout: null,
  reconnectAttempt: 0,
  sessionId: null,
};

const DOM = {
  chatBox: document.getElementById('chatBox'),
  input: document.getElementById('input'),
  sendBtn: document.getElementById('sendBtn'),
  micBtn: document.getElementById('micBtn'),
  statusEl: document.getElementById('status'),
  sessionInfo: document.getElementById('sessionInfo'),
};
const MAX_MESSAGES = 200;

// =========================================================
// UTILS & RENDER
// =========================================================
function scrollBottom() { DOM.chatBox.scrollTop = DOM.chatBox.scrollHeight; }
function setStatus(text, kind = 'online') { DOM.statusEl.textContent = text; DOM.statusEl.className = `status-pill ${kind}`; }

function startStreamingTimeout(ms = 60000) {
  clearStreamingTimeout();
  State.streamingTimeout = setTimeout(() => {
    AudioQueue.reset();
    resetState();
    addMessage('assistant', '❌ Quá thời gian chờ phản hồi.');
  }, ms);
}
function clearStreamingTimeout() { if (State.streamingTimeout) { clearTimeout(State.streamingTimeout); State.streamingTimeout = null; } }

function resetState() {
  State.isProcessing = false;
  State.isPlayingAudio = false;
  const isLinked = !!Auto.linkedId;
  DOM.sendBtn.disabled = isLinked;
  DOM.micBtn.disabled = isLinked;
  if (DOM.input) DOM.input.disabled = isLinked;
  State.currentBotEl = null;
  State.currentBotText = '';
  State.currentUserEl = null;
  clearStreamingTimeout();
  hideTypingIndicator();
  setStatus('Đã kết nối', 'online');
  if (!State.isRecording && !isLinked && DOM.input) DOM.input.focus();
}

function lockInput() {
  State.isProcessing = true;
  DOM.sendBtn.disabled = true;
  DOM.micBtn.disabled = true;
  startStreamingTimeout();
  showTypingIndicator();
}

function addMessage(role, content = '', opts = {}) {
  DOM.chatBox.querySelector('#welcome')?.remove();
  const nodes = DOM.chatBox.querySelectorAll(':scope > .chat-message');
  if (nodes.length >= MAX_MESSAGES) nodes[0].remove();

  const wrapper = document.createElement('div');
  wrapper.className = `chat-message ${role === 'user' ? 'user' : 'assistant'}`;
  if (opts.streaming) wrapper.classList.add('streaming');

  const av = document.createElement('div');
  av.className = 'chat-avatar';
  av.textContent = role === 'user' ? 'B' : '✦';
  wrapper.appendChild(av);

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';

  const contentEl = document.createElement('div');
  contentEl.className = 'content';
  contentEl.innerText = content;

  const meta = document.createElement('div');
  meta.className = 'message-meta';
  const timeStr = opts.time || new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  meta.innerHTML = `<span>${timeStr}</span>` + (opts.source ? `<span class="source-badge">${opts.source}</span>` : '');

  bubble.append(contentEl, meta);
  wrapper.appendChild(bubble);

  DOM.chatBox.appendChild(wrapper);
  scrollBottom();
  return bubble;
}

function appendToolTag(botEl, toolName) {
  if (!botEl) return;
  const el = document.createElement('div');
  el.className = 'tool-tag';
  el.textContent = `🔧 ${toolName}`;
  botEl.appendChild(el);
  scrollBottom();
}

function showTypingIndicator() {
  hideTypingIndicator();
  DOM.chatBox.querySelector('#welcome')?.remove();
  const el = document.createElement('div');
  el.id = 'typingIndicator';
  el.className = 'chat-message assistant typing';
  el.innerHTML = '<div class="chat-avatar">✦</div><div class="message-bubble"><span></span><span></span><span></span></div>';
  DOM.chatBox.appendChild(el);
  scrollBottom();
}
function hideTypingIndicator() { document.getElementById('typingIndicator')?.remove(); }

// =========================================================
// AUDIO (TTS Playback)
// =========================================================
const AudioQueue = {
  player: new Audio(), buffer: new Map(), nextExpected: 1, currentPlaying: false,
  generation: 0, currentUrl: null, waitTimeout: null, isEnded: false,
  push(index, blob) { if (this.buffer.has(index)) return; this.buffer.set(index, blob); this._tryPlay(); },
  markEnded() { this.isEnded = true; this._tryPlay(); },
  _tryPlay() {
    if (this.currentPlaying) return;
    const blob = this.buffer.get(this.nextExpected);
    if (!blob) {
      if (this.isEnded) { this.isEnded = false; State.isPlayingAudio = false; State.isProcessing = false; resetState(); return; }
      if (this.buffer.size > 0 && !this.waitTimeout) {
        this.waitTimeout = setTimeout(() => {
          this.waitTimeout = null;
          if (!this.currentPlaying && this.buffer.size > 0) {
            const keys = Array.from(this.buffer.keys()).sort((a, b) => a - b);
            const next = keys[0];
            if (next > this.nextExpected) {
              for (const k of this.buffer.keys()) if (k < next) this.buffer.delete(k);
              this.nextExpected = next; this._tryPlay();
            }
          }
        }, 3000);
      }
      return;
    }
    if (this.waitTimeout) { clearTimeout(this.waitTimeout); this.waitTimeout = null; }
    this.buffer.delete(this.nextExpected);
    this.currentPlaying = true; State.isPlayingAudio = true;
    const playIndex = this.nextExpected;
    const gen = this.generation;
    const url = URL.createObjectURL(blob);
    this.currentUrl = url; this.player.src = url;
    const finish = () => {
      if (gen !== this.generation) return;
      this.player.onended = null; this.player.onerror = null; this._cleanupUrl();
      this.currentPlaying = false; this.nextExpected = playIndex + 1;
      if (this.isEnded && this.buffer.size === 0) { this.isEnded = false; State.isPlayingAudio = false; State.isProcessing = false; resetState(); }
      else { setTimeout(() => this._tryPlay(), 30); }
    };
    this.player.onended = finish; this.player.onerror = finish; this.player.play().catch(() => finish());
  },
  _cleanupUrl() { if (this.currentUrl) { try { URL.revokeObjectURL(this.currentUrl); } catch {} this.currentUrl = null; } this.player.removeAttribute('src'); try { this.player.load(); } catch {} },
  reset() { this.generation++; this.currentPlaying = false; this.isEnded = false; this.buffer.clear(); this.nextExpected = 1; if (this.waitTimeout) { clearTimeout(this.waitTimeout); this.waitTimeout = null; } try { this.player.pause(); } catch {} this._cleanupUrl(); State.isPlayingAudio = false; },
};

// =========================================================
// MUSIC PLAYER (URL-based)
// =========================================================
const MusicPlayer = {
  current: null, url: null,
  receiveMeta(data) {
    if (State.currentBotEl && !State.currentBotText) {
      State.currentBotEl.closest('.chat-message')?.remove();
      State.currentBotEl = null;
    }

    const bubble = addMessage('assistant', '');
    const contentEl = bubble.querySelector('.content');
    const card = document.createElement('div');
    card.style.cssText = 'display:flex;flex-direction:column;gap:12px;min-width:260px;margin-top:8px;';
    card.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;">
        <div style="width:48px;height:48px;border-radius:8px;background:var(--accent);color:var(--accent-ink);display:grid;place-items:center;font-size:20px;">🎵</div>
        <div style="flex:1;min-width:0;">
          <div style="font-size:14px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(data.label || 'Bài nhạc')}</div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:2px;">YouTube Audio</div>
        </div>
      </div>`;
    const ctl = document.createElement('div');
    ctl.style.cssText = 'display:flex;align-items:center;gap:10px;';
    const audio = document.createElement('audio'); audio.preload = 'auto'; audio.style.display = 'none'; if (data.url) audio.src = data.url;
    const playBtn = document.createElement('button'); playBtn.textContent = '▶'; playBtn.style.cssText = 'width:34px;height:34px;border-radius:50%;background:var(--accent);color:var(--accent-ink);border:0;cursor:pointer;font-size:12px;display:grid;place-items:center;flex-shrink:0;';
    const cur = document.createElement('span'); cur.textContent = '0:00'; cur.style.cssText = 'font-size:11px;color:var(--text-muted);min-width:32px;text-align:center;';
    const bar = document.createElement('div'); bar.style.cssText = 'flex:1;height:4px;border-radius:2px;background:var(--border-strong);position:relative;cursor:pointer;';
    const fill = document.createElement('div'); fill.style.cssText = 'position:absolute;top:0;left:0;bottom:0;background:var(--accent);width:0%;border-radius:2px;'; bar.appendChild(fill);
    const tot = document.createElement('span'); tot.textContent = '0:00'; tot.style.cssText = 'font-size:11px;color:var(--text-muted);min-width:32px;text-align:center;';
    ctl.append(playBtn, cur, bar, tot); card.append(ctl, audio); contentEl.appendChild(card);
    if (this.current) this.current.pause(); this.current = audio;
    const fmt = s => { if (!isFinite(s)) return '0:00'; const m = Math.floor(s / 60), r = Math.floor(s % 60); return `${m}:${String(r).padStart(2, '0')}`; };
    playBtn.onclick = () => { audio.paused ? audio.play().catch(() => {}) : audio.pause(); };
    audio.addEventListener('play', () => playBtn.textContent = '⏸');
    audio.addEventListener('pause', () => playBtn.textContent = '▶');
    audio.addEventListener('loadedmetadata', () => tot.textContent = fmt(audio.duration));
    audio.addEventListener('timeupdate', () => { cur.textContent = fmt(audio.currentTime); if (audio.duration > 0) fill.style.width = (audio.currentTime / audio.duration * 100) + '%'; });
    bar.onclick = e => { const r = bar.getBoundingClientRect(); const pct = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); if (audio.duration > 0) audio.currentTime = pct * audio.duration; };
    audio.load(); audio.play().catch(() => {}); scrollBottom();
  },
  reset() { if (this.current) { try { this.current.pause(); } catch {} this.current = null; } if (this.url) { try { URL.revokeObjectURL(this.url); } catch {} this.url = null; } },
};

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

// =========================================================
// WEBSOCKET
// =========================================================
const WS = window.WS = {
  socket: null, pendingAudioMeta: [],
  connect() {
    if (this.socket && (this.socket.readyState === WebSocket.CONNECTING || this.socket.readyState === WebSocket.OPEN)) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${proto}//${location.host}/ws/chat`);
    this.socket = socket; socket.binaryType = 'arraybuffer';
    socket.onopen = () => {
      if (this.socket !== socket) return;
      State.reconnectAttempt = 0;
      const forceNew = sessionStorage.getItem('force_new_session') === '1';
      if (forceNew) sessionStorage.removeItem('force_new_session');
      socket.send(JSON.stringify({ type: 'hello', device_id: DEVICE_ID, session_id: getSessionId(), force_new: forceNew }));
      Auto.start();
    };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null; this.pendingAudioMeta = []; MusicPlayer.reset(); AudioQueue.reset(); resetState(); Auto.stop();
      setStatus('Mất kết nối, đang thử lại…', 'error');
      State.reconnectAttempt++;
      setTimeout(() => this.connect(), Math.min(5000 * State.reconnectAttempt, 30000));
    };
    socket.onmessage = e => { if (this.socket === socket) this._handleMessage(e); };
  },
  send(data) { if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false; try { this.socket.send(data); return true; } catch { return false; } },
  _handleMessage(event) {
    if (event.data instanceof ArrayBuffer) {
      const idx = this.pendingAudioMeta.shift(); if (idx == null) return;
      const blob = new Blob([event.data], { type: 'audio/wav' });
      AudioQueue.push(idx, blob); startStreamingTimeout(); return;
    }
    let data; try { data = JSON.parse(event.data); } catch { return; }
    this._dispatch(data);
  },
  _dispatch(data) {
    switch (data.type) {
      case 'session': State.sessionId = data.session_id; setSessionId(data.session_id); DOM.sessionInfo.textContent = `Session #${data.session_id} · ${data.is_new ? 'mới' : 'tiếp tục'}`; break;
      case 'status': setStatus(data.text, 'info'); break;
      case 'stt':
        hideTypingIndicator();
        State.currentUserEl = addMessage('user', data.text, { source: Auto.linkedId ? 'ESP32 Mic' : 'Giọng nói' });
        State.currentBotEl = null; State.currentBotText = '';
        startStreamingTimeout();
        break;
      case 'tool': hideTypingIndicator(); appendToolTag(State.currentBotEl, data.name); startStreamingTimeout(); break;
      case 'token': {
        hideTypingIndicator();
        if (!State.currentBotEl) {
          State.currentBotEl = addMessage('assistant', '', { streaming: true, source: Auto.linkedId ? 'ESP32 AI' : '' });
          State.currentBotText = '';
        }
        State.currentBotText += data.content;
        const c = State.currentBotEl.querySelector('.content');
        if (c) { c.textContent = State.currentBotText; scrollBottom(); }
        startStreamingTimeout();
        break;
      }
      case 'audio_meta': this.pendingAudioMeta.push(data.index); startStreamingTimeout(); break;
      case 'music_meta': hideTypingIndicator(); MusicPlayer.receiveMeta(data); setStatus(`Đang chuẩn bị nhạc: ${data.label || ''}`, 'info'); break;
      case 'end':
        document.querySelectorAll('.streaming').forEach(e => e.classList.remove('streaming'));
        State.isProcessing = false;
        AudioQueue.markEnded();
        if (AudioQueue.buffer.size === 0 && !AudioQueue.currentPlaying) resetState();
        break;
      case 'error':
        document.querySelectorAll('.streaming').forEach(e => e.classList.remove('streaming'));
        hideTypingIndicator();
        addMessage('assistant', `❌ ${data.text}`);
        MusicPlayer.reset();
        AudioQueue.reset();
        resetState();
        break;
      case 'link_status':
        if (data.linked) {
          Auto.linkedId = data.esp32_device_id;
          try { localStorage.setItem('esp32_link', data.esp32_device_id); } catch {}
          updateLinkUI(true, data.esp32_device_id);
          // Yêu cầu đồng bộ trạng thái đèn + cảm biến ngay khi vừa kết nối xong
          this.send(JSON.stringify({ type: 'sync_request', esp32_device_id: data.esp32_device_id }));
        } else {
          Auto.linkedId = null;
          try { localStorage.removeItem('esp32_link'); } catch {}
          updateLinkUI(false, null);
        }
        break;
      case 'lamp_state':
      case 'lamp_sync':
      case 'lamp_update':
        if (data.esp32_device_id && Auto.linkedId && data.esp32_device_id !== Auto.linkedId) break;
        window.dispatchEvent(new CustomEvent('lamp_sync', { detail: data }));
        break;
      case 'sensor_update':
        if (data.esp32_device_id && Auto.linkedId && data.esp32_device_id !== Auto.linkedId) break;
        window.dispatchEvent(new CustomEvent('esp32_sensor', { detail: data }));
        break;
    }
  },
};

// =========================================================
// RECORDER (Gửi trực tiếp binary WebM/Opus đúng chuẩn Backend)
// =========================================================
const Recorder = {
  mediaRecorder: null,
  chunks: [],
  stream: null,

  async start() {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const opts = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? { mimeType: 'audio/webm;codecs=opus' }
        : {};

      this.mediaRecorder = new MediaRecorder(this.stream, opts);
      this.chunks = [];

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.chunks.push(e.data);
      };

      this.mediaRecorder.onstop = async () => {
        try { this.stream?.getTracks().forEach(t => t.stop()); } catch {}
        const blob = new Blob(this.chunks, { type: 'audio/webm' });

        if (blob.size < 1000) {
          addMessage('assistant', '🎤 Đoạn ghi quá ngắn, bạn nói lâu hơn một chút nhé.');
          resetState();
          return;
        }

        State.currentBotEl = null;
        State.currentBotText = '';
        AudioQueue.reset();
        lockInput();
        setStatus('Đang nhận dạng giọng nói…', 'info');

        const arrayBuffer = await blob.arrayBuffer();
        if (!WS.send(arrayBuffer)) {
          addMessage('assistant', '❌ Mất kết nối, vui lòng thử lại.');
          resetState();
          return;
        }
      };

      this.mediaRecorder.start();
      State.isRecording = true;
      DOM.micBtn.classList.add('recording');
      setStatus('Đang nghe…', 'recording');
    } catch (e) {
      console.error('❌ Lỗi ghi âm:', e);
      alert(e.name === 'NotAllowedError' ? 'Bạn chưa cấp quyền mic.' : `Lỗi mic: ${e.message}`);
      resetState();
    }
  },

  stop() {
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    State.isRecording = false;
    DOM.micBtn.classList.remove('recording');
  },
};

// =========================================================
// ACTIONS & AUTO LINK
// =========================================================
function send(overrideText = null) {
  if (Auto.linkedId) return;
  const text = (overrideText !== null ? overrideText : DOM.input.value).trim();
  if (!text || State.isProcessing) return;
  MusicPlayer.reset(); AudioQueue.reset();
  State.currentUserEl = addMessage('user', text, { source: 'Web' });
  State.currentBotEl = null; State.currentBotText = ''; lockInput();
  if (!WS.send(JSON.stringify({ type: 'message', text }))) { addMessage('assistant', '❌ Mất kết nối, vui lòng thử lại.'); resetState(); return; }
  if (overrideText === null) { DOM.input.value = ''; DOM.input.focus(); }
}

function toggleRecording() {
  if (State.isRecording) { Recorder.stop(); return; }
  if (State.isProcessing) return;
  AudioQueue.reset(); State.currentUserEl = null; Recorder.start();
}

const Auto = (() => {
  const K_LINK = 'esp32_link'; const K_ENABLED = 'esp32_auto_enabled'; const K_COOL = 'esp32_auto_cooldown';
  const POLL = 3000, COOL_MS = 5 * 60 * 1000;
  const A = {
    timer: null, busy: false, linkedId: null,
    isEnabled() { try { if (localStorage.getItem(K_ENABLED) === '0') return false; const cd = parseInt(localStorage.getItem(K_COOL) || '0', 10); return !(cd && Date.now() < cd); } catch { return true; } },
    setEnabled(v) { try { localStorage.setItem(K_ENABLED, v ? '1' : '0'); localStorage.removeItem(K_COOL); } catch {} this.updatePill(); this.refreshBtn(); },
    cooldown() { try { localStorage.setItem(K_COOL, String(Date.now() + COOL_MS)); } catch {} this.updatePill(); this.refreshBtn(); },
    start() { this.stop(); this.timer = setInterval(() => this._tick(), POLL); setTimeout(() => this._tick(), 800); },
    stop() { if (this.timer) { clearInterval(this.timer); this.timer = null; } },
    async _tick() {
      if (this.busy || !WS.socket || WS.socket.readyState !== WebSocket.OPEN) return;
      if (!this.isEnabled()) return;
      this.busy = true;
      try {
        const r = await fetch('/api/devices/active?capability=chat', { cache: 'no-store' });
        const { devices = [] } = await r.json();
        if (this.linkedId) {
          if (!devices.includes(this.linkedId)) { this.linkedId = null; try { localStorage.removeItem(K_LINK); } catch {} updateLinkUI(false, null); if (devices.length === 1) this.sendLink(devices[0]); }
          return;
        }
        if (!devices.length) return;
        let saved = null; try { saved = localStorage.getItem(K_LINK); } catch {}
        if (saved && devices.includes(saved)) return this.sendLink(saved);
        if (devices.length === 1) return this.sendLink(devices[0]);
        if (!saved) this.updatePill('Nhiều ESP32 — chọn thủ công');
      } catch {} finally { this.busy = false; }
    },
    sendLink(id) { if (WS.send(JSON.stringify({ type: 'link', esp32_device_id: id }))) console.log('Auto-link →', id); },
    updatePill(text) { const pill = document.getElementById('linkPill'); if (!pill || this.linkedId) return; if (text) { pill.textContent = text; pill.className = 'status-pill warning'; pill.style.display = ''; } else if (this.isEnabled()) { pill.textContent = 'Đang tìm ESP32…'; pill.className = 'status-pill info'; pill.style.display = ''; } else pill.style.display = 'none'; },
    refreshBtn() { const btn = document.getElementById('autoLinkBtn'); if (!btn) return; const on = this.isEnabled(); btn.textContent = on ? 'Auto ✓' : 'Auto ✗'; btn.title = on ? 'Tắt tự động' : 'Bật tự động'; },
  };
  return A;
})();
window.Auto = Auto;

function updateLinkUI(linked, id) {
  const pill = document.getElementById('linkPill');
  const btn = document.getElementById('linkBtn');
  const mic = document.getElementById('micBtn');
  const nw = document.getElementById('newSessionBtn');
  const chips = document.getElementById('chips');
  if (!pill || !btn) return;

  if (linked && id) {
    pill.textContent = '🔗 ' + String(id).slice(0, 10) + '…';
    pill.className = 'status-pill online';
    pill.style.display = '';
    btn.textContent = 'Ngắt kết nối';
    btn.onclick = () => {
      WS.send(JSON.stringify({ type: 'unlink' }));
      Auto.cooldown();
      Auto.linkedId = null;
      try { localStorage.removeItem('esp32_link'); } catch {}
      updateLinkUI(false, null);
    };
    if (mic) mic.disabled = true;
    if (DOM.input) {
      DOM.input.disabled = true;
      DOM.input.value = '';
      DOM.input.placeholder = 'Đang đồng bộ hội thoại với ESP32 (Chế độ chỉ xem)...';
    }
    if (DOM.sendBtn) DOM.sendBtn.disabled = true;
    if (chips) chips.style.display = 'none';
    if (nw) nw.style.display = 'none';
  } else {
    pill.style.display = 'none';
    btn.textContent = 'Link ESP32';
    btn.onclick = openLinkDialog;
    if (mic) mic.disabled = false;
    if (DOM.input) {
      DOM.input.disabled = false;
      DOM.input.placeholder = 'Nhập tin nhắn hoặc lệnh...';
    }
    if (DOM.sendBtn) DOM.sendBtn.disabled = false;
    if (chips) chips.style.display = 'flex';
    if (nw) nw.style.display = '';
    if (Auto.isEnabled()) Auto.updatePill();
  }
  Auto.refreshBtn();
}

async function openLinkDialog() {
  try {
    const r = await fetch('/api/devices/active?capability=chat', { cache: 'no-store' });
    const { devices = [] } = await r.json();
    const sel = document.getElementById('linkDeviceSelect'); if (!sel) return;
    sel.innerHTML = ''; if (!devices.length) sel.innerHTML = "<option value=''>(Không có ESP32 online)</option>";
    else devices.forEach(d => { const o = document.createElement('option'); o.value = d; o.textContent = d; sel.appendChild(o); });
    document.getElementById('linkDialog')?.showModal();
  } catch { alert('Không tải được danh sách ESP32'); }
}

// =========================================================
// INIT & LOAD HISTORY
// =========================================================
async function loadHistory() {
  const sessionId = getSessionId();
  if (!sessionId) return;
  try {
    const res = await fetch(`/api/sessions/${sessionId}/messages`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.messages && data.messages.length > 0) {
      DOM.chatBox.querySelector('#welcome')?.remove();
      data.messages.forEach(msg => {
        if (msg.role === 'user' || msg.role === 'assistant') {
          addMessage(msg.role, msg.content);
        }
      });
      scrollBottom();
    }
  } catch (e) { console.warn('Không tải được lịch sử chat:', e); }
}

function init() {
  DOM.sendBtn.addEventListener('click', () => send());
  DOM.input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  DOM.micBtn.addEventListener('click', toggleRecording);

  document.querySelectorAll('#chips .chip[data-cmd]').forEach(btn => {
    btn.addEventListener('click', () => send(btn.dataset.cmd));
  });

  document.getElementById('newSessionBtn')?.addEventListener('click', () => {
    sessionStorage.setItem('force_new_session', '1');
    clearSession();
    location.reload();
  });

  document.getElementById('autoLinkBtn')?.addEventListener('click', () => {
    Auto.setEnabled(!Auto.isEnabled());
    updateLinkUI(!!Auto.linkedId, Auto.linkedId);
  });

  document.getElementById('linkForm')?.addEventListener('submit', e => {
    e.preventDefault();
    const id = document.getElementById('linkDeviceSelect')?.value;
    if (id) WS.send(JSON.stringify({ type: 'link', esp32_device_id: id }));
    document.getElementById('linkDialog')?.close();
  });

  (async () => {
    try { Auto.linkedId = localStorage.getItem('esp32_link'); } catch {}
    if (Auto.linkedId) {
      try {
        const r = await fetch('/api/devices/active?capability=chat', { cache: 'no-store' });
        const { devices = [] } = await r.json();
        if (!devices.includes(Auto.linkedId)) {
          Auto.linkedId = null;
          try { localStorage.removeItem('esp32_link'); } catch {}
        }
      } catch {}
    }
    updateLinkUI(!!Auto.linkedId, Auto.linkedId);
  })();

  loadHistory().then(() => {
    WS.connect();
    if (!Auto.linkedId && DOM.input) DOM.input.focus();
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
} 