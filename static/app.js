const chat = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const convList = document.getElementById("conv-list");
const newConvBtn = document.getElementById("new-conv");
const sidebar = document.getElementById("sidebar");
const overlay = document.getElementById("overlay");
const menuBtn = document.getElementById("menu-btn");

const GREETING = "Merhaba. Ben Mısra. Ne üzerinde çalışıyorsun?";

let currentId = null; // açık konuşmanın id'si
let sending = false;

// --------------------------------------------------------------------------- //
// Mesaj balonları
// --------------------------------------------------------------------------- //
function addBubble(role, text = "") {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return bubble;
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
// Konuşma listesi / paneli
// --------------------------------------------------------------------------- //
async function loadConversations() {
  const res = await fetch("/api/conversations");
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
  const res = await fetch(`/api/conversations/${id}/messages`);
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
  const res = await fetch("/api/conversations", { method: "POST" });
  const c = await res.json();
  currentId = c.id;
  await loadConversations();
  renderMessages([]);
  closeSidebar();
  input.focus();
}

async function deleteConversation(id) {
  await fetch(`/api/conversations/${id}`, { method: "DELETE" });
  if (id === currentId) currentId = null;
  const items = await loadConversations();
  if (currentId === null) {
    if (items.length) await openConversation(items[0].id);
    else await newConversation();
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
  if (e.key === "Enter" && !e.shiftKey) {
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
  const onlyGreeting =
    chat.children.length === 1 &&
    chat.querySelector(".msg.assistant .bubble")?.textContent === GREETING;
  if (onlyGreeting) chat.innerHTML = "";

  addBubble("user", text);
  const reply = addBubble("assistant");
  reply.classList.add("pending");
  let acc = "";

  try {
    const res = await fetch("/api/chat", {
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
          reply.textContent = acc;
          chat.scrollTop = chat.scrollHeight;
        } else if (payload.error) {
          throw new Error(payload.error);
        }
      }
    }
  } catch (err) {
    reply.classList.add("error");
    reply.textContent = acc + `\n\n[Hata: ${err.message}]`;
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
    const res = await fetch("/api/feedback", {
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
