/**
 * Parser de Markdown seguro, robusto y sin dependencias externas.
 * Renderiza de forma fiel negritas, cursivas, listas, tablas y encabezados,
 * garantizando que NUNCA queden asteriscos dobles (**) o sintaxis sin procesar en pantalla.
 */
export function renderMarkdown(text) {
  if (!text) return "";

  // 1. Escapar HTML para prevenir XSS
  let str = String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // 2. Extraer bloques de codigo cercados (```lang ... ```)
  const codeBlocks = [];
  str = str.replace(/```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g, (_, code) => {
    const placeholder = `§§CODEBLOCK_${codeBlocks.length}§§`;
    codeBlocks.push(`<pre class="md-code-block"><code>${code.trim()}</code></pre>`);
    return placeholder;
  });

  // 3. Extraer codigo en linea (`...`)
  const inlineCodes = [];
  str = str.replace(/`([^`]+)`/g, (_, code) => {
    const placeholder = `§§INLINECODE_${inlineCodes.length}§§`;
    inlineCodes.push(`<code class="md-inline-code">${code}</code>`);
    return placeholder;
  });

  // 4. Encabezados (#, ##, ###, ####)
  str = str.replace(/^#### (.*$)/gim, '<h5 class="md-h5">$1</h5>');
  str = str.replace(/^### (.*$)/gim, '<h4 class="md-h4">$1</h4>');
  str = str.replace(/^## (.*$)/gim, '<h3 class="md-h3">$1</h3>');
  str = str.replace(/^# (.*$)/gim, '<h2 class="md-h2">$1</h2>');

  // 5. Lineas horizontales (---, ***, ___)
  str = str.replace(/^(?:---|\*\*\*|___)\s*$/gim, '<hr class="md-hr">');

  // 6. Negrita + Cursiva combinadas: ***texto*** o ___texto___
  str = str.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong class="md-bold"><em class="md-italic">$1</em></strong>');
  str = str.replace(/___([^_]+)___/g, '<strong class="md-bold"><em class="md-italic">$1</em></strong>');

  // 7. Negrita: **texto** o __texto__
  str = str.replace(/\*\*([^*]+)\*\*/g, '<strong class="md-bold">$1</strong>');
  str = str.replace(/__([^_]+)__/g, '<strong class="md-bold">$1</strong>');

  // 8. Cursiva: *texto* o _texto_ (evitando confusiones con viñetas)
  // Requiere que el asterisco o guión bajo no tenga espacio inmediato en los bordes interiores
  str = str.replace(/(^|[^\*])\*([^\s*][^*]*[^\s*]|[^\s*])\*(?!\*)/g, '$1<em class="md-italic">$2</em>');
  str = str.replace(/(^|[^_])_([^\s_][^_]*[^\s_]|[^\s_])_(?!_)/g, '$1<em class="md-italic">$2</em>');

  // 9. Limpieza de asteriscos huérfanos o sueltos para evitar que se vea "**" en la salida
  str = str.replace(/\*\*/g, "");

  // 10. Procesamiento linea por linea para Listas y Tablas
  const lines = str.split("\n");
  const processed = [];
  let inUl = false;
  let inOl = false;
  let inTable = false;
  let tableRows = [];

  function closeLists() {
    if (inUl) {
      processed.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      processed.push("</ol>");
      inOl = false;
    }
  }

  function flushTable() {
    if (!inTable || tableRows.length === 0) return;
    let html = '<div class="md-table-wrapper"><table class="md-table">';
    tableRows.forEach((row, idx) => {
      // Ignorar fila separadora |---|---|
      if (/^\|?\s*[-:]+[-| :]*\|?$/.test(row.trim())) return;
      const cells = row.split("|").map(c => c.trim()).filter((c, i, arr) => {
        // Ignorar primer/ultimo elemento si vienen de pipes exteriores
        if (i === 0 && row.trim().startsWith("|") && c === "") return false;
        if (i === arr.length - 1 && row.trim().endsWith("|") && c === "") return false;
        return true;
      });
      if (idx === 0) {
        html += "<thead><tr>" + cells.map(c => `<th>${c}</th>`).join("") + "</tr></thead><tbody>";
      } else {
        html += "<tr>" + cells.map(c => `<td>${c}</td>`).join("") + "</tr>";
      }
    });
    html += "</tbody></table></div>";
    processed.push(html);
    tableRows = [];
    inTable = false;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Deteccion de tabla Markdown: lineas que contienen '|'
    if (trimmed.startsWith("|") && trimmed.endsWith("|") && trimmed.includes("|")) {
      closeLists();
      inTable = true;
      tableRows.push(trimmed);
      continue;
    } else if (inTable) {
      flushTable();
    }

    // Viñetas no ordenadas (- item, * item, + item)
    const bulletMatch = line.match(/^(\s*)[-*+]\s+(.*)$/);
    // Listas numeradas (1. item, 2. item)
    const numMatch = line.match(/^(\s*)\d+\.\s+(.*)$/);

    if (bulletMatch) {
      if (inOl) {
        processed.push("</ol>");
        inOl = false;
      }
      if (!inUl) {
        processed.push('<ul class="md-list">');
        inUl = true;
      }
      processed.push(`<li>${bulletMatch[2]}</li>`);
    } else if (numMatch) {
      if (inUl) {
        processed.push("</ul>");
        inUl = false;
      }
      if (!inOl) {
        processed.push('<ol class="md-list">');
        inOl = true;
      }
      processed.push(`<li>${numMatch[2]}</li>`);
    } else {
      closeLists();
      processed.push(line);
    }
  }

  closeLists();
  flushTable();

  // 11. Restaurar bloques y códigos extraídos
  let result = processed.join("\n");
  codeBlocks.forEach((block, idx) => {
    result = result.replace(`§§CODEBLOCK_${idx}§§`, block);
  });
  inlineCodes.forEach((code, idx) => {
    result = result.replace(`§§INLINECODE_${idx}§§`, code);
  });

  // 12. Párrafos separados por saltos de línea dobles
  const paragraphs = result.split(/\n\s*\n/);
  return paragraphs
    .map(p => {
      const trimmed = p.trim();
      if (!trimmed) return "";
      // Si ya comienza con bloque HTML, no envolver en <p>
      if (/^<(h[1-6]|ul|ol|pre|div|table|blockquote|hr)/i.test(trimmed)) {
        return trimmed;
      }
      return `<p class="md-p">${trimmed.replace(/\n/g, "<br>")}</p>`;
    })
    .filter(Boolean)
    .join("");
}
