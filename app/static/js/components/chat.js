import { openPdfPreviewModal } from "./dossier.js";
import { isProductCitation, openCitationDrawer } from "./inspector.js";
import { refreshIcons } from "../utils/icons.js";

const REPORT_FORMATS = {
  pdf: ["PDF", "file-text"],
  docx: ["Word", "file"],
  xlsx: ["Excel", "file-spreadsheet"],
};

function reportDownload(report) {
  const url = String(report.download_url || "");
  if (!/^\/api\/reports\/[a-f0-9-]+\/download$/i.test(url)) return null;
  const download = document.createElement("a");
  download.href = url;
  download.download = report.filename || "informe";
  return download;
}

function createReportCard(report) {
  const download = reportDownload(report);
  const format = REPORT_FORMATS[report.report_type];
  if (!download || !format) return null;
  const [label, icon] = format;

  const card = document.createElement("section");
  card.className = "report-hero-card";
  card.innerHTML = `
    <div class="report-hero-type"><i data-lucide="${icon}" class="ui-icon"></i>${label}</div>
    <p class="report-hero-title"></p>
    <div class="report-hero-actions"></div>
  `;
  card.querySelector(".report-hero-title").textContent = report.title || "Informe de Alpina";
  const actions = card.querySelector(".report-hero-actions");
  if (report.report_type === "pdf") {
    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "report-hero-btn preview";
    preview.textContent = "Vista previa";
    preview.addEventListener("click", () => openPdfPreviewModal(report));
    actions.appendChild(preview);
  }
  download.className = "report-hero-btn download";
  download.innerHTML = '<i data-lucide="download" class="ui-icon"></i>';
  download.append("Descargar " + label);
  actions.appendChild(download);
  return card;
}

/**
 * Renderizador de mensajes, bienvenida interactiva y citas con iconos enriquecidos.
 */
export function renderMessages(messages, onAskExample) {
  const container = document.getElementById("messages");
  if (!container) return;
  container.setAttribute("aria-busy", "false");

  if (!messages || messages.length === 0) {
    const welcome = document.getElementById("welcome-template");
    container.replaceChildren(welcome.content.cloneNode(true));

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

export function renderChatLoading() {
  const container = document.getElementById("messages");
  const template = document.getElementById("chat-loading-template");
  container.setAttribute("aria-busy", "true");
  container.replaceChildren(template.content.cloneNode(true));
  container.scrollTop = 0;
}

function createMessageElement(msg) {
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

  const content = document.createElement("div");
  content.className = "message-content";
  if (typeof msg.content_html === "string") {
    content.innerHTML = msg.content_html;
    content.querySelectorAll("table").forEach(table => {
      const scroll = document.createElement("div");
      scroll.className = "message-table";
      scroll.tabIndex = 0;
      scroll.setAttribute("role", "region");
      scroll.setAttribute("aria-label", "Tabla del mensaje");
      table.before(scroll);
      scroll.appendChild(table);
    });
  } else {
    content.classList.add("message-content-plain");
    content.textContent = msg.content || "";
  }
  bubble.appendChild(content);

  const report = msg.metadata?.generated_report || msg.generated_report;
  if (!isUser && report) {
    const card = createReportCard(report);
    if (card) bubble.appendChild(card);
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
          <span>Fuentes oficiales citadas</span>
        </div>
        <div class="citation-chips"></div>
      `;
      const chipsContainer = citationsDiv.querySelector(".citation-chips");
      citations.forEach(c => {
        const product = isProductCitation(c);
        const chip = document.createElement("button");
        chip.className = "citation-chip";
        chip.type = "button";
        chip.title = product ? "Ver ficha del producto" : "Ver evidencia documental";
        chip.innerHTML = `
          <i data-lucide="${product ? "package" : "file-search"}" class="ui-icon chip-icon"></i>
          <strong></strong>
          <span class="chip-page"></span>
        `;
        chip.querySelector("strong").textContent = c.title || c.document_id;
        chip.querySelector(".chip-page").textContent = product ? "Ficha" : `(Pág. ${c.page || 1})`;
        chip.onclick = () => openCitationDrawer(c, chip);
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
    <div class="message-bubble skeleton-bubble">
      <p class="typing-status" role="status">Analizando documentos oficiales…</p>
      <div class="skeleton skeleton-line" aria-hidden="true"></div>
      <div class="skeleton skeleton-line" aria-hidden="true"></div>
      <div class="skeleton skeleton-line" aria-hidden="true"></div>
    </div>
  `;
  container.appendChild(typingEl);
  container.scrollTop = container.scrollHeight;
}

export function hideTypingIndicator() {
  const existing = document.getElementById("typing-indicator");
  if (existing) existing.remove();
}
