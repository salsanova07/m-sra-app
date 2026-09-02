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

function setBusy(b) {
  sending = b;
  input.disabled = sendBtn.disabled = b;
}

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
// İkonlar (sade, tek renk çizgi)
// --------------------------------------------------------------------------- //
const ICONS = {
  copy: '<rect x="6" y="6" width="8" height="8" rx="1.5"/><path d="M10.5 6V4A1.5 1.5 0 0 0 9 2.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h2"/>',
  check: '<path d="M3.5 8.5l3 3 6-6.5"/>',
  edit: '<path d="M11.3 3.1l1.6 1.6M3.4 12.6l7.3-7.3 1.6 1.6-7.3 7.3-2.1.5z"/>',
  retry: '<path d="M12.7 4.6a5.2 5.2 0 1 0 1.1 3.4"/><path d="M13.6 2.3v3.1h-3.1"/>',
  pdf: '<path d="M4 2h5l3.4 3.4V14a.9.9 0 0 1-.9.9H4a.9.9 0 0 1-.9-.9V2.9A.9.9 0 0 1 4 2z"/><path d="M9 2.2v3.6h3.4"/>',
  pin: '<path d="M6 2.6h4M7.3 2.6v3l-1.7 1.7v1h4.8v-1L8.7 5.6v-3"/><path d="M8 8.3v5.1"/>',
};

function iconSvg(name) {
  return (
    `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" ` +
    `stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`
  );
}

function iconBtn(name, title, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "act";
  b.title = title;
  b.setAttribute("aria-label", title);
  b.innerHTML = iconSvg(name);
  b.addEventListener("click", () => onClick(b));
  return b;
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
function addBubble(role, text = "", msgId = null) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  if (msgId != null) wrap.dataset.messageId = msgId;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const content = document.createElement("div");
  content.className = "content";
  renderText(content, text);
  bubble.appendChild(content);

  const actions = document.createElement("div");
  actions.className = "bubble-actions";
  actions.appendChild(
    iconBtn("copy", "Kopyala", (b) => copyText(content.textContent, b)),
  );
  if (role === "user") {
    actions.appendChild(iconBtn("edit", "Düzenle", () => startEdit(content)));
  }
  if (role === "assistant") {
    actions.appendChild(iconBtn("retry", "Yeniden oluştur", () => retryMessage(content)));
  }
  actions.appendChild(
    iconBtn("pdf", "PDF'e dönüştür", () => openPdfDialog(content.textContent, bubble)),
  );
  actions.appendChild(
    iconBtn("pin", "Panoya ekle", (b) => pinText(content.textContent, b)),
  );
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
  for (const m of messages) addBubble(m.role, m.content, m.id);
}

function removeAfter(wrapper) {
  let n = wrapper.nextElementSibling;
  while (n) {
    const next = n.nextElementSibling;
    n.remove();
    n = next;
  }
}

// --------------------------------------------------------------------------- //
// Kopyala (tarayıcı panosu — 'Pano' özelliğiyle ilgisiz)
// --------------------------------------------------------------------------- //
function escapeHtml(s) {
  return String(s).replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]),
  );
}

async function writeClipboard(text) {
  text = (text || "").trim();
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.cssText = "position:fixed;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    return true;
  } catch (_) {
    return false;
  }
}

async function copyText(text, btn) {
  if (!(await writeClipboard(text))) {
    btn.title = "Kopyalanamadı";
    return;
  }
  const orig = btn.innerHTML;
  btn.innerHTML = iconSvg("check");
  btn.classList.add("ok");
  setTimeout(() => {
    btn.innerHTML = orig;
    btn.classList.remove("ok");
  }, 1200);
}

// --------------------------------------------------------------------------- //
// Düzenle (kullanıcı mesajı) — sonrası silinir, yeni cevap üretilir
// --------------------------------------------------------------------------- //
function startEdit(contentEl) {
  if (sending) return;
  const wrapper = contentEl.closest(".msg");
  const bubble = contentEl.closest(".bubble");
  const actions = bubble.querySelector(".bubble-actions");
  const msgId = Number(wrapper.dataset.messageId);
  if (!msgId) return; // henüz kaydedilmemiş mesaj
  const original = contentEl.textContent;

  const box = document.createElement("div");
  box.className = "edit-box";
  const ta = document.createElement("textarea");
  ta.className = "edit-area";
  ta.value = original;
  const bar = document.createElement("div");
  bar.className = "edit-bar";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "btn-ghost sm";
  cancel.textContent = "İptal";
  const send = document.createElement("button");
  send.type = "button";
  send.className = "btn-primary sm";
  send.textContent = "Gönder";
  bar.append(cancel, send);
  box.append(ta, bar);

  contentEl.hidden = true;
  actions.hidden = true;
  bubble.insertBefore(box, actions);
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);

  const close = () => {
    box.remove();
    contentEl.hidden = false;
    actions.hidden = false;
  };
  cancel.addEventListener("click", close);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send.click();
  });

  send.addEventListener("click", async () => {
    const newText = ta.value.trim();
    if (!newText) return;
    if (newText === original) return close();
    send.disabled = cancel.disabled = true;
    setBusy(true);
    renderText(contentEl, newText);
    close();
    removeAfter(wrapper);
    const reply = addBubble("assistant");
    const ids = await streamChat({
      content: newText,
      truncateFromId: msgId,
      reply,
    });
    if (ids.user_message_id) wrapper.dataset.messageId = ids.user_message_id;
    if (ids.assistant_message_id)
      reply.closest(".msg").dataset.messageId = ids.assistant_message_id;
    setBusy(false);
    input.focus();
  });
}

