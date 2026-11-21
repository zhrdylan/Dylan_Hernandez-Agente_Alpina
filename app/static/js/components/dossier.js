/**
 * Visor interactivo de documentos PDF generados por el Agente Alpina.
 */

export function openPdfPreviewModal(report) {
  const modal = document.getElementById("dossier-modal");
  if (!modal || !report) return;

  const titleEl = document.getElementById("preview-doc-title");
  const modalTitle = document.getElementById("dossier-title");
  const modalQuery = document.getElementById("dossier-query");
  const iframe = document.getElementById("pdf-preview-iframe");
  const downloadBtn = document.getElementById("preview-download-btn");
  const openTabBtn = document.getElementById("preview-open-tab-btn");
  const fallbackOpen = document.getElementById("preview-fallback-open");
  const fallbackDl = document.getElementById("preview-fallback-dl");

  const title = report.title || "Informe Oficial · Alpina";
  const filename = report.filename || "informe.pdf";
  const downloadUrl = report.download_url || "#";
  const inlineUrl = downloadUrl.includes("?") ? `${downloadUrl}&inline=true` : `${downloadUrl}?inline=true`;

  if (modalTitle) modalTitle.textContent = "Visor de Documento PDF · Alpina";
  if (modalQuery) modalQuery.textContent = title;
  if (titleEl) titleEl.textContent = `${title} (${filename})`;

  if (downloadBtn) {
    downloadBtn.href = downloadUrl;
    downloadBtn.setAttribute("download", filename);
  }
  if (openTabBtn) openTabBtn.href = inlineUrl;
  if (fallbackOpen) fallbackOpen.href = inlineUrl;
  if (fallbackDl) {
    fallbackDl.href = downloadUrl;
    fallbackDl.setAttribute("download", filename);
  }

  if (iframe) {
    iframe.src = inlineUrl;
  }

  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

export function closeDossierModal() {
  const modal = document.getElementById("dossier-modal");
  if (!modal) return;
  const iframe = document.getElementById("pdf-preview-iframe");
  if (iframe) iframe.src = "";
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}
