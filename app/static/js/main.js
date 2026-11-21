import { api } from "./api.js";
import { state } from "./state.js";
import { storage } from "./storage.js";
import { renderChatLoading, renderMessages, showTypingIndicator, hideTypingIndicator } from "./components/chat.js";
import { loadAndRenderCatalog } from "./components/catalog.js";
import { loadAndRenderDocuments, setupPreviewControls } from "./components/documents.js";
import { closeDossierModal } from "./components/dossier.js";
import { initCitationDrawer } from "./components/inspector.js";
import { refreshIcons } from "./utils/icons.js";

const mobileLayout = window.matchMedia("(max-width: 820px)");
const selectedChatIds = new Set();
const modalOpeners = new WeakMap();
let selectingChats = false;
let isSavingChats = false;
let chatSelection = 0;
let noticeTimer;

/**
 * Punto de entrada principal (ES Module) del Agente Alpina.
 */
document.addEventListener("DOMContentLoaded", async () => {
  initModals();
  initComposer();
  initSidebar();
  initCitationDrawer();
  setupPreviewControls();

  refreshIcons();

  checkHealthAndStats();
  await loadChats();
});

async function checkHealthAndStats() {
  const statusEl = document.getElementById("agent-status");
  const statsEl = document.getElementById("corpus-stats");

  try {
    const health = await api("/health");
    if (statusEl) {
      if (health.status === "ok") {
        statusEl.innerHTML = `<i data-lucide="check-circle" class="ui-icon" style="color:var(--green); width:13px; height:13px;"></i> <span>Servicio disponible</span>`;
        statusEl.classList.add("ready");
      } else {
        statusEl.innerHTML = `<i data-lucide="loader-2" class="ui-icon spin" style="width:13px; height:13px;"></i> <span>Iniciando...</span>`;
      }
      statusEl.title = statusEl.textContent.trim();
      refreshIcons(statusEl);
    }

    const stats = await api("/api/stats");
    if (statsEl) {
      statsEl.innerHTML = '<i data-lucide="layers" class="ui-icon"></i> <span></span>';
      statsEl.querySelector("span").textContent = `${stats.documents || 0} documentos · ${stats.products || 0} productos`;
      refreshIcons(statsEl);
    }
  } catch (err) {
    if (statusEl) {
      statusEl.innerHTML = `<i data-lucide="alert-triangle" class="ui-icon" style="color:var(--red); width:13px; height:13px;"></i> <span>Error de conexión</span>`;
      statusEl.title = "Error de conexión";
      refreshIcons(statusEl);
    }
  }
}

async function loadChats() {
  state.isLoadingChat = true;
  renderChatLoading();
  updateChatControls();

  try {
    state.chats = await api("/api/chats");
  } catch (err) {
    console.error("Error al cargar chats:", err);
    const list = document.getElementById("chat-list");
    setChatListMessage(list, "No se pudo cargar el historial.");
    list.setAttribute("aria-busy", "false");
    renderMessages(state.messages, handleAsk);
    state.isLoadingChat = false;
    updateChatControls();
    return;
  }

  const savedChatId = storage.local.getActiveChatId();
  const chat = state.chats.find(chat => chat.id === savedChatId) || state.chats[0];
  if (chat) await selectChat(chat.id);
  else showNewChat();
}

function setChatListMessage(list, text) {
  const message = document.createElement("p");
  message.className = "chat-list-message";
  message.textContent = text;
  list.replaceChildren(message);
}

function createChatItem(chat) {
  const title = chat.title || "Nuevo chat";
  const item = document.createElement(selectingChats ? "label" : "button");
  item.className = "chat-item";
  item.dataset.chatId = chat.id;
  item.title = title;

  if (selectingChats) {
    item.classList.add("chat-selection-item");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selectedChatIds.has(chat.id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedChatIds.add(chat.id);
      else selectedChatIds.delete(chat.id);
      updateChatControls();
    });
    item.appendChild(checkbox);
  } else {
    item.type = "button";
    const current = chat.id === state.activeChatId;
    item.classList.toggle("active", current);
    if (current) item.setAttribute("aria-current", "true");
    item.innerHTML = '<i data-lucide="message-square" class="ui-icon chat-item-icon"></i>';
    item.addEventListener("click", () => {
      setSidebarOpen(false);
      selectChat(chat.id);
    });
  }

  const label = document.createElement("span");
  label.className = "chat-item-title";
  label.textContent = title;
  item.appendChild(label);
  return item;
}

