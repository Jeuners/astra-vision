"use strict";
const $ = (id) => document.getElementById(id);
const labels = {listening: "Ich höre dir zu.", responding: "Einen Moment …", speaking: "Astra spricht. Du kannst jederzeit unterbrechen."};
let peer = null, stream = null, channel = null, pcId = null, heartbeat = null;
let connecting = false, disconnecting = false, muted = false, ready = false;
const output = new Audio();
output.autoplay = true;

function state(value) {
  document.body.dataset.state = value;
  $("status").textContent = muted ? "Mikrofon pausiert" : (labels[value] || value);
}
function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}
function addMessage(event) {
  $("messages").querySelector(".empty")?.remove();
  const article = document.createElement("article");
  article.className = `message ${event.role === "user" ? "user" : "assistant"}`;
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = event.role === "user" ? "Du" : "Astra";
  const text = document.createElement("p");
  text.textContent = event.text;
  article.append(speaker, text);
  if (event.interrupted) {
    const note = document.createElement("small");
    note.textContent = "Unterbrochen";
    article.append(note);
  }
  $("messages").append(article);
  while ($("messages").children.length > 80) $("messages").firstElementChild.remove();
  $("messages").scrollTop = $("messages").scrollHeight;
}
function addToolStart(text) {
  $("messages").querySelector(".empty")?.remove();
  document.getElementById("pending-tool")?.remove();
  const article = document.createElement("article");
  article.className = "message assistant pending-tool";
  article.id = "pending-tool";
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = "Astra";
  const body = document.createElement("p");
  body.className = "pending-text";
  const spinner = document.createElement("i");
  spinner.className = "spinner";
  body.append(spinner, document.createTextNode(` ${text}`));
  article.append(speaker, body);
  $("messages").append(article);
  $("messages").scrollTop = $("messages").scrollHeight;
}
function addToolError(text) {
  const pending = document.getElementById("pending-tool");
  if (pending) {
    pending.removeAttribute("id");
    pending.classList.remove("pending-tool");
    pending.querySelector(".pending-text").textContent = text;
    $("messages").scrollTop = $("messages").scrollHeight;
    return;
  }
  showError(text);
}
function addToolResult(text, items) {
  const pending = document.getElementById("pending-tool");
  const article = pending || document.createElement("article");
  if (pending) {
    pending.removeAttribute("id");
    pending.className = "message assistant";
    pending.replaceChildren();
  } else {
    $("messages").querySelector(".empty")?.remove();
    article.className = "message assistant";
  }
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = "Astra";
  article.append(speaker);
  if (items?.length) {
    const list = document.createElement("ol");
    list.className = "tool-result-list";
    for (const item of items) {
      const li = document.createElement("li");
      if (item.link) {
        const link = document.createElement("a");
        link.href = item.link;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = item.title;
        li.append(link);
      } else {
        li.textContent = item.title;
      }
      if (item.source) {
        const source = document.createElement("small");
        source.textContent = ` (${item.source})`;
        li.append(source);
      }
      list.append(li);
    }
    article.append(list);
  } else {
    const body = document.createElement("p");
    body.className = "tool-result";
    body.textContent = text;
    article.append(body);
  }
  if (!pending) $("messages").append(article);
  $("messages").scrollTop = $("messages").scrollHeight;
}
function addImage(url) {
  const pending = document.getElementById("pending-tool");
  const article = pending || document.createElement("article");
  if (pending) {
    pending.removeAttribute("id");
    pending.className = "message assistant";
    pending.replaceChildren();
  } else {
    $("messages").querySelector(".empty")?.remove();
    article.className = "message assistant";
  }
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = "Astra";
  const img = document.createElement("img");
  img.className = "generated-image";
  img.src = url;
  img.alt = "Von Astra erzeugtes Bild";
  article.append(speaker, img);
  if (!pending) $("messages").append(article);
  $("messages").scrollTop = $("messages").scrollHeight;
}
function addUploadNote(filename) {
  $("messages").querySelector(".empty")?.remove();
  const article = document.createElement("article");
  article.className = "message user";
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = "Du";
  const text = document.createElement("p");
  text.textContent = `Hochgeladen: ${filename}`;
  article.append(speaker, text);
  $("messages").append(article);
  $("messages").scrollTop = $("messages").scrollHeight;
}
function addUploadedImage(dataUrl, filename) {
  $("messages").querySelector(".empty")?.remove();
  const article = document.createElement("article");
  article.className = "message user";
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = "Du";
  const img = document.createElement("img");
  img.className = "generated-image";
  img.src = dataUrl;
  img.alt = filename;
  article.append(speaker, img);
  $("messages").append(article);
  $("messages").scrollTop = $("messages").scrollHeight;
}
function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
function receive(event) {
  let message;
  try { message = JSON.parse(event.data); } catch { return; }
  if (message.type === "state") state(message.state);
  if (message.type === "activity" && !muted) $("status").textContent = message.text;
  if (message.type === "tool_start") addToolStart(message.text);
  if (message.type === "tool_error") addToolError(message.text);
  if (message.type === "tool_result") addToolResult(message.text, message.items);
  if (message.type === "partial") $("partial").textContent = message.text;
  if (message.type === "transcript") addMessage(message);
  if (message.type === "image") addImage(message.url);
  if (message.type === "upload") addUploadNote(message.filename);
  if (message.type === "error") showError(message.message);
  if (message.type === "metric" && message.name === "llm_ms") {
    $("latency").textContent = `Erstes Antwortwort · ${(message.value / 1000).toFixed(2)} s`;
  }
}
async function uploadFile(file) {
  if (!pcId) return;
  if (file.type.startsWith("image/")) {
    try { addUploadedImage(await fileToDataURL(file), file.name); }
    catch { /* preview failed to render; upload still proceeds below */ }
  }
  const body = new FormData();
  body.append("pc_id", pcId);
  body.append("file", file);
  try {
    const response = await fetch("/api/upload", {method: "POST", body, signal: AbortSignal.timeout(30000)});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Upload fehlgeschlagen.");
  } catch (error) {
    showError(error.message || "Upload fehlgeschlagen.");
  }
}
async function request(path, body, timeout = 20000) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body), signal: AbortSignal.timeout(timeout)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Verbindung fehlgeschlagen.");
  return data;
}
async function waitIce(pc) {
  if (pc.iceGatheringState === "complete") return;
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { cleanup(); reject(new Error("Lokaler Verbindungsaufbau dauert zu lange.")); }, 10000);
    function cleanup() { clearTimeout(timeout); pc.removeEventListener("icegatheringstatechange", check); }
    function check() { if (pc.iceGatheringState === "complete") { cleanup(); resolve(); } }
    pc.addEventListener("icegatheringstatechange", check);
    check();
  });
}
async function loadVoices() {
  try {
    const response = await fetch("/api/voices", {signal: AbortSignal.timeout(5000)});
    const data = await response.json();
    const groups = {weiblich: document.createElement("optgroup"), männlich: document.createElement("optgroup")};
    groups.weiblich.label = "Weiblich";
    groups.männlich.label = "Männlich";
    for (const voice of data.voices) {
      const option = document.createElement("option");
      option.value = voice.name;
      option.textContent = voice.display_name;
      groups[voice.gender]?.append(option);
    }
    $("voice").replaceChildren(groups.weiblich, groups.männlich);
    const saved = localStorage.getItem("astra-voice");
    $("voice").value = data.voices.some(v => v.name === saved) ? saved : data.default;
  } catch { showError("Stimmenliste konnte nicht geladen werden."); }
}
$("voice").addEventListener("change", () => {
  try { localStorage.setItem("astra-voice", $("voice").value); } catch { /* ignore */ }
});
async function connect() {
  if (connecting || peer) return;
  connecting = true;
  $("error").hidden = true;
  $("connect").disabled = true;
  $("voice").disabled = true;
  state("Mikrofon wird verbunden …");
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Bitte diese Seite unter http://localhost:7860 öffnen.");
    stream = await navigator.mediaDevices.getUserMedia({audio: {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
    }, video: false});
    const pc = new RTCPeerConnection({iceServers: []});
    peer = pc;
    stream.getTracks().forEach(track => pc.addTrack(track, stream));
    channel = pc.createDataChannel("astra");
    channel.onmessage = receive;
    channel.onopen = () => {
      heartbeat = setInterval(() => { if (channel?.readyState === "open") channel.send("ping"); }, 1000);
    };
    pc.ontrack = (event) => {
      output.srcObject = event.streams[0] || new MediaStream([event.track]);
      output.play().catch(() => showError("Audioausgabe blockiert. Bitte die Audiowiedergabe im Browser erlauben und neu starten."));
    };
    pc.onconnectionstatechange = () => {
      if (peer !== pc) return;
      if (pc.connectionState === "connected") state("listening");
      if (["failed", "disconnected", "closed"].includes(pc.connectionState) && !disconnecting) {
        showError("Verbindung beendet. Du kannst das Gespräch erneut starten.");
        void disconnect();
      }
    };
    await pc.setLocalDescription(await pc.createOffer());
    await waitIce(pc);
    const answer = await request("/api/offer", {sdp: pc.localDescription.sdp, type: "offer", voice: $("voice").value});
    pcId = answer.pc_id;
    await pc.setRemoteDescription({sdp: answer.sdp, type: answer.type});
    $("connect").textContent = "Gespräch beenden";
    $("mute").hidden = false;
    $("attach").hidden = false;
    $("clear").textContent = "Neues Gespräch";
    $("hint").textContent = "Sprich frei. Beim Dazwischenreden hält Astra an.";
  } catch (error) {
    await disconnect();
    const messages = {NotAllowedError: "Mikrofonzugriff nicht erlaubt. Bitte in den Browser-Einstellungen freigeben.",
      NotFoundError: "Kein Mikrofon gefunden. Bitte ein Mikrofon anschließen.",
      NotReadableError: "Das Mikrofon ist gerade nicht verfügbar."};
    showError(messages[error.name] || error.message);
  } finally {
    connecting = false;
    $("connect").disabled = !ready;
  }
}
async function disconnect() {
  if (disconnecting) return;
  disconnecting = true;
  const id = pcId;
  pcId = null;
  clearInterval(heartbeat);
  heartbeat = null;
  stream?.getTracks().forEach(track => track.stop());
  stream = null;
  const oldPeer = peer;
  peer = null;
  channel?.close();
  channel = null;
  oldPeer?.close();
  output.pause();
  output.srcObject = null;
  muted = false;
  $("voice").disabled = !ready;
  $("mute").hidden = true;
  $("mute").setAttribute("aria-pressed", "false");
  $("mute").textContent = "Mikrofon pausieren";
  $("attach").hidden = true;
  $("connect").textContent = "Gespräch starten";
  $("clear").textContent = "Verlauf leeren";
  $("partial").textContent = "";
  $("hint").textContent = "Mikrofon ist aus. Beim nächsten Start beginnt ein neues Gespräch.";
  state("Bereit, wenn du es bist.");
  try { if (id) await request("/api/disconnect", {pc_id: id}, 10000); }
  catch { showError("Der Server hat das Beenden nicht bestätigt. Das Mikrofon ist aus; bitte kurz warten, bevor du neu startest."); }
  finally { disconnecting = false; }
}
$("connect").addEventListener("click", () => { if (peer) void disconnect(); else void connect(); });
$("mute").addEventListener("click", () => {
  muted = !muted;
  stream?.getAudioTracks().forEach(track => { track.enabled = !muted; });
  $("mute").setAttribute("aria-pressed", String(muted));
  $("mute").textContent = muted ? "Mikrofon aktivieren" : "Mikrofon pausieren";
  state("listening");
});
$("attach").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", async () => {
  const file = $("file-input").files[0];
  $("file-input").value = "";
  if (file) await uploadFile(file);
});
$("clear").addEventListener("click", async () => {
  const reconnect = Boolean(peer);
  if (reconnect) await disconnect();
  $("messages").replaceChildren();
  if (reconnect) await connect();
});
window.addEventListener("pagehide", () => {
  stream?.getTracks().forEach(track => track.stop());
  peer?.close();
});
async function poll() {
  try {
    const response = await fetch("/api/status", {signal: AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error("Status nicht verfügbar");
    const status = await response.json();
    ready = status.ready;
    if (!peer && !connecting) {
      $("connect").disabled = !ready;
      $("voice").disabled = !ready;
      state(ready ? "Bereit, wenn du es bist." : status.stage);
      if (status.error) showError(status.error);
    }
  } catch {
    ready = false;
    if (!peer) { $("connect").disabled = true; $("voice").disabled = true; state("Lokaler Server nicht erreichbar."); }
  } finally { setTimeout(poll, ready ? 5000 : 1500); }
}
void poll();
void loadVoices();
