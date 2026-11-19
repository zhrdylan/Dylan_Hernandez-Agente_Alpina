import { refreshIcons } from "../utils/icons.js";

/**
 * Inspector Lateral de Citas (Side Drawer) con evidencia y soporte completo tanto
 * para documentos PDF oficiales como para fichas técnicas de productos del catálogo.
 */
export function openCitationDrawer(citation) {
  const drawer = document.getElementById("citation-drawer");
  const backdrop = document.getElementById("citation-drawer-backdrop");
  const titleEl = document.getElementById("drawer-doc-title");
  const metaEl = document.getElementById("drawer-doc-meta");
  const quoteEl = document.getElementById("drawer-quote-text");
  const imgEl = document.getElementById("drawer-page-img");
  const spinnerEl = document.getElementById("drawer-page-spinner");
  const hintEl = document.getElementById("drawer-hint");
  const copyBtn = document.getElementById("drawer-copy-quote-btn");

  if (!drawer) return;

  const docId = String(citation.document_id || "Documento").trim();
  const title = citation.title || docId;
  const page = citation.page || 1;
  const version = citation.version || "vigente";
  const quote = citation.quote || "";

  const isProduct =
    docId.toUpperCase().startsWith("SKU-") ||
    docId.toLowerCase().startsWith("sku-") ||
    docId.toLowerCase().startsWith("product-");

  if (titleEl) titleEl.textContent = title;

  if (isProduct) {
    if (metaEl) metaEl.textContent = `Catálogo Maestro Oficial · SKU: ${docId.toUpperCase()}`;
    if (hintEl) hintEl.textContent = "Ficha técnica oficial generada y verificada contra el catálogo de productos de Alpina.";
  } else {
    if (metaEl) metaEl.textContent = `Documento oficial · Pág. ${page} · Versión ${version}`;
    if (hintEl) hintEl.textContent = "El resaltado tenue y contorneado delimita la coincidencia textual exacta en el documento oficial.";
  }

  if (quoteEl) quoteEl.textContent = quote ? `"${quote}"` : "Cita oficial referenciada en este fragmento.";

  if (copyBtn) {
    copyBtn.innerHTML = `<i data-lucide="copy" class="ui-icon"></i> <span>Copiar</span>`;
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(quote || title);
      copyBtn.innerHTML = `<i data-lucide="check" class="ui-icon" style="color:var(--green)"></i> <span>¡Copiada!</span>`;
      refreshIcons(copyBtn);
      setTimeout(() => {
        copyBtn.innerHTML = `<i data-lucide="copy" class="ui-icon"></i> <span>Copiar</span>`;
        refreshIcons(copyBtn);
      }, 2000);
    };
  }

  if (imgEl) {
    imgEl.style.opacity = "0";
    if (spinnerEl) spinnerEl.style.display = "block";

    imgEl.onload = () => {
      if (spinnerEl) spinnerEl.style.display = "none";
      imgEl.style.opacity = "1";
    };

    imgEl.onerror = () => {
      if (spinnerEl) spinnerEl.style.display = "none";
      imgEl.style.opacity = "0.7";
      console.warn("No se pudo cargar la vista previa para:", docId);
    };

    const params = new URLSearchParams();
    if (version && version !== "vigente") params.set("version", version);
    if (quote) params.set("quote", quote);
    const qs = params.toString() ? `?${params.toString()}` : "";
    imgEl.src = `/api/documents/${encodeURIComponent(docId)}/pages/${page}${qs}`;
  }

  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  if (backdrop) {
    backdrop.classList.add("open");
  }

  refreshIcons(drawer);
}

export function closeCitationDrawer() {
  const drawer = document.getElementById("citation-drawer");
  const backdrop = document.getElementById("citation-drawer-backdrop");
  if (drawer) {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
  }
  if (backdrop) {
    backdrop.classList.remove("open");
  }
}

export function initCitationDrawer() {
  const closeBtn = document.getElementById("drawer-close-btn");
  const backdrop = document.getElementById("citation-drawer-backdrop");

  if (closeBtn) closeBtn.onclick = closeCitationDrawer;
  if (backdrop) backdrop.onclick = closeCitationDrawer;

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeCitationDrawer();
    }
  });
}
