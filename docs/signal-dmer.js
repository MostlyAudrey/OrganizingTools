const nameInput = document.getElementById("user-name");
const openBtn = document.getElementById("open-btn");
const stopBtn = document.getElementById("stop-btn");
const statusEl = document.getElementById("status");
const detailEl = document.getElementById("detail");
const linkWrap = document.getElementById("open-link-wrap");
const openLink = document.getElementById("open-link");

const STORAGE_KEY = "signal-dmer-name";
let pollTimer = null;
let activeId = "";

nameInput.value = localStorage.getItem(STORAGE_KEY) || "";

function setStatus(message, tone) {
  statusEl.textContent = message || "";
  if (tone) {
    statusEl.dataset.tone = tone;
  } else {
    delete statusEl.dataset.tone;
  }
}

function setDetail(text) {
  const value = (text || "").trim();
  detailEl.hidden = !value;
  detailEl.textContent = value;
}

function showLink(url) {
  if (!url) {
    linkWrap.hidden = true;
    openLink.href = "";
    return;
  }
  linkWrap.hidden = false;
  openLink.href = url;
}

function applySession(data) {
  activeId = data.id || activeId;
  const live = data.status === "installing" || data.status === "starting" || data.status === "ready";
  openBtn.disabled = data.status === "installing" || data.status === "starting";
  stopBtn.hidden = !live;
  const tone = data.status === "error" ? "error" : data.status === "ready" || data.status === "ended" ? "ok" : "";
  setStatus(data.message || "", tone);
  setDetail(data.detail || "");
  showLink(data.status === "ready" ? data.url : "");
  const pending = data.status === "installing" || data.status === "starting";
  if (pending && activeId) {
    schedulePoll(activeId);
  } else {
    clearPoll();
  }
}

function clearPoll() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePoll(id) {
  clearPoll();
  pollTimer = setTimeout(() => poll(id), 1500);
}

async function poll(id) {
  try {
    const response = await fetch(`/api/signal-dmer/session/${encodeURIComponent(id)}`, { cache: "no-store" });
    if (!response.ok) {
      setStatus("Lost contact with the organizer server.", "error");
      openBtn.disabled = false;
      return;
    }
    applySession(await response.json());
  } catch (err) {
    setStatus("The organizer server is not running. Start it with python tools/serve_organizer_tools.py and open this page from that server.", "error");
    openBtn.disabled = false;
  }
}

async function openSession() {
  const name = nameInput.value.trim();
  if (!name) {
    setStatus("Enter the name that should own this Signal login.", "error");
    nameInput.focus();
    return;
  }
  localStorage.setItem(STORAGE_KEY, name);
  openBtn.disabled = true;
  stopBtn.hidden = true;
  showLink("");
  setDetail("");
  setStatus("Starting a private environment for this name.");
  try {
    const response = await fetch("/api/signal-dmer/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await response.json();
    if (!response.ok) {
      setStatus(data.message || "Could not start Signal DMER.", "error");
      openBtn.disabled = false;
      return;
    }
    applySession(data);
  } catch (err) {
    openBtn.disabled = false;
    setStatus("The organizer server is not running. Start it with python tools/serve_organizer_tools.py and open this page from that server.", "error");
  }
}

async function stopSession() {
  if (!activeId) {
    return;
  }
  const confirmed = window.confirm(
    "End this session and delete its environment, Signal login, and exported files on this computer?"
  );
  if (!confirmed) {
    return;
  }
  stopBtn.disabled = true;
  openBtn.disabled = true;
  setStatus("Ending the session and deleting its data.");
  try {
    const response = await fetch(`/api/signal-dmer/session/${encodeURIComponent(activeId)}/stop`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      setStatus(data.message || "Could not stop Signal DMER.", "error");
      return;
    }
    applySession(data);
  } catch (err) {
    setStatus("The organizer server is not running.", "error");
  } finally {
    stopBtn.disabled = false;
    if (statusEl.dataset.tone === "error") {
      openBtn.disabled = false;
    }
  }
}

openBtn.addEventListener("click", openSession);
stopBtn.addEventListener("click", stopSession);
nameInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    openSession();
  }
});
