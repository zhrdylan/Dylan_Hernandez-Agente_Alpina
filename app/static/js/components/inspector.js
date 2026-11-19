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

    const params = new URLSearchParams();
    if (version && version !== "vigente") params.set("version", version);
    if (quote) params.set("quote", quote);
    const qs = params.toString() ? `?${params.toString()}` : "";
    const url = `/api/documents/${encodeURIComponent(docId)}/pages/${page}${qs}`;

    fetch(url)
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || "La versión solicitada no está disponible.");
        }
        const hlStatus = res.headers.get("X-Highlight-Status") || "none";
        if (hintEl) {
          if (isProduct) {
            hintEl.textContent = hlStatus === "exact"
              ? "Coincidencia textual verificada en la ficha oficial del catálogo."
              : "Referencia a producto en catálogo maestro oficial.";
          } else {
            if (hlStatus === "exact") {
              hintEl.textContent = "Coincidencia textual exacta resaltada en la página del documento oficial.";
            } else if (hlStatus === "partial") {
              hintEl.textContent = "Coincidencia parcial o por fragmentos resaltada en el documento oficial.";
            } else {
              hintEl.textContent = "Página oficial de referencia (la cita exacta no tuvo coincidencia textual directa en esta página).";
            }
          }
        }
        return res.blob();
      })
      .then((blob) => {
        const objectUrl = URL.createObjectURL(blob);
        imgEl.onload = () => {
          if (spinnerEl) spinnerEl.style.display = "none";
          imgEl.style.opacity = "1";
        };
        imgEl.src = objectUrl;
      })
      .catch((err) => {
        if (spinnerEl) spinnerEl.style.display = "none";
        imgEl.style.opacity = "0.4";
        if (hintEl) {
          hintEl.textContent = `Aviso: ${err.message || "La versión histórica o página del documento no está disponible."}`;
        }
      });
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
