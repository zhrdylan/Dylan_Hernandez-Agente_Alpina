import { api } from "./api.js";
import { state, setState } from "./state.js";
import { storage } from "./storage.js";
import { renderMessages, showTypingIndicator, hideTypingIndicator } from "./components/chat.js";
import { loadAndRenderCatalog } from "./components/catalog.js";
import { loadAndRenderDocuments, openPagePreview, setupPreviewControls } from "./components/documents.js";
import { openPdfPreviewModal, closeDossierModal } from "./components/dossier.js";
import { initCitationDrawer } from "./components/inspector.js";
import { refreshIcons } from "./utils/icons.js";

/**
 * Punto de entrada principal (ES Module) del Agente Alpina.
 */
document.addEventListener("DOMContentLoaded", async () => {
  storage.cookies.getDeviceId();
  storage.cookies.getSessionId();
  initModals();
  initComposer();
  initSidebar();
  initCitationDrawer();
  setupPreviewControls();

  refreshIcons();

  await checkHealthAndStats();
  await loadChats();
});

async function checkHealthAndStats() {
  const statusEl = document.getElementById("agent-status");
  const statsEl = document.getElementById("corpus-stats");

  try {
    const health = await api("/health");
    if (statusEl) {
      if (health.agent_ready) {
        statusEl.innerHTML = `<i data-lucide="check-circle" class="ui-icon" style="color:var(--green); width:13px; height:13px;"></i> <span>Conectado (Semántico)</span>`;
        statusEl.classList.add("ready");
      } else {
        statusEl.innerHTML = `<i data-lucide="loader-2" class="ui-icon spin" style="width:13px; height:13px;"></i> <span>Iniciando...</span>`;
      }
      refreshIcons(statusEl);
    }

    const stats = await api("/api/stats");
    if (statsEl) {
      statsEl.innerHTML = `<i data-lucide="layers" class="ui-icon" style="width:13px; height:13px; margin-right:4px;"></i> <span>${stats.documents || 0} docs · ${stats.products || 0} productos · ${stats.chunks || 0} chunks</span>`;
      refreshIcons(statsEl);
    }
  } catch (err) {
    if (statusEl) {
      statusEl.innerHTML = `<i data-lucide="alert-triangle" class="ui-icon" style="color:var(--red); width:13px; height:13px;"></i> <span>Error de conexión</span>`;
      refreshIcons(statusEl);
    }
  }
}

async function loadChats() {
  try {
    const chats = await api("/api/chats");
    state.chats = chats;
    renderChatList(chats);

    if (chats.length > 0) {
      const savedChatId = storage.local.getActiveChatId();
      const targetChat = chats.find(c => c.id === savedChatId) || chats[0];
      await selectChat(targetChat.id);
    } else {
      state.activeChatId = null;
      storage.local.setActiveChatId(null);
      state.messages = [];
      renderMessages([], handleAsk);
    }
  } catch (err) {
    console.error("Error al cargar chats:", err);
  }
}

function renderChatList(chats) {
  const listEl = document.getElementById("chat-list");
  if (!listEl) return;

  if (!chats || chats.length === 0) {
    listEl.innerHTML = `<div style="color: var(--sidebar-muted); font-size: 0.78rem; padding: 8px;"><i data-lucide="message-square-dashed" class="ui-icon" style="width:14px;height:14px;margin-right:4px;"></i> Sin chats aún.</div>`;
    refreshIcons(listEl);
    return;
  }

  listEl.innerHTML = chats.map(c => `
    <button class="chat-item ${c.id === state.activeChatId ? "active" : ""}" type="button" data-chat-id="${c.id}" title="${escapeHtml(c.title || 'Nuevo chat')}">
      <i data-lucide="message-square" class="ui-icon chat-item-icon"></i>
      <span class="chat-item-title">${escapeHtml(c.title || "Nuevo chat")}</span>
    </button>
  `).join("");

  listEl.querySelectorAll(".chat-item").forEach(btn => {
    btn.onclick = () => selectChat(btn.dataset.chatId);
  });

  refreshIcons(listEl);
}

async function selectChat(chatId) {
  state.activeChatId = chatId;
  storage.local.setActiveChatId(chatId);
  renderChatList(state.chats);

  const titleEl = document.getElementById("chat-title");
  const activeChat = state.chats.find(c => c.id === chatId);
  if (titleEl && activeChat) titleEl.textContent = activeChat.title || "Chat activo";

  try {
    const messages = await api(`/api/chats/${chatId}/messages`);
    state.messages = messages;
    renderMessages(messages, handleAsk);
  } catch (err) {
    console.error("Error al obtener mensajes:", err);
  }
}

