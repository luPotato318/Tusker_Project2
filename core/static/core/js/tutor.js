(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root.document) api.initTutor(root.document, root);
})(typeof window === "undefined" ? globalThis : window, function () {
  "use strict";

  const QUICK_PROMPTS = {
    recomendar_cursos: "Recomendar oficinas",
    tarefa_dia: "Tarefa do dia",
    ideia_projeto: "Ideia de projeto",
    simular_entrevista: "Simular entrevista",
  };
  const REPLY_TYPES = new Set(["simples", "alerta", "recomendacao", "desafio", "tarefa", "ideia", "tutor"]);

  function parseReply(payload) {
    const reply = payload && payload.resposta_tutor;
    if (payload?.status !== "sucesso" || !reply || typeof reply.texto !== "string" || !reply.texto.trim()
        || !Number.isSafeInteger(payload.session_id) || payload.session_id < 1) {
      throw new Error("A resposta não pôde ser lida. Atualize a página para conferir o histórico antes de reenviar.");
    }
    return {
      text: reply.texto,
      type: REPLY_TYPES.has(reply.tipo) ? reply.tipo : "tutor",
      sessionId: payload.session_id,
    };
  }

  async function requestReply({ fetchImpl, url, message, token, sessionId, signal }) {
    const payload = { mensagem: message };
    if (Number.isSafeInteger(sessionId) && sessionId > 0) payload.session_id = sessionId;
    const response = await fetchImpl(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token, "Accept": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
    if (response.redirected || response.status === 401 || response.status === 403) {
      throw new Error("Sua sessão expirou ou o acesso foi recusado. Atualize a página e entre novamente.");
    }
    if (response.status === 404) {
      throw new Error("Esta conversa não está disponível. Atualize a página para continuar.");
    }
    if (response.status === 429) throw new Error("Aguarde um momento antes de enviar outra pergunta.");
    if (!response.ok) throw new Error("O tutor está indisponível. Sua pergunta foi preservada; confira o histórico antes de reenviar.");
    let result;
    try {
      result = await response.json();
    } catch (_) {
      throw new Error("A resposta não pôde ser lida. Atualize a página para conferir o histórico antes de reenviar.");
    }
    return parseReply(result);
  }

  function appendMessage(document, chat, role, text, type) {
    const row = document.createElement("div");
    row.className = `chat-message ${role === "user" ? "user-message" : "tutor-message"}`;
    if (REPLY_TYPES.has(type)) row.classList.add(`type-${type}`);
    const sender = document.createElement("span");
    sender.className = "sender";
    sender.textContent = role === "user" ? "Você" : "Tutor PIEM";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    // Replies and user input are always text, including anything resembling HTML.
    bubble.textContent = text;
    bubble.style.whiteSpace = "pre-wrap";
    row.append(sender, bubble);
    chat.append(row);
    chat.scrollTop = chat.scrollHeight;
    return row;
  }

  function initTutor(document, browser) {
    const chat = document.getElementById("chat");
    const form = document.getElementById("tutor-form");
    const input = document.getElementById("message");
    const send = document.getElementById("tutor-send-btn");
    const status = document.getElementById("tutor-status");
    const voice = document.getElementById("tutor-voice-btn");
    if (!chat || !form || !input || !send || !status) return null;
    const chips = Array.from(document.querySelectorAll("[data-tutor-prompt]"));
    const token = form.querySelector('[name="csrfmiddlewaretoken"]');
    let sessionId = Number(chat.dataset.sessionId) || null;
    let pending = false;
    let listening = false;
    let recognition = null;

    function setStatus(message, error = false) {
      status.textContent = message;
      status.classList.toggle("tutor-status-error", error);
    }

    function setPending(value) {
      pending = value;
      chat.setAttribute("aria-busy", String(value));
      input.disabled = value;
      send.disabled = value;
      send.textContent = value ? "Enviando…" : "Enviar";
      chips.forEach((chip) => { chip.disabled = value; });
      if (voice) voice.disabled = value;
    }

    async function submit(prompt) {
      if (pending) return;
      const message = (prompt || input.value).trim();
      if (!message) {
        setStatus("Escreva uma pergunta para conversar com o tutor.", true);
        input.focus();
        return;
      }
      if (message.length > 4000) {
        setStatus("Sua pergunta deve ter até 4.000 caracteres.", true);
        input.focus();
        return;
      }
      if (listening && recognition) recognition.stop();
      // A failed quick prompt remains editable and retryable, just like typed input.
      input.value = message;
      setPending(true);
      setStatus("O tutor está preparando sua resposta…");
      const controller = new browser.AbortController();
      const timeout = browser.setTimeout(() => controller.abort(), 65000);
      try {
        const result = await requestReply({
          fetchImpl: browser.fetch.bind(browser), url: chat.dataset.url,
          message, token: token ? token.value : "", sessionId, signal: controller.signal,
        });
        sessionId = result.sessionId;
        chat.dataset.sessionId = String(sessionId);
        appendMessage(document, chat, "user", QUICK_PROMPTS[message] || message);
        appendMessage(document, chat, "assistant", result.text, result.type);
        input.value = "";
        setStatus("Resposta recebida. Você pode continuar a conversa.");
      } catch (error) {
        const message = error.name === "AbortError"
          ? "A resposta demorou mais que o esperado. Sua pergunta foi preservada; confira o histórico antes de reenviar."
          : error instanceof TypeError
            ? "Não foi possível conectar ao tutor. Verifique sua conexão e confira o histórico antes de reenviar."
            : error.message;
        setStatus(message, true);
      } finally {
        browser.clearTimeout(timeout);
        setPending(false);
        input.focus();
      }
    }

    form.addEventListener("submit", (event) => { event.preventDefault(); submit(); });
    chips.forEach((chip) => chip.addEventListener("click", () => submit(chip.dataset.tutorPrompt)));
    const SpeechRecognition = browser.SpeechRecognition || browser.webkitSpeechRecognition;
    if (voice && SpeechRecognition && browser.isSecureContext) {
      voice.hidden = false;
      voice.addEventListener("click", () => {
        if (pending) return;
        if (listening && recognition) { recognition.stop(); return; }
        try {
          recognition = new SpeechRecognition();
          recognition.lang = "pt-BR";
          recognition.interimResults = false;
          recognition.maxAlternatives = 1;
          recognition.onstart = () => {
            listening = true;
            voice.setAttribute("aria-pressed", "true");
            voice.setAttribute("aria-label", "Parar ditado por voz");
            setStatus("Ouvindo… Ao terminar, revise o texto antes de enviar.");
          };
          recognition.onresult = (event) => {
            const transcript = event.results?.[0]?.[0]?.transcript;
            if (!pending && typeof transcript === "string") {
              input.value = transcript.slice(0, 4000);
              setStatus("Ditado concluído. Revise a pergunta e selecione Enviar.");
            }
          };
          recognition.onerror = () => setStatus("Não foi possível usar o microfone. Você pode digitar sua pergunta.", true);
          recognition.onend = () => {
            listening = false;
            voice.setAttribute("aria-pressed", "false");
            voice.setAttribute("aria-label", "Ditado por voz");
            if (!pending) input.focus();
          };
          recognition.start();
        } catch (_) {
          setStatus("O ditado não está disponível neste navegador. Digite sua pergunta.", true);
        }
      });
    }
    chat.scrollTop = chat.scrollHeight;
    return { submit };
  }

  return { initTutor, requestReply, parseReply, appendMessage };
});
