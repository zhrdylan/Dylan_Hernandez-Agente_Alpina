/**
 * Módulo centralizado para la gestión segura del almacenamiento del navegador:
 * 1. localStorage: Persistencia entre sesiones y pestañas (chat activo, preferencias).
 * 2. sessionStorage: Aislamiento por pestaña (borrador del compositor, caché de preview).
 * 3. cookies: Identificación de dispositivo (alpina_device_id) con SameSite=Lax.
 */

// Prefijo común para evitar colisiones en el dominio
const PREFIX = "alpina_";

/**
 * 1. LocalStorage: persistente entre sesiones y pestañas
 */
export const local = {
  get(key, defaultValue = null) {
    try {
      const val = localStorage.getItem(`${PREFIX}${key}`);
      return val ? JSON.parse(val) : defaultValue;
    } catch {
      return defaultValue;
    }
  },

  set(key, value) {
    try {
      localStorage.setItem(`${PREFIX}${key}`, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  },

  remove(key) {
    try {
      localStorage.removeItem(`${PREFIX}${key}`);
    } catch {}
  },

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

  removeActiveChatId() {
    try {
      localStorage.removeItem(`${PREFIX}active_chat_id`);
    } catch {}
  },

  getUserPrefs() {
    return this.get("user_prefs", {
      sidebarOpen: true,
      preferredFormat: "pdf",
    });
  },

  setUserPrefs(prefs) {
    const current = this.getUserPrefs();
    return this.set("user_prefs", { ...current, ...prefs });
  },
};

/**
 * 2. SessionStorage: temporal por pestaña actual
 */
export const session = {
  get(key, defaultValue = null) {
    try {
      const val = sessionStorage.getItem(`${PREFIX}${key}`);
      return val ? JSON.parse(val) : defaultValue;
    } catch {
      return defaultValue;
    }
  },

  set(key, value) {
    try {
      sessionStorage.setItem(`${PREFIX}${key}`, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  },

  remove(key) {
    try {
      sessionStorage.removeItem(`${PREFIX}${key}`);
    } catch {}
  },

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

  getPreviewCache(chatId) {
    if (!chatId) return null;
    return this.get(`preview_cache_${chatId}`, null);
  },

  setPreviewCache(chatId, data) {
    if (!chatId) return;
    this.set(`preview_cache_${chatId}`, data);
  },
};

/**
 * 3. Cookies: cliente seguro con SameSite=Lax
 */
export const cookies = {
  get(name) {
    try {
      const target = `${PREFIX}${name}=`;
      const parts = document.cookie.split(";");
      for (let i = 0; i < parts.length; i++) {
        let part = parts[i].trim();
        if (part.indexOf(target) === 0) {
          return decodeURIComponent(part.substring(target.length));
        }
      }
      return null;
    } catch {
      return null;
    }
  },

  set(name, value, days = 365) {
    try {
      let expires = "";
      if (days) {
        const date = new Date();
        date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
        expires = `; expires=${date.toUTCString()}`;
      }
      document.cookie = `${PREFIX}${name}=${encodeURIComponent(value)}${expires}; path=/; SameSite=Lax`;
      return true;
    } catch {
      return false;
    }
  },

  remove(name) {
    try {
      document.cookie = `${PREFIX}${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; SameSite=Lax`;
    } catch {}
  },

  /**
   * Obtiene o inicializa un identificador único anónimo para este dispositivo.
   */
  getDeviceId() {
    let deviceId = this.get("device_id");
    if (!deviceId) {
      deviceId = "dev-" + Math.random().toString(36).substring(2, 15) + "-" + Date.now().toString(36);
      this.set("device_id", deviceId, 365);
    }
    return deviceId;
  },

  /**
   * Obtiene la sesión anónima persistente (alpina_session_id) emitida por el servidor.
   */
  getSessionId() {
    return this.get("alpina_session_id") || "";
  },
};

export const storage = {
  local,
  session,
  cookies,
};

export default storage;
