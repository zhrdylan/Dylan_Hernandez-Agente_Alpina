import { api, formatCurrency } from "../api.js";
import { state } from "../state.js";
import { refreshIcons } from "../utils/icons.js";

/**
 * Componente del Catálogo Oficial de Productos Alpina.
 */
export async function loadAndRenderCatalog(onSelectProduct) {
  const container = document.getElementById("product-grid");
  const totalEl = document.getElementById("product-total");
  const searchInput = document.getElementById("product-search");
  if (!container) return;

  container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--muted);"><i data-lucide="loader-2" class="ui-icon spin"></i> Cargando catálogo oficial...</div>`;
  refreshIcons(container);

  try {
    const data = await api("/api/products?limit=96");
    state.productsCache = data.items || [];
    if (totalEl) totalEl.textContent = `${data.total || data.items.length} productos oficiales`;
    renderProductCards(state.productsCache, container, onSelectProduct);

    if (searchInput) {
      searchInput.oninput = (e) => {
        const query = e.target.value.toLowerCase().trim();
        const filtered = state.productsCache.filter(p =>
          (p.name && p.name.toLowerCase().includes(query)) ||
          (p.ean && p.ean.includes(query)) ||
          (p.id && p.id.toLowerCase().includes(query)) ||
          ((p.claims || []).some(c => String(c).toLowerCase().includes(query)))
        );
        if (totalEl) totalEl.textContent = `${filtered.length} productos`;
        renderProductCards(filtered, container, onSelectProduct);
      };
    }
  } catch (err) {
    container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--red);"><i data-lucide="alert-circle" class="ui-icon"></i> Error al cargar productos: ${escapeHtml(err.message || String(err))}</div>`;
    refreshIcons(container);
  }
}

function renderProductCards(products, container, onSelectProduct) {
  if (!products || products.length === 0) {
    container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--muted);"><i data-lucide="search-x" class="ui-icon"></i> No se encontraron productos con ese criterio.</div>`;
    refreshIcons(container);
    return;
  }

  container.innerHTML = products.map(p => {
    const imageUrl = p.image_url || (p.metadata && p.metadata.image_url) || "/static/brand/alpina-logo.png";
    return `
    <div class="product-card">
      <div class="product-img-wrapper">
        <img
          class="product-img"
          src="${imageUrl}"
          alt="${escapeHtml(p.name)}"
          loading="lazy"
          onerror="this.onerror=null; this.src='/static/brand/alpina-logo.png'; this.classList.add('fallback-logo');"
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
        ${p.price ? formatCurrency(p.price) : "Precio oficial no consta"}
      </div>
      <div class="product-card-tags">
        ${p.protein_g ? `<span class="product-tag">${p.protein_g}g proteína</span>` : ""}
        ${(p.claims || []).slice(0, 2).map(c => `<span class="product-tag">${escapeHtml(c)}</span>`).join("")}
      </div>
      <div class="product-card-actions">
        <button class="product-ask-btn" type="button" data-product-name="${escapeHtml(p.name)}">
          <i data-lucide="message-square-plus" class="ui-icon"></i>
          <span>Consultar este producto</span>
        </button>
      </div>
    </div>
  `;
  }).join("");

  container.querySelectorAll(".product-ask-btn").forEach(btn => {
    btn.onclick = () => {
      const name = btn.dataset.productName;
      if (name && onSelectProduct) {
        onSelectProduct(name);
      }
    };
  });

  refreshIcons(container);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text || "");
  return div.innerHTML;
}