// --------------------------------------------------------------------------- //
// Yeniden oluştur (Mısra'nın cevabı)
// --------------------------------------------------------------------------- //
async function retryMessage(contentEl) {
  if (sending) return;
  const wrapper = contentEl.closest(".msg");
  const msgId = Number(wrapper.dataset.messageId);
  if (!msgId) return;
  setBusy(true);
  removeAfter(wrapper);
  wrapper.remove();
  const reply = addBubble("assistant");
  const ids = await streamChat({ truncateFromId: msgId, reply });
  if (ids.assistant_message_id)
    reply.closest(".msg").dataset.messageId = ids.assistant_message_id;
  setBusy(false);
  input.focus();
}

// --------------------------------------------------------------------------- //
// PDF ve pano işlemleri (buton yolu)
// --------------------------------------------------------------------------- //

// PDF'i indirir ve tarayıcının kaydetme işlemini doğrudan tetikler
// (masaüstü: dosya iner; mobilde <a download> desteklenmiyorsa yeni sekmede açılır).
async function triggerDownload(url, filename) {
  const res = await apiFetch(url);
  if (!res.ok) throw new Error("HTTP " + res.status);
  const blob = await res.blob();
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = filename || "belge.pdf";
  a.target = "_blank";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objUrl), 10000);
}

function attachPdfLink(container, url, filename) {
  let link = container.querySelector(":scope > .pdf-link");
  if (!link) {
    link = document.createElement("a");
    link.className = "pdf-link";
    container.insertBefore(link, container.querySelector(".bubble-actions"));
  }
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "📄 " + filename;
}

// PDF'e Dönüştür formu — yazı tipi / hizalama / sayfa boyutu seçilir,
// sonra "PDF İndir" (ayarlarla PDF) veya "Metni Kopyala" (seçilen yazı tipi +
// hizalamayla biçimlendirilmiş; zengin metin olarak panoya, düz metin yedekli).
const pdfDialog = document.getElementById("pdf-dialog");
const pdfForm = document.getElementById("pdf-form");
const pdfFont = document.getElementById("pdf-font");
const pdfAlign = document.getElementById("pdf-align");
const pdfSize = document.getElementById("pdf-size");
const pdfStatus = document.getElementById("pdf-status");
const pdfCancel = document.getElementById("pdf-cancel");
const pdfCopyBtn = document.getElementById("pdf-copy");
const pdfDownloadBtn = document.getElementById("pdf-download");

let pdfCtx = { text: "", container: null };

function openPdfDialog(text, container) {
  text = (text || "").trim();
  if (!text) return;
  pdfCtx = { text, container: container || null };
  pdfStatus.hidden = true;
  pdfDownloadBtn.disabled = false;
  pdfDialog.showModal();
}

pdfCancel.addEventListener("click", () => pdfDialog.close());

// Formdaki font seçimi -> yapıştırılan uygulamada kullanılacak font yığını.
// (Times New Roman / Georgia her yerde vardır; Tinos / Gelasio yedek.)
// Tek tırnak: değer çift tırnaklı style="" içine gömülecek.
const PDF_FONT_STACKS = {
  times: "'Times New Roman', Tinos, Times, serif",
  merriweather: "Merriweather, Georgia, 'Times New Roman', serif",
  georgia: "Georgia, Gelasio, 'Times New Roman', serif",
};

function buildRichHtml(text, fontKey, alignKey) {
  const family = PDF_FONT_STACKS[fontKey] || PDF_FONT_STACKS.merriweather;
  const align = ["left", "center", "right", "justify"].includes(alignKey)
    ? alignKey
    : "justify";
  const paras = text
    .trim()
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map(
      (p) =>
        `<p style="margin:0 0 1em;text-align:${align};font-family:${family};">` +
        `${escapeHtml(p).replace(/\n/g, "<br>")}</p>`,
    )
    .join("");
  return (
    `<meta charset="utf-8">` +
    `<div style="font-family:${family};text-align:${align};">${paras}</div>`
  );
}

// Öncelik: zengin metin (text/html + text/plain). Olmazsa düz metne düş.
async function writeRichClipboard(html, plain) {
  try {
    if (navigator.clipboard?.write && window.ClipboardItem) {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([plain], { type: "text/plain" }),
        }),
      ]);
      return "rich";
    }
  } catch (_) {
    /* zengin kopyalama desteklenmiyor — düz metne düş */
  }
  return (await writeClipboard(plain)) ? "plain" : "fail";
}

