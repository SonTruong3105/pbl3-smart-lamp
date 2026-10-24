/**
 * Xiaozhi CE — Chat Client với audio buffer theo index.
 */

// =====================================================
// DEVICE + SESSION ID
// =====================================================

function getOrCreateDeviceId() {
  let id = localStorage.getItem("device_id");
  if (!id) {
    id = "web-" + crypto.randomUUID();
    localStorage.setItem("device_id", id);
  }
  return id;
}

function getSessionId() {
  const v = localStorage.getItem("session_id");
  return v ? parseInt(v) : null;
}

function setSessionId(id) {
  if (id != null) localStorage.setItem("session_id", id);
}

function clearSession() {
  localStorage.removeItem("session_id");
}

const DEVICE_ID = getOrCreateDeviceId();

// =====================================================
// STATE
// =====================================================

const State = {
  isProcessing: false,
  isPlayingAudio: false,
  isRecording: false,
  currentBotEl: null,
  currentBotText: "",
  currentUserEl: null,
  streamingTimeout: null,
  reconnectAttempt: 0,
  sessionId: null,
};

// =====================================================
// DOM
// =====================================================

const DOM = {
  chatBox: document.getElementById("chatBox"),
  input: document.getElementById("input"),
  sendBtn: document.getElementById("sendBtn"),
  micBtn: document.getElementById("micBtn"),
  statusEl: document.getElementById("status"),
  sessionInfo: document.getElementById("sessionInfo"),
};

const MAX_MESSAGES = 200;

// =====================================================
// UTILS
// =====================================================

function scrollBottom() {
  DOM.chatBox.scrollTop = DOM.chatBox.scrollHeight;
}

function setStatus(text, color = "green") {
  const colors = {
    green: "bg-green-100 text-green-800",
    red: "bg-red-100 text-red-800",
    blue: "bg-blue-100 text-blue-800",
    yellow: "bg-yellow-100 text-yellow-800",
    slate: "bg-slate-100 text-slate-800",
  };
  DOM.statusEl.textContent = text;
  DOM.statusEl.className = `text-xs px-2 py-1 rounded ${colors[color] || colors.slate}`;
}

function startStreamingTimeout(ms = 60000) {
  clearStreamingTimeout();
  State.streamingTimeout = setTimeout(() => {
    console.warn("⏱️ Force reset state sau timeout");
    resetState();
  }, ms);
}

function clearStreamingTimeout() {
  if (State.streamingTimeout) {
    clearTimeout(State.streamingTimeout);
    State.streamingTimeout = null;
  }
}

function resetState() {
  State.isProcessing = false;
  DOM.sendBtn.disabled = false;
  DOM.micBtn.disabled = false;
  State.currentBotEl = null;
  State.currentBotText = "";
  State.currentUserEl = null;
  setStatus("Đã kết nối", "green");
  clearStreamingTimeout();
  if (!State.isRecording) DOM.input.focus();
}

function lockInput() {
  State.isProcessing = true;
  DOM.sendBtn.disabled = true;
  DOM.micBtn.disabled = true;
  startStreamingTimeout();
}

// =====================================================
// UI
// =====================================================

function addMessage(role, content) {
  const welcome = DOM.chatBox.querySelector(".text-center");
  if (welcome) welcome.remove();

  const messages = DOM.chatBox.querySelectorAll(":scope > div.flex");
  if (messages.length >= MAX_MESSAGES) messages[0].remove();

  const wrapper = document.createElement("div");
  wrapper.className = `flex ${role === "user" ? "justify-end" : "justify-start"}`;

  const bubble = document.createElement("div");
  bubble.className = role === "user"
    ? "bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-2 max-w-[75%] shadow"
    : "bg-white text-slate-800 rounded-2xl rounded-tl-sm px-4 py-2 max-w-[75%] shadow";

  const label = document.createElement("div");
  label.className = "text-xs opacity-60 mb-1";
  label.innerText = role === "user" ? "Bạn" : "Trợ lý";

  const contentEl = document.createElement("div");
  contentEl.className = "content whitespace-pre-wrap";
  contentEl.innerText = content;

  bubble.appendChild(label);
  bubble.appendChild(contentEl);
  wrapper.appendChild(bubble);
  DOM.chatBox.appendChild(wrapper);
  scrollBottom();
  return bubble;
}

