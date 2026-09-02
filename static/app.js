const chat = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const convList = document.getElementById("conv-list");
const pinList = document.getElementById("pin-list");
const newConvBtn = document.getElementById("new-conv");
const tabConv = document.getElementById("tab-conv");
const tabPin = document.getElementById("tab-pin");
const sidebar = document.getElementById("sidebar");
const overlay = document.getElementById("overlay");
const menuBtn = document.getElementById("menu-btn");

const GREETING = "Merhaba. Ben Mısra. Ne üzerinde çalışıyorsun?";

let currentId = null; // açık konuşmanın id'si
let sending = false;

// Oturum düşerse (401) giriş sayfasına dön.
async function apiFetch(url, opts) {
  const res = await fetch(url, opts);
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Oturum sona erdi");
  }
  return res;
}

// --------------------------------------------------------------------------- //
// Metin render (güvenli): [etiket](/pdf/... | http...) → tıklanabilir link
// --------------------------------------------------------------------------- //
function renderText(el, text) {
  const esc = (s) =>
    s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  el.innerHTML = esc(text).replace(
    /\[([^\]]+)\]\((\/pdf\/[A-Za-z0-9_-]+|https?:\/\/[^\s)]+)\)/g,
    (_, label, url) => `<a href="${url}" target="_blank" rel="noopener">${label}</a>`,
  );
}

// --------------------------------------------------------------------------- //
// Mesaj balonları
// --------------------------------------------------------------------------- //
function addBubble(role, text = "") {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const content = document.createElement("div");
  content.className = "content";
  renderText(content, text);
  bubble.appendChild(content);

  const actions = document.createElement("div");
  actions.className = "bubble-actions";

  const pdfBtn = document.createElement("button");
  pdfBtn.type = "button";
  pdfBtn.className = "act";
  pdfBtn.title = "PDF yap";
  pdfBtn.textContent = "📄";
  pdfBtn.addEventListener("click", () =>
    makePdf(content.textContent, pdfBtn, bubble),
  );

  const pinBtn = document.createElement("button");
  pinBtn.type = "button";
  pinBtn.className = "act";
  pinBtn.title = "Panoya ekle";
  pinBtn.textContent = "📌";
  pinBtn.addEventListener("click", () => pinText(content.textContent, pinBtn));

  actions.append(pdfBtn, pinBtn);
  bubble.appendChild(actions);

  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return content; // çağıran taraf bunu günceller
}

function renderMessages(messages) {
  chat.innerHTML = "";
  if (!messages.length) {
    addBubble("assistant", GREETING);
    return;
  }
  for (const m of messages) addBubble(m.role, m.content);
}

// --------------------------------------------------------------------------- //
// PDF ve pano işlemleri (buton yolu)
// --------------------------------------------------------------------------- //
function attachPdfLink(container, url, filename) {
  let link = container.querySelector(".pdf-link");
  if (!link) {
    link = document.createElement("a");
    link.className = "pdf-link";
    container.appendChild(link);
  }
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "📄 " + filename;
}

async function makePdf(text, btn, container) {
  text = (text || "").trim();
  if (!text) return;
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "…";
  try {
    const res = await apiFetch("/api/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const { url, filename } = await res.json();
    attachPdfLink(container, url, filename);
  } catch (_) {
    btn.title = "PDF oluşturulamadı, tekrar dene";
  } finally {
    btn.textContent = old;
    btn.disabled = false;
  }
}

async function pinText(text, btn) {
  text = (text || "").trim();
  if (!text) return;
  btn.disabled = true;
  try {
    const res = await apiFetch("/api/pins", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text }),
    });
    if (res.ok) {
      btn.textContent = "✓";
      setTimeout(() => (btn.textContent = "📌"), 1500);
      loadPins();
    }
  } finally {
    btn.disabled = false;
  }
}

