const PREFIX = "alpina_";

export const storage = {
  local: {
    getActiveChatId() {
      try {
        return localStorage.getItem(`${PREFIX}active_chat_id`) || null;
      } catch {
        return null;
      }
    },

    setActiveChatId(chatId) {
      try {
        if (chatId) {
          localStorage.setItem(`${PREFIX}active_chat_id`, String(chatId));
        } else {
          localStorage.removeItem(`${PREFIX}active_chat_id`);
        }
      } catch {}
    },
  },
  session: {
    getComposerDraft() {
      try {
        return sessionStorage.getItem(`${PREFIX}composer_draft`) || "";
      } catch {
        return "";
      }
    },

    setComposerDraft(text) {
      try {
        if (text && text.trim()) {
          sessionStorage.setItem(`${PREFIX}composer_draft`, text);
        } else {
          sessionStorage.removeItem(`${PREFIX}composer_draft`);
        }
      } catch {}
    },

    clearComposerDraft() {
      try {
        sessionStorage.removeItem(`${PREFIX}composer_draft`);
      } catch {}
    },
  },
};