pdfCopyBtn.addEventListener("click", async () => {
  const html = buildRichHtml(pdfCtx.text, pdfFont.value, pdfAlign.value);
  const result = await writeRichClipboard(html, pdfCtx.text);
  const msg = {
    rich: "Biçimlendirilmiş metin panoya kopyalandı.",
    plain: "Panoya kopyalandı (bu tarayıcı yalnız düz metni destekliyor).",
    fail: "Kopyalanamadı.",
  };
  pdfStatus.textContent = msg[result];
  pdfStatus.className = "fb-status " + (result === "fail" ? "err" : "ok");
  pdfStatus.hidden = false;
});

pdfForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  pdfDownloadBtn.disabled = true;
  pdfStatus.hidden = true;
  try {
    const res = await apiFetch("/api/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: pdfCtx.text,
        font: pdfFont.value,
        align: pdfAlign.value,
        page_size: pdfSize.value,
      }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const { url, filename } = await res.json();
    await triggerDownload(url, filename);
    // Link balonda da kalsın: indirme açılmadıysa ya da tekrar gerekirse.
    if (pdfCtx.container) attachPdfLink(pdfCtx.container, url, filename);
    pdfStatus.innerHTML =
      `PDF indirildi. Başlamadıysa: ` +
      `<a href="${url}" target="_blank" rel="noopener">${escapeHtml(filename)}</a>`;
    pdfStatus.className = "fb-status ok";
    pdfStatus.hidden = false;
  } catch (_) {
    pdfStatus.textContent = "PDF oluşturulamadı, tekrar dene.";
    pdfStatus.className = "fb-status err";
    pdfStatus.hidden = false;
  } finally {
    pdfDownloadBtn.disabled = false;
  }
});

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
      const { id } = await res.json();
      openSidebar();
      switchTab("pin", id);
    }
  } finally {
    btn.disabled = false;
  }
}

// --------------------------------------------------------------------------- //
// Kenar panel: sekmeler
// --------------------------------------------------------------------------- //
function switchTab(which, highlightId = null) {
  const pin = which === "pin";
  tabPin.classList.toggle("active", pin);
  tabConv.classList.toggle("active", !pin);
  convList.hidden = pin;
  newConvBtn.hidden = pin;
  pinList.hidden = !pin;
  if (pin) loadPins(highlightId);
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
async function loadPins(highlightId = null) {
  const res = await apiFetch("/api/pins");
  const items = await res.json();
  pinList.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "pin-empty";
    li.textContent = "Pano boş. Bir mesajın altındaki 📌 ile ekleyebilirsin.";
    pinList.appendChild(li);
    return;
  }
  for (const p of items) {
    const li = document.createElement("li");
    li.className = "pin-item";
    if (p.id === highlightId) li.classList.add("flash");

    const txt = document.createElement("div");
    txt.className = "pin-text";
    txt.textContent = p.content;
    li.appendChild(txt);

    const row = document.createElement("div");
    row.className = "pin-actions";
    row.appendChild(
      iconBtn("pdf", "PDF'e dönüştür", () => openPdfDialog(p.content, li)),
    );
    const del = document.createElement("button");
    del.type = "button";
    del.className = "act";
    del.title = "Panodan kaldır";
    del.textContent = "×";
    del.addEventListener("click", async () => {
      await apiFetch(`/api/pins/${p.id}`, { method: "DELETE" });
      loadPins();
    });
    row.appendChild(del);
    li.appendChild(row);
    pinList.appendChild(li);
  }
  if (highlightId != null) {
    pinList
      .querySelector(".pin-item.flash")
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
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
// Yazma alanı + gönderme
// --------------------------------------------------------------------------- //
function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}
input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    form.requestSubmit();
  }
});

/** /api/chat akışını bir asistan balonuna işler; done olaylarındaki id'leri döndürür. */
async function streamChat({ content = null, truncateFromId = null, reply }) {
  reply.classList.add("pending");
  reply.classList.remove("error");
  let acc = "";
  let ids = {};
  try {
    const res = await apiFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: currentId,
        content,
        truncate_from_id: truncateFromId,
      }),
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
        } else if (payload.done) {
          ids = payload;
        }
      }
    }
  } catch (err) {
    reply.classList.add("error");
    renderText(reply, acc + `\n\n[Hata: ${err.message}]`);
  } finally {
    reply.classList.remove("pending");
    loadConversations();
  }
  return ids;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || sending || currentId === null) return;

  setBusy(true);
  input.value = "";
  autoGrow();

  const first = chat.querySelector(".msg.assistant .content");
  if (chat.children.length === 1 && first && first.textContent === GREETING) {
    chat.innerHTML = "";
  }

  const userC = addBubble("user", text);
  const reply = addBubble("assistant");
  const ids = await streamChat({ content: text, reply });
  if (ids.user_message_id)
    userC.closest(".msg").dataset.messageId = ids.user_message_id;
  if (ids.assistant_message_id)
    reply.closest(".msg").dataset.messageId = ids.assistant_message_id;

  setBusy(false);
  input.focus();
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
    await openConversation(items[0].id);
  } else {
    await newConversation();
  }
})();
