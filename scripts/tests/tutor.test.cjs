const assert = require("node:assert/strict");
const test = require("node:test");
const { requestReply, parseReply, appendMessage, initTutor } = require("../../core/static/core/js/tutor.js");

const success = { status: "sucesso", resposta_tutor: { texto: "Comece por uma meta.", tipo: "tarefa" }, session_id: 42 };

test("tutor sends CSRF, same-origin credentials and a numeric conversation ID", async () => {
  let request;
  const result = await requestReply({
    fetchImpl: async (url, options) => { request = { url, ...options }; return { ok: true, json: async () => success }; },
    url: "/api/tutor/", message: "Minha dúvida", token: "csrf-token", sessionId: 7,
  });
  assert.equal(request.url, "/api/tutor/");
  assert.equal(request.credentials, "same-origin");
  assert.equal(request.headers["X-CSRFToken"], "csrf-token");
  assert.deepEqual(JSON.parse(request.body), { mensagem: "Minha dúvida", session_id: 7 });
  assert.equal(result.sessionId, 42);
});

test("tutor rejects login redirects, unavailable servers and invalid JSON without rendering them", async () => {
  const options = { url: "/api/tutor/", message: "Ajuda", token: "token" };
  for (const response of [
    { ok: true, redirected: true },
    { ok: false, status: 403 },
    { ok: false, status: 500 },
    { ok: true, json: async () => { throw new SyntaxError("HTML page"); } },
  ]) {
    await assert.rejects(requestReply({ ...options, fetchImpl: async () => response }));
  }
});

test("tutor does not trust malformed response objects", () => {
  for (const malformed of [null, [], {}, { ...success, session_id: "42" },
    { ...success, resposta_tutor: { texto: {} } }, { ...success, resposta_tutor: { texto: "  " } }]) {
    assert.throws(() => parseReply(malformed));
  }
  assert.equal(parseReply({ ...success, resposta_tutor: { texto: "Olá", tipo: 'x\" onclick=alert(1)' } }).type, "tutor");
});

function element() {
  const classes = new Set();
  return {
    children: [], dataset: {}, style: {}, value: "", textContent: "", disabled: false,
    classList: { add: (name) => classes.add(name), toggle: (name, force) => force ? classes.add(name) : classes.delete(name) },
    append(...children) { this.children.push(...children); },
    setAttribute() {}, addEventListener() {}, focus() {}, querySelector() { return null; },
    set innerHTML(_) { throw new Error("HTML injection must never be used"); },
  };
}

test("tutor displays HTML-like model output as literal text", () => {
  const chat = element();
  const payload = '<img src=x onerror="alert(1)">\n<script>steal()</script>';
  const row = appendMessage({ createElement: element }, chat, "assistant", payload, "tutor");
  assert.equal(row.children[1].textContent, payload);
  assert.equal(row.children[1].children.length, 0);
  assert.equal(chat.children.length, 1);
});

function tutorHarness(fetchImpl) {
  const nodes = Object.fromEntries(["chat", "tutor-form", "message", "tutor-send-btn", "tutor-status"].map((id) => [id, element()]));
  nodes.chat.dataset = { url: "/api/tutor/", sessionId: "9" };
  const document = { getElementById: (id) => nodes[id], querySelectorAll: () => [], createElement: element };
  const browser = { fetch: fetchImpl, AbortController, setTimeout, clearTimeout };
  return { nodes, controller: initTutor(document, browser) };
}

test("network failure preserves the draft, restores controls and leaves the conversation unchanged", async () => {
  const { nodes, controller } = tutorHarness(async () => { throw new TypeError("offline"); });
  nodes.message.value = "Meu projeto precisa de ajuda";
  await controller.submit();
  assert.equal(nodes.message.value, "Meu projeto precisa de ajuda");
  assert.equal(nodes.message.disabled, false);
  assert.equal(nodes["tutor-send-btn"].disabled, false);
  assert.match(nodes["tutor-status"].textContent, /conexão/);
  assert.equal(nodes.chat.children.length, 0);
});

test("pending requests prevent duplicate submission and continue the returned session", async () => {
  let resolveFetch;
  const requests = [];
  const { nodes, controller } = tutorHarness((url, options) => {
    requests.push(JSON.parse(options.body));
    return new Promise((resolve) => { resolveFetch = resolve; });
  });
  nodes.message.value = "Como começar?";
  const pending = controller.submit();
  await controller.submit();
  assert.equal(requests.length, 1);
  assert.equal(nodes.message.disabled, true);
  assert.equal(requests[0].session_id, 9);
  resolveFetch({ ok: true, json: async () => success });
  await pending;
  assert.equal(nodes.chat.dataset.sessionId, "42");
  assert.equal(nodes.message.value, "");
  assert.equal(nodes.chat.children.length, 2);
  assert.equal(nodes.message.disabled, false);
});
