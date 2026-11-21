import { api } from "../api.js";
import { state } from "../state.js";
import { escapeHtml } from "../utils/html.js";
import { refreshIcons } from "../utils/icons.js";

/**
 * Componente del Visor de Documentos Oficiales y Páginas PDF.
 */
export async function loadAndRenderDocuments() {
  const container = document.getElementById("document-list");
  if (!container) return;

  container.setAttribute("aria-busy", "true");
  container.innerHTML = '<div class="document-item" aria-hidden="true"><div class="skeleton skeleton-line"></div></div>'.repeat(3);

  try {
    const documents = await api("/api/documents");
    state.documentsCache = documents;
    renderDocumentItems(documents, container);
  } catch (err) {
    container.textContent = "Error al cargar documentos. " + err.message;
  } finally {
    container.setAttribute("aria-busy", "false");
  }
}

function renderDocumentItems(documents, container) {
  if (!documents || documents.length === 0) {
    container.innerHTML = `<p style="text-align: center; color: var(--muted); padding: 20px;"><i data-lucide="file-x" class="ui-icon"></i> Sin documentos registrados.</p>`;
    refreshIcons(container);
    return;
  }

  container.innerHTML = documents.map(d => `
        <div class="document-item">
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
                Categoría: <strong>${escapeHtml(d.category)}</strong> · ${escapeHtml(d.page_count || 1)} páginas · Vigente: ${d.vigente ? "Sí" : "No"}
              </div>
            </div>
          </div>
          <button class="ghost-button view-page-btn" type="button">
            <i data-lucide="eye" class="ui-icon"></i>
            <span>Ver página 1</span>
          </button>
        </div>
  `).join("");

  container.querySelectorAll(".view-page-btn").forEach((btn, index) => {
    btn.onclick = () => openPagePreview(documents[index].id, 1);
  });

  refreshIcons(container);
}

let currentDocId = null;
let currentPage = 1;
let currentTotalPages = 1;

export function setupPreviewControls() {
  const prevBtn = document.getElementById("preview-prev-btn");
  const nextBtn = document.getElementById("preview-next-btn");

  if (prevBtn) {
    prevBtn.onclick = () => {
      if (currentPage > 1) {
        openPagePreview(currentDocId, currentPage - 1);
      }
    };
  }
  if (nextBtn) {
    nextBtn.onclick = () => {
      if (currentPage < currentTotalPages) {
        openPagePreview(currentDocId, currentPage + 1);
      }
    };
  }
}

function openPagePreview(docId, pageNumber) {
  const modal = document.getElementById("preview-modal");
  const imgEl = document.getElementById("preview-img");
  const titleEl = document.getElementById("preview-title");
  const prevBtn = document.getElementById("preview-prev-btn");
  const nextBtn = document.getElementById("preview-next-btn");
  const indicator = document.getElementById("preview-page-indicator");
  const fullPdfBtn = document.getElementById("preview-full-pdf-btn");

  if (!modal || !imgEl) return;

  currentDocId = docId;
  currentPage = pageNumber;

  // Resolver metadatos del documento desde el caché
  const docInfo = (state.documentsCache || []).find(d => d.id === docId);
  currentTotalPages = (docInfo && docInfo.page_count && docInfo.page_count > 0)
    ? docInfo.page_count
    : Math.max(pageNumber, 1);
  const docTitle = (docInfo && docInfo.title) ? docInfo.title : `Documento ${docId}`;

  if (titleEl) titleEl.textContent = `${docTitle} · Página ${pageNumber}`;
  if (indicator) indicator.textContent = `Página ${pageNumber} de ${currentTotalPages}`;
  if (prevBtn) prevBtn.disabled = currentPage <= 1;
  if (nextBtn) nextBtn.disabled = currentPage >= currentTotalPages;

  if (fullPdfBtn) {
    fullPdfBtn.href = `/api/documents/${encodeURIComponent(docId)}/pdf`;
    fullPdfBtn.style.display = docId.toUpperCase().startsWith("SKU-") ? "none" : "inline-flex";
  }

  imgEl.src = `/api/documents/${encodeURIComponent(docId)}/pages/${pageNumber}`;

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  refreshIcons(modal);
}
