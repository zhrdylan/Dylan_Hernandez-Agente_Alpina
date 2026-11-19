/**
 * Estado global compartido de la aplicación web.
 */
export const state = {
  activeChatId: null,
  chats: [],
  messages: [],
  documentsCache: null,
  productsCache: null,
  activeDossier: null,
  isSending: false,
};

export const listeners = new Set();

export function setState(updates) {
  Object.assign(state, updates);
  for (const listener of listeners) {
    try {
      listener(state);
    } catch (err) {
      console.error("Error en listener de estado:", err);
    }
  }
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