// --------------------------------------------------------------------------- //
// Kenar panel: sekmeler
// --------------------------------------------------------------------------- //
function switchTab(which) {
  const pin = which === "pin";
  tabPin.classList.toggle("active", pin);
  tabConv.classList.toggle("active", !pin);
  convList.hidden = pin;
  newConvBtn.hidden = pin;
  pinList.hidden = !pin;
  if (pin) loadPins();
}
tabConv.addEventListener("click", () => switchTab("conv"));
tabPin.addEventListener("click", () => switchTab("pin"));

// --------------------------------------------------------------------------- //
// Konuşma listesi
// --------------------------------------------------------------------------- //
async function loadConversations() {
  const res = await apiFetch("/api/conversations");
  const items = await res.json();
  convList.innerHTML = "";
  for (const c of items) {
    const li = document.createElement("li");
    li.className = "conv-item" + (c.id === currentId ? " active" : "");
    li.dataset.id = c.id;

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = c.title || "Yeni konuşma";
    li.appendChild(title);

    const del = document.createElement("button");
    del.className = "del";
    del.type = "button";
    del.textContent = "×";
    del.title = "Konuşmayı sil";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteConversation(c.id);
    });
    li.appendChild(del);

    li.addEventListener("click", () => openConversation(c.id));
    convList.appendChild(li);
  }
  return items;
}

async function openConversation(id) {
  const res = await apiFetch(`/api/conversations/${id}/messages`);
  if (!res.ok) return;
  const data = await res.json();
  currentId = data.id;
  renderMessages(data.messages);
  for (const li of convList.children) {
    li.classList.toggle("active", Number(li.dataset.id) === currentId);
  }
  closeSidebar();
  input.focus();
}

async function newConversation() {
  const res = await apiFetch("/api/conversations", { method: "POST" });
  const c = await res.json();
  currentId = c.id;
  await loadConversations();
  renderMessages([]);
  closeSidebar();
  input.focus();
}

async function deleteConversation(id) {
  await apiFetch(`/api/conversations/${id}`, { method: "DELETE" });
  if (id === currentId) currentId = null;
  const items = await loadConversations();
  if (currentId === null) {
    if (items.length) await openConversation(items[0].id);
    else await newConversation();
  }
}

// --------------------------------------------------------------------------- //
// Pano listesi
// --------------------------------------------------------------------------- //
async function loadPins() {
  const res = await apiFetch("/api/pins");
  const items = await res.json();
  pinList.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "pin-empty";
    li.textContent = "Pano boş. Bir mesajın yanındaki 📌 ile ekleyebilirsin.";
    pinList.appendChild(li);
    return;
  }
  for (const p of items) {
    const li = document.createElement("li");
    li.className = "pin-item";

    const txt = document.createElement("div");
    txt.className = "pin-text";
    txt.textContent = p.content;
    li.appendChild(txt);

    const row = document.createElement("div");
    row.className = "pin-actions";

    const pdfB = document.createElement("button");
    pdfB.type = "button";
    pdfB.className = "act";
    pdfB.title = "PDF yap";
    pdfB.textContent = "📄";
    pdfB.addEventListener("click", () => makePdf(p.content, pdfB, li));

    const delB = document.createElement("button");
    delB.type = "button";
    delB.className = "act";
    delB.title = "Panodan kaldır";
    delB.textContent = "×";
    delB.addEventListener("click", async () => {
      await apiFetch(`/api/pins/${p.id}`, { method: "DELETE" });
      loadPins();
    });

    row.append(pdfB, delB);
    li.appendChild(row);
    pinList.appendChild(li);
  }
}

// --------------------------------------------------------------------------- //
// Panel aç/kapa (dar ekran)
// --------------------------------------------------------------------------- //
function openSidebar() {
  sidebar.classList.add("open");
  overlay.hidden = false;
}
function closeSidebar() {
  sidebar.classList.remove("open");
  overlay.hidden = true;
}
menuBtn.addEventListener("click", openSidebar);
overlay.addEventListener("click", closeSidebar);
newConvBtn.addEventListener("click", newConversation);