function appendToolTag(botEl, toolName) {
  if (!botEl) return;
  const toolEl = document.createElement("div");
  toolEl.className = "text-xs text-slate-400 italic mt-1";
  toolEl.innerText = `🔧 ${toolName}`;
  botEl.appendChild(toolEl);
  scrollBottom();
}

// =====================================================
// AUDIO QUEUE — Indexed buffer
// =====================================================

const AudioQueue = {
  player: new Audio(),
  buffer: new Map(),         // index → blob
  nextExpected: 1,           // index tiếp theo cần phát
  currentPlaying: false,

  /**
   * Push audio với index cụ thể.
   * Nếu đúng thứ tự → phát ngay.
   * Nếu chưa đến lượt → buffer chờ.
   */
  push(index, blob) {
    this.buffer.set(index, blob);
    console.log(`🔊 Audio #${index} buffered (total: ${this.buffer.size}, next: ${this.nextExpected})`);
    this.playNext();
  },

  /**
   * Phát audio có index = nextExpected nếu có sẵn.
   */
  playNext() {
    if (this.currentPlaying) return;

    const blob = this.buffer.get(this.nextExpected);
    if (!blob) {
      // Chưa có audio cho index này → chờ
      console.log(`⏳ Chờ audio #${this.nextExpected}...`);
      return;
    }

    // Có sẵn → phát
    this.buffer.delete(this.nextExpected);
    this.currentPlaying = true;

    const url = URL.createObjectURL(blob);
    this.player.src = url;

    console.log(`▶️ Phát audio #${this.nextExpected}`);

    const finish = () => {
      this.player.onended = null;
      this.player.onerror = null;
      try { URL.revokeObjectURL(url); } catch (e) {}
      this.currentPlaying = false;
      this.nextExpected += 1;
      // Đệ quy phát câu tiếp (nếu có sẵn trong buffer)
      setTimeout(() => this.playNext(), 50);
    };

    this.player.onended = finish;
    this.player.onerror = (e) => {
      console.error("❌ Audio error:", e);
      finish();
    };

    this.player.play().catch((e) => {
      console.error("❌ Play failed:", e);
      finish();
    });
  },

  /**
   * Reset khi bắt đầu cuộc hội thoại mới.
   */
  reset() {
    try { this.player.pause(); } catch (e) {}
    this.buffer.clear();
    this.nextExpected = 1;
    this.currentPlaying = false;
  },

  stop() {
    try { this.player.pause(); } catch (e) {}
    this.buffer.clear();
    this.currentPlaying = false;
  },
};

// =====================================================
// WEBSOCKET
// =====================================================

const WS = {
  socket: null,

  connect() {
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.CONNECTING ||
        this.socket.readyState === WebSocket.OPEN)
    ) {
      return;
    }

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/ws/chat`;
    const socket = new WebSocket(url);
    this.socket = socket;
    socket.binaryType = "arraybuffer";

    socket.onopen = () => {
      if (this.socket !== socket) return;
      State.reconnectAttempt = 0;
      console.log(`✅ WS connected | device=${DEVICE_ID}`);

      socket.send(JSON.stringify({
        type: "hello",
        device_id: DEVICE_ID,
        session_id: getSessionId(),
      }));
    };

    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      setStatus("Mất kết nối, đang thử lại...", "red");
      State.reconnectAttempt++;
      const delay = Math.min(2000 * State.reconnectAttempt, 10000);
      setTimeout(() => this.connect(), delay);
    };

    socket.onerror = (e) => {
      if (this.socket === socket) console.error("❌ WS error:", e);
    };
    socket.onmessage = (e) => {
      if (this.socket === socket) this._handleMessage(e);
    };
  },

  send(data) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      console.warn("⚠️ WS chưa sẵn sàng");
      return false;
    }
    this.socket.send(data);
    return true;
  },

  // ⭐ State cho pending audio — biết binary tiếp theo thuộc index nào
  pendingAudioIndex: null,

  _handleMessage(event) {
    // === Binary = audio data ===
    if (event.data instanceof ArrayBuffer) {
      const idx = this.pendingAudioIndex;
      if (idx === null) {
        console.warn("⚠️ Nhận audio binary nhưng không có metadata");
        return;
      }
      const blob = new Blob([event.data], { type: "audio/wav" });
      AudioQueue.push(idx, blob);
      this.pendingAudioIndex = null;
      return;
    }

    // === JSON ===
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      console.error("❌ JSON parse:", e);
      return;
    }

    this._dispatch(data);
  },

  _dispatch(data) {
    switch (data.type) {
      case "session":
        State.sessionId = data.session_id;
        setSessionId(data.session_id);
        DOM.sessionInfo.textContent =
          `Session #${data.session_id} · ${data.is_new ? "mới" : "tiếp tục"}`;
        break;

      case "status":
        setStatus(data.text, "blue");
        break;

      case "stt":
        State.currentUserEl = addMessage("user", data.text);
        State.currentBotEl = null;
        State.currentBotText = "";
        break;

      case "tool":
        appendToolTag(State.currentBotEl, data.name);
        break;

      case "token":
        if (!State.currentBotEl) {
          State.currentBotEl = addMessage("assistant", "");
          State.currentBotText = "";
        }
        State.currentBotText += data.content;
        const contentEl = State.currentBotEl.querySelector(".content");
        if (contentEl) {
          contentEl.textContent = State.currentBotText;
          scrollBottom();
        }
        break;

      // ⭐ Metadata audio — biết binary tiếp theo thuộc index nào
      case "audio_meta":
        this.pendingAudioIndex = data.index;
        break;

      case "end":
        resetState();
        break;

      case "error":
        addMessage("assistant", `❌ ${data.text}`);
        resetState();
        break;

      default:
        console.warn("⚠️ Message không rõ type:", data.type);
    }
  },
};

