/**
 * Utilidad de iconos Lucide para el Agente Alpina.
 */

export function refreshIcons(root = document) {
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    try {
      window.lucide.createIcons({
        root: root instanceof HTMLElement || root instanceof Document ? root : document,
        attrs: {
          "stroke-width": "2",
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
        },
      });
    } catch (err) {
      console.warn("Error al renderizar iconos Lucide:", err);
    }
  }
}

export function iconHtml(name, { size = 16, className = "" } = {}) {
  return `<i data-lucide="${name}" class="ui-icon ${className}" style="width:${size}px; height:${size}px;"></i>`;
}

