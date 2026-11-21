import { api } from "../api.js";
import { refreshIcons } from "../utils/icons.js";

const ALPINA_ORIGINS = new Set(["https://alpina.com", "https://www.alpina.com"]);
let previewRequest;
let citationOpener;
let copyTimer;

export function isProductCitation(citation) {
  if (citation.kind) return citation.kind === "product";
  const id = String(citation.document_id || "").trim();
  return /^(?:sku-|product-|\d+$)/i.test(id)
    || Boolean(id && !/^[npc]\d{1,2}$/i.test(id) && officialAlpinaUrl(citation.source_url));
}

function officialAlpinaUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && ALPINA_ORIGINS.has(url.origin) && !url.username && !url.password) {
      return url.href;
    }
  } catch {
    // La cita puede no incluir una URL.
  }
  return null;
}

function showSourceLink(url) {
  const link = document.getElementById("drawer-product-link");
  if (url) link.href = url;
  else link.removeAttribute("href");
  link.hidden = !url;
}

async function findCatalogLink(docId, signal) {
  const id = docId.toUpperCase();
  const sku = id.replace(/^PRODUCT-/, "").replace(/^SKU-/, "");
  const params = new URLSearchParams({ q: sku, limit: "24" });
  const { items } = await api(`/api/products?${params}`, { signal });
  const matches = new Set([id, sku, `SKU-${sku}`]);
  const product = items.find(item => item.id.toUpperCase() === id)
    || items.find(item => matches.has(item.id.toUpperCase()));
  return officialAlpinaUrl(product?.source_url);
}

async function loadCitationPreview(citation, docId, product, signal) {
  const wrapper = document.getElementById("drawer-page-view-wrapper");
  const image = document.getElementById("drawer-page-img");
  const skeleton = document.getElementById("drawer-page-skeleton");
  const hint = document.getElementById("drawer-hint");
  const source = officialAlpinaUrl(citation.source_url);

  wrapper.hidden = false;
  wrapper.setAttribute("aria-busy", "true");
  skeleton.hidden = false;
  image.hidden = true;
  image.removeAttribute("src");
  hint.textContent = "Cargando vista previa…";
  showSourceLink(product ? source : null);

  const params = new URLSearchParams();
  if (!product && citation.version && citation.version !== "vigente") params.set("version", citation.version);
  if (citation.quote && citation.quote.length <= 500) params.set("quote", citation.quote);
  const previewId = product && !/^(sku|product)-/i.test(docId) ? `PRODUCT-${docId}` : docId;
  const page = product ? 1 : Number(citation.page) || 1;
  const query = params.size ? `?${params}` : "";

  try {
    const response = await fetch(`/api/documents/${encodeURIComponent(previewId)}/pages/${page}${query}`, { signal });
    if (!response.ok) throw new Error("Vista previa no disponible");
    const blob = await response.blob();
    if (signal.aborted) return;

    const objectUrl = URL.createObjectURL(blob);
    try {
      image.src = objectUrl;
      await image.decode();
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
    if (signal.aborted) return;

    image.hidden = false;
    const highlight = response.headers.get("X-Highlight-Status");
    if (highlight === "exact") hint.textContent = "Coincidencia exacta resaltada en la fuente oficial.";
    else if (highlight === "partial") hint.textContent = "Coincidencia parcial resaltada en la fuente oficial.";
    else hint.textContent = product ? "Ficha del catálogo oficial de Alpina." : "Página oficial de referencia.";
  } catch {
    if (signal.aborted) return;
    wrapper.hidden = true;
    image.removeAttribute("src");
    hint.textContent = product ? "No se pudo previsualizar la ficha del producto." : "No se pudo previsualizar esta página.";
    if (!citation.kind && source) showSourceLink(source);
    if (product && !source) {
      try {
        const catalogUrl = await findCatalogLink(docId, signal);
        if (!signal.aborted) showSourceLink(catalogUrl);
      } catch {
        // La ficha puede haber salido del catálogo.
      }
    }
  } finally {
    if (!signal.aborted) {
      skeleton.hidden = true;
      wrapper.setAttribute("aria-busy", "false");
    }
  }
}

export function openCitationDrawer(citation, opener) {
  previewRequest?.abort();
  previewRequest = new AbortController();
  const { signal } = previewRequest;
  citationOpener = opener;

  const drawer = document.getElementById("citation-drawer");
  const docId = String(citation.document_id || "").trim();
  const title = citation.title || docId || "Fuente oficial";
  const product = isProductCitation(citation);
  const quote = citation.quote || "";

  document.getElementById("drawer-doc-title").textContent = title;
  document.getElementById("drawer-doc-meta").textContent = product
    ? `Catálogo oficial · SKU ${docId.replace(/^(?:product-)?sku-/i, "")}`
    : `Documento oficial · Pág. ${citation.page || 1} · Versión ${citation.version || "vigente"}`;
  document.getElementById("drawer-quote-text").textContent = quote || "Fragmento de referencia.";

  const copyBtn = document.getElementById("drawer-copy-quote-btn");
  const resetCopyButton = () => {
    copyBtn.querySelector("span").textContent = "Copiar";
  };
  clearTimeout(copyTimer);
  resetCopyButton();
  copyBtn.onclick = async () => {
    clearTimeout(copyTimer);
    try {
      await navigator.clipboard.writeText(quote || title);
      if (!signal.aborted) copyBtn.querySelector("span").textContent = "¡Copiada!";
    } catch {
      if (!signal.aborted) copyBtn.querySelector("span").textContent = "No se pudo copiar";
    }
    if (!signal.aborted) copyTimer = setTimeout(resetCopyButton, 2000);
  };

  drawer.inert = false;
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  document.getElementById("citation-drawer-backdrop").classList.add("open");
  refreshIcons(drawer);
  drawer.querySelector(".drawer-body").scrollTop = 0;
  document.getElementById("drawer-close-btn").focus();
  document.querySelector(".app-shell").inert = true;
  loadCitationPreview(citation, docId, product, signal);
}

export function closeCitationDrawer() {
  const drawer = document.getElementById("citation-drawer");
  if (!drawer.classList.contains("open")) return;

  previewRequest?.abort();
  clearTimeout(copyTimer);
  drawer.inert = true;
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  document.getElementById("citation-drawer-backdrop").classList.remove("open");
  document.querySelector(".app-shell").inert = false;
  const restoreFocus = citationOpener?.isConnected ? citationOpener : document.getElementById("message-input");
  restoreFocus.focus({ preventScroll: true });
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