// =====================================================
// RECORDER
// =====================================================

const Recorder = {
  mediaRecorder: null,
  chunks: [],
  stream: null,

  async start() {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(this.stream, {
        mimeType: "audio/webm;codecs=opus",
      });
      this.chunks = [];

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.chunks.push(e.data);
      };

      this.mediaRecorder.onstop = async () => {
        this.stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(this.chunks, { type: "audio/webm" });

        if (blob.size < 1000) {
          console.warn("Audio quá ngắn");
          resetState();
          return;
        }

        State.currentBotEl = null;
        State.currentBotText = "";
        AudioQueue.reset();         // ⭐ Reset buffer cho câu mới
        lockInput();

        const arrayBuffer = await blob.arrayBuffer();
        if (!WS.send(arrayBuffer)) {
          addMessage("assistant", "❌ Mất kết nối, vui lòng thử lại");
          resetState();
          return;
        }

        setStatus("Đang xử lý...", "yellow");
      };

      this.mediaRecorder.start();
      State.isRecording = true;
      DOM.micBtn.textContent = "⏹ Dừng";
      DOM.micBtn.classList.add("bg-red-600");
      DOM.micBtn.classList.remove("bg-slate-600");
      setStatus("Đang ghi âm...", "red");
    } catch (e) {
      console.error("❌ Lỗi ghi âm:", e);
      if (e.name === "NotAllowedError") {
        alert("Bạn chưa cấp quyền mic.");
      } else {
        alert(`Lỗi mic: ${e.message}`);
      }
      resetState();
    }
  },

  stop() {
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
    State.isRecording = false;
    DOM.micBtn.textContent = "🎤 Nói";
    DOM.micBtn.classList.remove("bg-red-600");
    DOM.micBtn.classList.add("bg-slate-600");
  },
};

// =====================================================
// ACTIONS
// =====================================================

function send() {
  const text = DOM.input.value.trim();
  if (!text || State.isProcessing) return;

  // Reset audio buffer cho câu mới
  AudioQueue.reset();

  State.currentUserEl = addMessage("user", text);
  State.currentBotEl = null;
  State.currentBotText = "";

  lockInput();

  const ok = WS.send(JSON.stringify({ type: "message", text }));
  if (!ok) {
    addMessage("assistant", "❌ Mất kết nối, vui lòng thử lại");
    resetState();
    return;
  }

  DOM.input.value = "";
  DOM.input.focus();
}

function toggleRecording() {
  if (State.isRecording) {
    Recorder.stop();
    return;
  }
  if (State.isProcessing) return;

  AudioQueue.reset();
  State.currentUserEl = null;
  Recorder.start();
}

// =====================================================
// INIT
// =====================================================

DOM.sendBtn.addEventListener("click", send);
DOM.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});
DOM.micBtn.addEventListener("click", toggleRecording);

document.getElementById("newSessionBtn")?.addEventListener("click", () => {
  clearSession();
  location.reload();
});

WS.connect();
DOM.input.focus();