// --------------------------------------------------------------------------- //
// Yazma alanı
// --------------------------------------------------------------------------- //
function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}
input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (e) => {
  // Enter = yeni satır (varsayılan). Göndermek için Ctrl+Enter (veya ⌘+Enter).
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    form.requestSubmit();
  }
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || sending || currentId === null) return;

  sending = true;
  input.value = "";
  autoGrow();
  input.disabled = sendBtn.disabled = true;

  // Karşılama balonu varsa (boş konuşma) ilk mesajda temizle
  const first = chat.querySelector(".msg.assistant .content");
  if (chat.children.length === 1 && first && first.textContent === GREETING) {
    chat.innerHTML = "";
  }

  addBubble("user", text);
  const reply = addBubble("assistant");
  reply.classList.add("pending");
  let acc = "";

  try {
    const res = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: currentId, content: text }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      for (const part of parts) {
        const line = part.replace(/^data: /, "").trim();
        if (!line) continue;
        const payload = JSON.parse(line);

        if (payload.delta) {
          acc += payload.delta;
          renderText(reply, acc);
          chat.scrollTop = chat.scrollHeight;
        } else if (payload.error) {
          throw new Error(payload.error);
        }
      }
    }
  } catch (err) {
    reply.classList.add("error");
    renderText(reply, acc + `\n\n[Hata: ${err.message}]`);
  } finally {
    reply.classList.remove("pending");
    input.disabled = sendBtn.disabled = false;
    sending = false;
    input.focus();
    loadConversations(); // başlık + sıralama güncellensin
  }
});

// --------------------------------------------------------------------------- //
// Geri bildirim
// --------------------------------------------------------------------------- //
const feedbackBtn = document.getElementById("feedback-btn");
const fbDialog = document.getElementById("feedback-dialog");
const fbForm = document.getElementById("feedback-form");
const fbKind = document.getElementById("fb-kind");
const fbMessage = document.getElementById("fb-message");
const fbStatus = document.getElementById("fb-status");
const fbCancel = document.getElementById("fb-cancel");
const fbSend = document.getElementById("fb-send");

feedbackBtn.addEventListener("click", () => {
  fbForm.reset();
  fbStatus.hidden = true;
  closeSidebar();
  fbDialog.showModal();
  fbMessage.focus();
});

fbCancel.addEventListener("click", () => fbDialog.close());

fbForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = fbMessage.value.trim();
  if (!message) return;

  fbSend.disabled = true;
  fbStatus.hidden = true;
  try {
    const res = await apiFetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: fbKind.value, message }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    fbStatus.textContent = "Teşekkürler! Geri bildirimin alındı.";
    fbStatus.className = "fb-status ok";
    fbStatus.hidden = false;
    setTimeout(() => fbDialog.close(), 1200);
  } catch (err) {
    fbStatus.textContent = "Gönderilemedi: " + err.message;
    fbStatus.className = "fb-status err";
    fbStatus.hidden = false;
  } finally {
    fbSend.disabled = false;
  }
});

// --------------------------------------------------------------------------- //
// Çıkış
// --------------------------------------------------------------------------- //
const logoutBtn = document.getElementById("logout-btn");
logoutBtn?.addEventListener("click", async () => {
  logoutBtn.disabled = true;
  try {
    await fetch("/logout", { method: "POST" });
  } catch (_) {
    /* yoksay */
  }
  window.location.href = "/login";
});

// --------------------------------------------------------------------------- //
// Service worker + açılış
// --------------------------------------------------------------------------- //
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  });
}

(async function init() {
  const items = await loadConversations();
  if (items.length) {
    await openConversation(items[0].id); // en son güncellenen konuşma
  } else {
    await newConversation();
  }
})();
