const chat = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");

/** Sohbet geçmişi — her istekte tamamı backend'e gönderilir. */
const history = [];

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
  if (!text) return;

  input.value = "";
  autoGrow();
  input.disabled = sendBtn.disabled = true;

  addBubble("user", text);
  history.push({ role: "user", content: text });

  const reply = addBubble("assistant");
  reply.classList.add("pending");
  let acc = "";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const readerLoop = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await readerLoop.read();
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

    history.push({ role: "assistant", content: acc });
  } catch (err) {
    reply.classList.add("error");
    reply.textContent = acc + `\n\n[Hata: ${err.message}]`;
  } finally {
    reply.classList.remove("pending");
    input.disabled = sendBtn.disabled = false;
    input.focus();
  }
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  });
}