function initComposer() {
  const form = document.getElementById("composer");
  const input = document.getElementById("message-input");
  if (!form || !input) return;

  // Restaurar borrador de la sesión actual si existe
  const draft = storage.session.getComposerDraft();
  if (draft) input.value = draft;

  // Persistir en tiempo real en sessionStorage
  input.addEventListener("input", () => {
    storage.session.setComposerDraft(input.value);
  });

  form.onsubmit = async (e) => {
    e.preventDefault();
    const content = input.value.trim();
    if (!content || state.isSending) return;
    input.value = "";
    storage.session.clearComposerDraft();
    await handleAsk(content);
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event("submit"));
    }
  });
}

async function handleAsk(content) {
  if (!content || state.isSending) return;
  state.isSending = true;

  try {
    // Si no hay chat activo, crear uno dentro del bloque protegido (F16)
    if (!state.activeChatId) {
      const newChat = await api("/api/chats", { method: "POST", body: { title: content.slice(0, 40) } });
      state.activeChatId = newChat.id;
      storage.local.setActiveChatId(newChat.id);
      state.chats.unshift(newChat);
      renderChatList(state.chats);
    }

    const targetChatId = state.activeChatId;

    // Agregar mensaje de usuario optimistamente
    const userMsg = { role: "user", content, created_at: new Date().toISOString() };
    state.messages.push(userMsg);
    renderMessages(state.messages, handleAsk);
    showTypingIndicator();

    const res = await api(`/api/chats/${targetChatId}/messages`, {
      method: "POST",
      body: { content },
    });

    hideTypingIndicator();
    const assistantMsg = {
      role: "assistant",
      content: res.answer,
      citations: res.citations || [],
      metadata: res.metadata || {},
      generated_report: res.generated_report || res.metadata?.generated_report || null,
      created_at: new Date().toISOString(),
    };
    if (assistantMsg.generated_report && !assistantMsg.metadata.generated_report) {
      assistantMsg.metadata.generated_report = assistantMsg.generated_report;
    }

    // Vincular respuesta a la conversación activa para evitar fuga de mensajes si el usuario cambió de chat (F16)
    if (state.activeChatId === targetChatId) {
      state.messages.push(assistantMsg);
      renderMessages(state.messages, handleAsk);
    }

    // Actualizar lista de chats
    const chats = await api("/api/chats");
    state.chats = chats;
    renderChatList(chats);
  } catch (err) {
    hideTypingIndicator();
    alert(`Error del agente: ${err.message}`);
  } finally {
    state.isSending = false;
  }
}

function initSidebar() {
  document.getElementById("new-chat")?.addEventListener("click", async () => {
    const newChat = await api("/api/chats", { method: "POST", body: { title: "Nuevo chat" } });
    state.chats.unshift(newChat);
    renderChatList(state.chats);
    await selectChat(newChat.id);
  });

  document.getElementById("clear-chats")?.addEventListener("click", async () => {
    if (!confirm("¿Deseas vaciar todas las conversaciones? Esta acción no se puede deshacer.")) return;
    await api("/api/chats", { method: "DELETE" });
    storage.local.removeActiveChatId();
    storage.session.clearComposerDraft();
    state.chats = [];
    state.messages = [];
    state.activeChatId = null;
    renderChatList([]);
    renderMessages([], handleAsk);
  });

  document.getElementById("delete-chat")?.addEventListener("click", async () => {
    if (!state.activeChatId) return;
    if (!confirm("¿Deseas eliminar este chat?")) return;
    const chatToDelete = state.activeChatId;
    storage.local.removeActiveChatId();
    state.activeChatId = null;
    await api(`/api/chats/${chatToDelete}`, { method: "DELETE" });
    await loadChats();
  });

  document.getElementById("products-button")?.addEventListener("click", () => {
    openModal("catalog");
    loadAndRenderCatalog((productName) => {
      closeModal("catalog");
      handleAsk(`¿Qué información oficial tienes del producto ${productName}?`);
    });
  });

  document.getElementById("documents-button")?.addEventListener("click", () => {
    openModal("documents");
    loadAndRenderDocuments();
  });
}

function initModals() {
  document.querySelectorAll("[data-close-modal]").forEach(btn => {
    btn.onclick = () => closeModal(btn.dataset.closeModal);
  });

  // Cerrar al pulsar Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal.open").forEach(m => m.classList.remove("open"));
    }
  });
}

function openModal(id) {
  const modal = document.getElementById(`${id}-modal`);
  if (modal) {
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
  }
}

function closeModal(id) {
  const modal = document.getElementById(`${id}-modal`);
  if (modal) {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text || "");
  return div.innerHTML;
}
