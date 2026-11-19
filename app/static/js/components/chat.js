import { state } from "../state.js";
import { openPdfPreviewModal } from "./dossier.js";
import { openCitationDrawer } from "./inspector.js";
import { renderMarkdown } from "../utils/markdown.js";
import { refreshIcons } from "../utils/icons.js";

/**
 * Renderizador de mensajes, bienvenida interactiva y citas con iconos enriquecidos.
 */
export function renderMessages(messages, onAskExample) {
  const container = document.getElementById("messages");
  if (!container) return;

  if (!messages || messages.length === 0) {
    container.innerHTML = `
      <div class="empty-state" id="empty-state">
        <img class="empty-logo" src="/static/brand/alpina-logo.png" alt="Alpina" />
        <h2>¿Qué deseas consultar hoy?</h2>
        <p>
          Soy el Asistente Oficial de Alpina. Respondo con base en documentos oficiales,
          normas de etiquetado y nuestro catálogo. Cada respuesta incluye trazabilidad verificada.
        </p>
        <div class="examples" id="examples">
          <button class="example" type="button" data-question="¿Qué exige la Resolución 810 de 2021 sobre etiquetado frontal?">
            <span class="example-text"><i data-lucide="scale" class="ui-icon example-icon"></i> ¿Qué exige la Resolución 810 de 2021 sobre etiquetado?</span>
            <i data-lucide="arrow-right" class="ui-icon example-arrow"></i>
          </button>
          <button class="example" type="button" data-question="¿Cuánta proteína tiene el Yogurt Griego Natural 500 g y qué claims tiene?">
            <span class="example-text"><i data-lucide="sparkles" class="ui-icon example-icon"></i> ¿Cuánta proteína tiene el Yogurt Griego Natural 500 g?</span>
            <i data-lucide="arrow-right" class="ui-icon example-arrow"></i>
          </button>
          <button class="example" type="button" data-question="¿Cuáles fueron los resultados financieros de Alpina en 2025?">
            <span class="example-text"><i data-lucide="bar-chart-3" class="ui-icon example-icon"></i> ¿Cuáles fueron los resultados financieros de 2025?</span>
            <i data-lucide="arrow-right" class="ui-icon example-arrow"></i>
          </button>
          <button class="example" type="button" data-question="¿Qué dice la política de calidad sobre inocuidad alimentaria?">
            <span class="example-text"><i data-lucide="shield-check" class="ui-icon example-icon"></i> ¿Qué establece la política de calidad e inocuidad?</span>
            <i data-lucide="arrow-right" class="ui-icon example-arrow"></i>
          </button>
        </div>
      </div>
    `;

    refreshIcons(container);

    container.querySelectorAll(".example").forEach(btn => {
      btn.addEventListener("click", () => {
        const q = btn.dataset.question;
        if (q && onAskExample) onAskExample(q);
      });
    });
    return;
  }

  container.innerHTML = "";
  messages.forEach(msg => {
    container.appendChild(createMessageElement(msg));
  });

  refreshIcons(container);
  container.scrollTop = container.scrollHeight;
}

