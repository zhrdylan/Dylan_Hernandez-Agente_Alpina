import { api } from "../api.js";
import { state } from "../state.js";
import { refreshIcons } from "../utils/icons.js";

/**
 * Componente del Visor de Documentos Oficiales y Páginas PDF.
 */
export async function loadAndRenderDocuments() {
  const container = document.getElementById("document-list");
  if (!container) return;

  container.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--muted);"><i data-lucide="loader-2" class="ui-icon spin"></i> Cargando documentos oficiales...</div>`;
  refreshIcons(container);

  try {
    const documents = await api("/api/documents");
    state.documentsCache = documents;
    renderDocumentItems(documents, container);
  } catch (err) {
    container.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--red);"><i data-lucide="alert-circle" class="ui-icon"></i> Error al cargar documentos: ${err.message}</div>`;
    refreshIcons(container);
  }
}

function renderDocumentItems(documents, container) {
  if (!documents || documents.length === 0) {
    container.innerHTML = `<p style="text-align: center; color: var(--muted); padding: 20px;"><i data-lucide="file-x" class="ui-icon"></i> Sin documentos registrados.</p>`;
    refreshIcons(container);
    return;
  }

  container.innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 10px; padding: 18px 24px; max-height: calc(85vh - 120px); overflow-y: auto;">
      ${documents.map(d => `
        <div style="background: #ffffff; border: 1px solid var(--line); border-radius: var(--radius-md); padding: 14px 18px; display: flex; justify-content: space-between; align-items: center; gap: 12px;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <div style="background: var(--blue-light); color: var(--blue); width: 36px; height: 36px; border-radius: var(--radius-md); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
              <i data-lucide="file-text" class="ui-icon" style="width: 18px; height: 18px;"></i>
            </div>
            <div>
              <div style="font-weight: 700; color: var(--ink); font-size: 0.95rem;">
                <span style="background: var(--blue-light); color: var(--blue); padding: 2px 7px; border-radius: 4px; font-size: 0.75rem; margin-right: 6px;">${escapeHtml(d.id)}</span>
                ${escapeHtml(d.title)}
              </div>
              <div style="font-size: 0.78rem; color: var(--muted); margin-top: 4px;">
                Categoría: <strong>${escapeHtml(d.category)}</strong> · ${d.page_count || 1} páginas · Vigente: ${d.vigente ? "Sí" : "No"}
              </div>
            </div>
          </div>
          <button class="ghost-button view-page-btn" type="button" data-doc-id="${escapeHtml(d.id)}" data-page="1">
            <i data-lucide="eye" class="ui-icon"></i>
            <span>Ver página 1</span>
          </button>
        </div>
      `).join("")}
    </div>
  `;

  container.querySelectorAll(".view-page-btn").forEach(btn => {
    btn.onclick = () => {
      openPagePreview(btn.dataset.docId, parseInt(btn.dataset.page || "1", 10));
    };
  });

  refreshIcons(container);
}

export function openPagePreview(docId, pageNumber, quote = null) {
  const modal = document.getElementById("preview-modal");
  const imgEl = document.getElementById("preview-img");
  const titleEl = document.getElementById("preview-title");
  const quoteEl = document.getElementById("preview-quote");

  if (!modal || !imgEl) return;

  if (titleEl) titleEl.textContent = `Documento ${docId} · Página ${pageNumber}`;
  if (quoteEl) {
    if (quote) {
      quoteEl.innerHTML = `<strong>Cita citada:</strong><br>"${escapeHtml(quote)}"`;
      quoteEl.style.display = "block";
    } else {
      quoteEl.style.display = "none";
    }
  }

  const quoteParam = quote ? `?quote=${encodeURIComponent(quote)}` : "";
  imgEl.src = `/api/documents/${encodeURIComponent(docId)}/pages/${pageNumber}${quoteParam}`;

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text || "");
  return div.innerHTML;
}
