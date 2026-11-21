import { api, formatCurrency } from "../api.js";
import { escapeHtml } from "../utils/html.js";
import { refreshIcons } from "../utils/icons.js";

/**
 * Componente del Catálogo Oficial de Productos Alpina.
 */
export async function loadAndRenderCatalog(onSelectProduct) {
  const container = document.getElementById("product-grid");
  const totalEl = document.getElementById("product-total");
  const searchInput = document.getElementById("product-search");
  if (!container) return;

  container.setAttribute("aria-busy", "true");
  if (totalEl) totalEl.textContent = "Cargando catálogo…";
  if (searchInput) searchInput.disabled = true;
  container.innerHTML = `
    <div class="product-card" aria-hidden="true">
      <div class="skeleton product-img-placeholder"></div>
      <div class="skeleton skeleton-line"></div>
      <div class="skeleton skeleton-line"></div>
    </div>
  `.repeat(3);

  try {
    const data = await api("/api/products?limit=96");
    const products = data.items || [];
    const applyFilter = () => {
      const query = searchInput?.value.toLowerCase().trim() || "";
      const filtered = query ? products.filter(p =>
        (p.name && p.name.toLowerCase().includes(query)) ||
        (p.ean && p.ean.includes(query)) ||
        (p.id && p.id.toLowerCase().includes(query)) ||
        ((p.claims || []).some(c => String(c).toLowerCase().includes(query)))
      ) : products;
      if (totalEl) totalEl.textContent = `${query ? filtered.length : data.total ?? products.length} productos`;
      renderProductCards(filtered, container, onSelectProduct);
    };
    if (searchInput) searchInput.oninput = applyFilter;
    applyFilter();
  } catch (err) {
    if (totalEl) totalEl.textContent = "";
    container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--red);"><i data-lucide="alert-circle" class="ui-icon"></i> Error al cargar productos: ${escapeHtml(err.message || String(err))}</div>`;
    refreshIcons(container);
  } finally {
    container.setAttribute("aria-busy", "false");
    if (searchInput) searchInput.disabled = false;
  }
}

function renderProductCards(products, container, onSelectProduct) {
  if (!products || products.length === 0) {
    container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--muted);"><i data-lucide="search-x" class="ui-icon"></i> No se encontraron productos con ese criterio.</div>`;
    refreshIcons(container);
    return;
  }

  container.innerHTML = products.map(p => `
    <div class="product-card">
      <div class="product-img-wrapper">
        <img
          class="product-img"
          alt="${escapeHtml(p.name)}"
          loading="lazy"
        />
      </div>
      <div class="product-card-header">
        <h3 class="product-card-title">${escapeHtml(p.name)}</h3>
        <span class="product-card-sku">${escapeHtml(p.id)}</span>
      </div>
      <div style="font-size: 0.8rem; color: var(--muted);">
        ${escapeHtml(p.presentation || "Presentación oficial")}
      </div>
      <div class="product-card-price">
        ${escapeHtml(formatCurrency(p.price))}
      </div>
      <div class="product-card-tags">
        ${p.protein_g != null ? `<span class="product-tag">${escapeHtml(p.protein_g)} g de proteína</span>` : ""}
        ${(p.claims || []).slice(0, 2).map(c => `<span class="product-tag">${escapeHtml(c)}</span>`).join("")}
      </div>
      <div class="product-card-actions">
        <button class="product-ask-btn" type="button">
          <i data-lucide="message-square-plus" class="ui-icon"></i>
          <span>Consultar este producto</span>
        </button>
      </div>
    </div>
  `).join("");

  container.querySelectorAll(".product-card").forEach((card, index) => {
    const product = products[index];
    const image = card.querySelector("img");
    const fallback = () => {
      image.src = "/static/brand/alpina-logo.png";
      image.classList.add("fallback-logo");
    };
    const url = product.image_url || product.metadata?.image_url;
    if (url) {
      try {
        const parsed = new URL(url, window.location.origin);
        if (parsed.protocol === "https:" || (parsed.protocol === "http:" && parsed.origin === window.location.origin)) {
          image.addEventListener("error", fallback, { once: true });
          image.src = parsed.href;
        } else {
          fallback();
        }
      } catch {
        fallback();
      }
    } else {
      fallback();
    }
    card.querySelector(".product-ask-btn").addEventListener("click", () => onSelectProduct?.(product.name));
  });

  refreshIcons(container);
}