export function createMessageElement(msg) {
  const isUser = msg.role === "user";
  const el = document.createElement("div");
  el.className = `message ${isUser ? "message-user" : "message-assistant"}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  if (isUser) {
    avatar.innerHTML = `<i data-lucide="user" class="ui-icon" style="width: 18px; height: 18px;"></i>`;
  } else {
    avatar.innerHTML = `<img src="/static/brand/alpina-logo.png" alt="Alpina" />`;
  }
  el.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  // Renderizado con parser de Markdown seguro (convierte ** en negrita, listas, etc.)
  bubble.innerHTML = renderMarkdown(msg.content || "");

  // Si el asistente generó un informe mediante Tool Calling, incrustar Tarjeta Hero
  const report = msg.metadata?.generated_report || msg.generated_report;
  if (!isUser && report) {
    const isPdf = report.report_type === "pdf";
    const reportCard = document.createElement("div");
    reportCard.className = "report-hero-card";
    reportCard.innerHTML = `
      <div class="report-hero-badge">
        <span class="report-hero-type">
          <i data-lucide="${isPdf ? 'file-text' : 'file-spreadsheet'}" class="ui-icon"></i>
          <span>${isPdf ? "Documento PDF Oficial" : "Libro Excel Analítico"}</span>
        </span>
        <span class="report-hero-status">
          <i data-lucide="sparkles" class="ui-icon"></i>
          <span>Generado con Tool Calling</span>
        </span>
      </div>
      <div class="report-hero-title">${escapeHtml(report.title || "Informe Oficial · Alpina")}</div>
      <div class="report-hero-meta">Archivo: <code>${escapeHtml(report.filename || "informe")}</code> · Verificado 100% trazable</div>
      <div class="report-hero-actions">
        ${isPdf ? `
          <button class="report-hero-btn preview" type="button">
            <i data-lucide="eye" class="ui-icon"></i>
            <span>Previsualizar Informe PDF</span>
          </button>
        ` : ''}
        <a class="report-hero-btn download" href="${report.download_url}" download="${report.filename || 'reporte'}">
          <i data-lucide="download" class="ui-icon"></i>
          <span>Descargar ${isPdf ? "PDF" : "Excel"}</span>
        </a>
      </div>
    `;
    if (isPdf) {
      reportCard.querySelector(".report-hero-btn.preview")?.addEventListener("click", () => {
        openPdfPreviewModal(report);
      });
    }
    bubble.appendChild(reportCard);
  }

  // Si es del asistente y tiene citas, agregar chips de evidencia
  if (!isUser) {
    const citations = Array.isArray(msg.citations) ? msg.citations : [];
    if (citations.length > 0) {
      const citationsDiv = document.createElement("div");
      citationsDiv.className = "citations-container";
      citationsDiv.innerHTML = `
        <div class="citations-label">
          <i data-lucide="bookmark-check" class="ui-icon" style="width:14px;height:14px;"></i>
          <span>Fuentes Oficiales Citadas (haz clic para auditar evidencia)</span>
        </div>
        <div class="citation-chips"></div>
      `;
      const chipsContainer = citationsDiv.querySelector(".citation-chips");
      citations.forEach(c => {
        const chip = document.createElement("button");
        chip.className = "citation-chip";
        chip.type = "button";
        chip.title = "Haz clic para ver el fragmento resaltado en el PDF oficial";
        chip.innerHTML = `
          <i data-lucide="file-search" class="ui-icon chip-icon"></i>
          <strong>${escapeHtml(c.title || c.document_id)}</strong>
          <span class="chip-page">(Pág. ${c.page || 1})</span>
        `;
        chip.onclick = () => openCitationDrawer(c);
        chipsContainer.appendChild(chip);
      });
      bubble.appendChild(citationsDiv);
    }

    // Acciones del mensaje
    const actions = document.createElement("div");
    actions.className = "msg-actions";

    const copyBtn = document.createElement("button");
    copyBtn.className = "copy-btn";
    copyBtn.type = "button";
    copyBtn.innerHTML = `<i data-lucide="copy" class="ui-icon"></i> <span>Copiar</span>`;
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(msg.content);
      copyBtn.innerHTML = `<i data-lucide="check" class="ui-icon" style="color:var(--green)"></i> <span>¡Copiado!</span>`;
      refreshIcons(copyBtn);
      setTimeout(() => {
        copyBtn.innerHTML = `<i data-lucide="copy" class="ui-icon"></i> <span>Copiar</span>`;
        refreshIcons(copyBtn);
      }, 2000);
    });
    actions.appendChild(copyBtn);

    bubble.appendChild(actions);
  }

  el.appendChild(bubble);
  refreshIcons(el);
  return el;
}

export function showTypingIndicator() {
  const container = document.getElementById("messages");
  if (!container) return;

  hideTypingIndicator();

  const typingEl = document.createElement("div");
  typingEl.id = "typing-indicator";
  typingEl.className = "message message-assistant";
  typingEl.innerHTML = `
    <div class="message-avatar"><img src="/static/brand/alpina-logo.png" alt="Alpina" /></div>
    <div class="message-bubble typing-bubble">
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span style="font-size: 0.78rem; color: var(--muted); margin-left: 8px;">
        <i data-lucide="search" class="ui-icon" style="width:13px;height:13px;margin-right:3px;"></i>
        Analizando documentos oficiales...
      </span>
    </div>
  `;
  container.appendChild(typingEl);
  refreshIcons(typingEl);
  container.scrollTop = container.scrollHeight;
}

export function hideTypingIndicator() {
  const existing = document.getElementById("typing-indicator");
  if (existing) existing.remove();
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text || "");
  return div.innerHTML;
}