function renderChatList() {
  const list = document.getElementById("chat-list");
  const focusedChat = document.activeElement?.closest("[data-chat-id]")?.dataset.chatId;
  if (state.chats.length) list.replaceChildren(...state.chats.map(createChatItem));
  else setChatListMessage(list, "Sin chats aún.");
  refreshIcons(list);
  list.setAttribute("aria-busy", "false");

  if (focusedChat) {
    const item = list.querySelector(`[data-chat-id="${CSS.escape(focusedChat)}"]`);
    (item?.querySelector("input") || item)?.focus({ preventScroll: true });
  }
}

function chatIsBusy() {
  return state.isSending || state.isLoadingChat || isSavingChats;
}

function updateChatControls() {
  const busy = chatIsBusy();
  const submitBtn = document.getElementById("send-button");
  const selectBtn = document.getElementById("select-chats");
  const deleteSelectedBtn = document.getElementById("delete-selected-chats");

  submitBtn.disabled = busy;
  document.getElementById("new-chat").disabled = busy;
  document.getElementById("delete-chat").disabled = busy || !state.activeChatId;
  selectBtn.disabled = busy || (!selectingChats && !state.chats.length);
  selectBtn.textContent = selectingChats ? "Cancelar" : "Seleccionar";

  const count = selectedChatIds.size;
  deleteSelectedBtn.hidden = !selectingChats;
  deleteSelectedBtn.disabled = busy || !count;
  deleteSelectedBtn.querySelector("span").textContent = count
    ? `Eliminar ${count} ${count === 1 ? "chat" : "chats"}`
    : "Eliminar selección";

  document.querySelectorAll("#chat-list input").forEach(input => { input.disabled = busy; });
  document.querySelectorAll("#chat-list button").forEach(button => { button.disabled = isSavingChats; });
}

function updateChatTitle() {
  const titleEl = document.getElementById("chat-title");
  const chat = state.chats.find(chat => chat.id === state.activeChatId);
  titleEl.textContent = chat?.title || "Nuevo chat";
  titleEl.title = titleEl.textContent;
}

function showNewChat() {
  state.activeChatId = null;
  state.isLoadingChat = false;
  state.messages = [];
  storage.local.setActiveChatId(null);
  updateChatTitle();
  renderMessages([], handleAsk);
  renderChatList();
  updateChatControls();
}

