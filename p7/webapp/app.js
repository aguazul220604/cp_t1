let currentColumnsAnalysis = [];

document
  .getElementById("btnProcess")
  .addEventListener("click", handleProcessClick);
document
  .getElementById("btnGenerateCsv")
  .addEventListener("click", handleGenerateCsvClick);

// ---- Mejoras UI: hint de archivos + drag & drop (no tocan la lógica de inferencia) ----
const fileInput = document.getElementById("datasetFile");
const fileHint = document.getElementById("fileHint");
const dropZone = document.getElementById("dropZone");
const fileDrop = dropZone ? dropZone.querySelector(".file-drop") : null;

if (fileInput) {
  fileInput.addEventListener("change", updateFileHint);
}
if (fileDrop && fileInput) {
  ["dragenter", "dragover"].forEach((ev) =>
    fileDrop.addEventListener(ev, (e) => {
      e.preventDefault();
      fileDrop.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    fileDrop.addEventListener(ev, (e) => {
      e.preventDefault();
      fileDrop.classList.remove("dragover");
    })
  );
  fileDrop.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      updateFileHint();
    }
  });
}

function updateFileHint() {
  if (!fileHint || !fileInput) return;
  const n = fileInput.files ? fileInput.files.length : 0;
  if (!n) {
    fileHint.textContent = "Ningún archivo seleccionado";
    fileHint.classList.remove("has-files");
  } else {
    const names = Array.from(fileInput.files)
      .slice(0, 3)
      .map((f) => f.name)
      .join(", ");
    const extra = n > 3 ? ` +${n - 3} más` : "";
    fileHint.textContent = `${n} archivo(s): ${names}${extra}`;
    fileHint.classList.add("has-files");
  }
}

function handleProcessClick() {
  const files = fileInput.files;

  hideError();

  if (!files || files.length === 0) {
    showError("Por favor, selecciona uno o más archivos CSV o Excel.");
    return;
  }

  const formData = new FormData();
  Array.from(files).forEach((file) => formData.append("file", file));

  document.getElementById("loadingSpinner").style.display = "flex";

  fetch(getWebAppBackendUrl("process_table"), {
    method: "POST",
    body: formData,
  })
    .then((response) =>
      response.json().then((data) => ({ ok: response.ok, data })),
    )
    .then(({ ok, data }) => {
      document.getElementById("loadingSpinner").style.display = "none";

      if (!ok || data.status !== "success") {
        throw new Error(
          data.message || "Error desconocido al procesar las tablas.",
        );
      }

      currentColumnsAnalysis = data.columns_analysis || [];
      renderSummary(currentColumnsAnalysis);

      if (data.warnings && data.warnings.length) {
        showWarning(data.warnings.join(" | "));
      }

      const section = document.getElementById("piiSummarySection");
      section.style.display = "block";
      section.scrollIntoView({ behavior: "smooth", block: "start" });
    })
    .catch((error) => {
      document.getElementById("loadingSpinner").style.display = "none";
      showError(error.message);
    });
}

function probBar(pct) {
  const level = pct >= 75 ? "high" : "";
  return `<span class="prob-wrap">
    <span class="prob-bar"><span class="prob-fill ${level}" style="width:${pct.toFixed(1)}%"></span></span>
    <span class="prob-num">${pct.toFixed(2)}%</span>
  </span>`;
}

function renderSummary(columns) {
  const tbody = document.getElementById("piiListBody");
  tbody.innerHTML = "";

  const total = columns.length;
  const piiCount = columns.filter((c) => c.is_pii).length;
  const meta = document.getElementById("resultsMeta");
  if (meta) {
    meta.textContent = `${total} columnas analizadas · ${piiCount} PII detectadas`;
  }

  columns.forEach((col, i) => {
    const probPct = (col.pii_probability * 100);
    const isPii = col.is_pii;
    const entity = col.entity ?? "—";
    const entityPct =
      col.entity_probability === null || col.entity_probability === undefined
        ? "—"
        : (col.entity_probability * 100).toFixed(2) + "%";

    const tr = document.createElement("tr");
    if (isPii) tr.classList.add("pii-row");
    tr.classList.add("row-enter");
    tr.style.animationDelay = `${Math.min(i * 0.03, 0.6)}s`;

    tr.innerHTML = `
      <td>${escapeHtml(col.source_file || "")}</td>
      <td><strong>${escapeHtml(col.name)}</strong></td>
      <td>
        <span class="status-badge ${isPii ? "danger" : "success"}">
          ${isPii ? "PII" : "NO PII"}
        </span>
      </td>
      <td class="prob-cell">${probBar(probPct)}</td>
      <td>${escapeHtml(entity)}</td>
      <td>${entityPct}</td>
    `;
    tbody.appendChild(tr);
  });
}

function handleGenerateCsvClick() {
  if (!currentColumnsAnalysis.length) {
    showError("Primero analiza al menos una tabla antes de generar el CSV.");
    return;
  }

  const header = [
    "Archivo",
    "Nombre de Columna",
    "Prediccion",
    "Probabilidad PII (%)",
    "Entidad",
    "Probabilidad Entidad (%)",
  ];
  const rows = currentColumnsAnalysis.map((col) => [
    col.source_file || "",
    col.name,
    col.is_pii ? "PII" : "NO PII",
    (col.pii_probability * 100).toFixed(2),
    col.entity ?? "",
    col.entity_probability === null || col.entity_probability === undefined
      ? ""
      : (col.entity_probability * 100).toFixed(2),
  ]);

  const csvContent = [header, ...rows].map(toCsvRow).join("\r\n");
  downloadCsv(csvContent, "analisis_pii.csv");
}

function toCsvRow(fields) {
  return fields
    .map((field) => {
      const value = String(field ?? "");
      const needsQuotes = /[",\n]/.test(value);
      const escaped = value.replace(/"/g, '""');
      return needsQuotes ? `"${escaped}"` : escaped;
    })
    .join(",");
}

function downloadCsv(csvContent, filename) {
  const blob = new Blob(["\ufeff" + csvContent], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function showError(message) {
  const el = document.getElementById("uploadError");
  el.textContent = message;
  el.className = "error-text";
  el.style.display = "block";
}

function showWarning(message) {
  const el = document.getElementById("uploadError");
  el.textContent = message;
  el.className = "warning-text";
  el.style.display = "block";
}

function hideError() {
  document.getElementById("uploadError").style.display = "none";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