async function selectChat(chatId) {
  const selection = ++chatSelection;
  state.activeChatId = chatId;
  state.isLoadingChat = true;
  state.messages = [];
  storage.local.setActiveChatId(chatId);
  updateChatTitle();
  renderChatLoading();
  renderChatList();
  updateChatControls();

  try {
    const messages = await api(`/api/chats/${chatId}/messages`);
    // Descartar si el usuario cambió a otro chat antes de que este fetch terminara (R11)
    if (state.activeChatId !== chatId || selection !== chatSelection) return;
    state.messages = messages;
    renderMessages(messages, handleAsk);
  } catch (err) {
    if (selection === chatSelection) {
      console.error("Error al obtener mensajes:", err);
      const container = document.getElementById("messages");
      const message = document.createElement("p");
      message.className = "message-load-error";
      message.textContent = "No se pudo cargar esta conversación.";
      container.replaceChildren(message);
      container.setAttribute("aria-busy", "false");
    }
  } finally {
    if (selection === chatSelection) {
      state.isLoadingChat = false;
      updateChatControls();
    }
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
    const content = input.value.replace(/^[ \r\n]+|[ \r\n]+$/g, "");
    if (!content.trim() || chatIsBusy()) return;
    input.value = "";
    storage.session.clearComposerDraft();
    await handleAsk(content);
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
}

async function handleAsk(content) {
  if (!content || chatIsBusy()) return;
  state.isSending = true;
  const input = document.getElementById("message-input");
  updateChatControls();
  let targetChatId = state.activeChatId;
  let userMsg;

  try {
    // Si no hay chat activo, crear uno dentro del bloque protegido (F16)
    if (!targetChatId) {
      const newChat = await api("/api/chats", { method: "POST", body: { title: content.slice(0, 40) } });
      state.activeChatId = newChat.id;
      targetChatId = newChat.id;
      storage.local.setActiveChatId(newChat.id);
      state.chats.unshift(newChat);
      updateChatTitle();
      renderChatList();
    }

    // Agregar mensaje de usuario optimistamente
    userMsg = { role: "user", content, created_at: new Date().toISOString() };
    state.messages.push(userMsg);
    renderMessages(state.messages, handleAsk);
    showTypingIndicator();

    const res = await api(`/api/chats/${targetChatId}/messages`, {
      method: "POST",
      body: { content },
    });

    hideTypingIndicator();
    Object.assign(userMsg, res.user_message || {});
    const assistantMsg = {
      ...res.assistant_message,
      role: "assistant",
      content: res.answer,
      citations: res.citations || [],
      metadata: res.metadata || {},
      generated_report: res.generated_report || res.metadata?.generated_report || null,
    };
    // Vincular respuesta a la conversación activa para evitar fuga de mensajes si el usuario cambió de chat (F16)
    if (state.activeChatId === targetChatId) {
      if (state.messages.includes(userMsg)) {
        state.messages.push(assistantMsg);
        renderMessages(state.messages, handleAsk);
      } else {
        await selectChat(targetChatId);
      }
    }

    try {
      state.chats = await api("/api/chats");
      updateChatTitle();
      renderChatList();
    } catch (err) {
      console.error("Error al actualizar conversaciones:", err);
    }
  } catch (err) {
    if (state.activeChatId === targetChatId) {
      if (input && !input.value) {
        input.value = content;
        storage.session.setComposerDraft(content);
      }
      const failedMessage = state.messages.indexOf(userMsg);
      if (failedMessage !== -1) {
        state.messages.splice(failedMessage, 1);
        renderMessages(state.messages, handleAsk);
      }
      alert(`Error del agente: ${err.message}`);
    }
  } finally {
    hideTypingIndicator();
    state.isSending = false;
    updateChatControls();
  }
}

function showChatNotice(message, { error = false, pending = false } = {}) {
  const notice = document.getElementById("chat-notice");
  clearTimeout(noticeTimer);
  notice.textContent = message;
  notice.classList.toggle("error", error);
  if (!pending) {
    noticeTimer = setTimeout(() => { notice.textContent = ""; }, 6500);
  }
}

async function deleteChats(chatIds, trigger) {
  if (chatIsBusy() || !chatIds.length) return;
  const count = chatIds.length;
  const description = count === 1 ? "este chat" : `estos ${count} chats`;
  if (!window.confirm(`¿Deseas eliminar ${description}? Esta acción es permanente.`)) return;

  const hadFocus = document.activeElement === trigger;
  isSavingChats = true;
  updateChatControls();
  showChatNotice(count === 1 ? "Eliminando chat…" : `Eliminando ${count} chats…`, { pending: true });

  const deleted = new Set();
  for (const chatId of chatIds) {
    try {
      await api(`/api/chats/${encodeURIComponent(chatId)}`, { method: "DELETE" });
      deleted.add(chatId);
    } catch (err) {
      if (err.status === 404) deleted.add(chatId);
    }
  }

  state.chats = state.chats.filter(chat => !deleted.has(chat.id));
  for (const id of deleted) selectedChatIds.delete(id);
  if (deleted.size && !selectedChatIds.size) selectingChats = false;

  if (deleted.has(state.activeChatId)) {
    if (state.chats[0]) await selectChat(state.chats[0].id);
    else showNewChat();
  } else {
    renderChatList();
  }

  isSavingChats = false;
  updateChatControls();
  const failures = count - deleted.size;
  const removed = deleted.size === 1 ? "Se eliminó 1 chat." : `Se eliminaron ${deleted.size} chats.`;
  const failed = failures === 1 ? "No se pudo eliminar 1 chat." : `No se pudieron eliminar ${failures} chats.`;
  showChatNotice([deleted.size && removed, failures && failed].filter(Boolean).join(" "), { error: failures > 0 });

  if (hadFocus && document.activeElement === document.body) {
    const nextControl = trigger.hidden ? document.getElementById("select-chats") : trigger;
    const fallback = trigger.hidden ? "new-chat" : "message-input";
    if (!nextControl.disabled) nextControl.focus();
    else document.getElementById(fallback).focus();
  }
}

function setSidebarOpen(open) {
  const sidebar = document.getElementById("chat-sidebar");
  const toggle = document.getElementById("sidebar-toggle");
  const panel = document.querySelector(".chat-panel");
  const wasOpen = sidebar.classList.contains("open");
  const shouldOpen = open && mobileLayout.matches;
  sidebar.classList.toggle("open", shouldOpen);
  document.getElementById("sidebar-backdrop").classList.toggle("open", shouldOpen);
  toggle.setAttribute("aria-expanded", String(shouldOpen));

  if (shouldOpen) {
    sidebar.inert = false;
    document.getElementById("sidebar-close").focus();
    panel.inert = true;
  } else {
    panel.inert = false;
    if (wasOpen && mobileLayout.matches) toggle.focus();
    sidebar.inert = mobileLayout.matches;
  }
}

function initSidebar() {
  setSidebarOpen(false);
  mobileLayout.addEventListener("change", () => setSidebarOpen(false));
  document.getElementById("sidebar-toggle").addEventListener("click", () => setSidebarOpen(true));
  document.getElementById("sidebar-close").addEventListener("click", () => setSidebarOpen(false));
  document.getElementById("sidebar-backdrop").addEventListener("click", () => setSidebarOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.getElementById("chat-sidebar").classList.contains("open")) {
      setSidebarOpen(false);
    }
  });

  document.getElementById("new-chat").addEventListener("click", async () => {
    if (chatIsBusy()) return;
    setSidebarOpen(false);
    isSavingChats = true;
    updateChatControls();
    try {
      const newChat = await api("/api/chats", { method: "POST", body: { title: "Nuevo chat" } });
      state.chats.unshift(newChat);
      await selectChat(newChat.id);
    } catch (err) {
      showChatNotice("No se pudo crear el chat.", { error: true });
    } finally {
      isSavingChats = false;
      updateChatControls();
    }
  });

  document.getElementById("delete-chat").addEventListener("click", (event) => {
    if (state.activeChatId) deleteChats([state.activeChatId], event.currentTarget);
  });

  document.getElementById("select-chats").addEventListener("click", () => {
    selectingChats = !selectingChats;
    selectedChatIds.clear();
    renderChatList();
    updateChatControls();
  });

  document.getElementById("delete-selected-chats").addEventListener("click", (event) => {
    deleteChats([...selectedChatIds], event.currentTarget);
  });

  document.getElementById("products-button")?.addEventListener("click", () => {
    setSidebarOpen(false);
    openModal("catalog");
    loadAndRenderCatalog((productName) => {
      closeModal("catalog");
      handleAsk(`¿Qué información oficial tienes del producto ${productName}?`);
    });
  });

  document.getElementById("documents-button")?.addEventListener("click", () => {
    setSidebarOpen(false);
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
      document.querySelectorAll(".modal.open").forEach(modal => closeModal(modal.id.replace(/-modal$/, "")));
    }
  });
}

function openModal(id) {
  const modal = document.getElementById(`${id}-modal`);
  if (modal) {
    modalOpeners.set(modal, document.activeElement);
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    modal.querySelector(".modal-close")?.focus();
  }
}

function closeModal(id) {
  if (id === "dossier") {
    closeDossierModal();
    return;
  }
  const modal = document.getElementById(`${id}-modal`);
  if (modal?.classList.contains("open")) {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    modalOpeners.get(modal)?.focus();
  }
}
