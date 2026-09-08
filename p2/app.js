let currentColumnsAnalysis = [];

document
  .getElementById("btnProcess")
  .addEventListener("click", handleProcessClick);
document
  .getElementById("btnGenerateCsv")
  .addEventListener("click", handleGenerateCsvClick);

function handleProcessClick() {
  const fileInput = document.getElementById("datasetFile");
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

      document.getElementById("piiSummarySection").style.display = "block";
    })
    .catch((error) => {
      document.getElementById("loadingSpinner").style.display = "none";
      showError(error.message);
    });
}

function renderSummary(columns) {
  const tbody = document.getElementById("piiListBody");
  tbody.innerHTML = "";

  columns.forEach((col) => {
    const probPct = (col.pii_probability * 100).toFixed(2);
    const isPii = col.is_pii;

    const tr = document.createElement("tr");
    if (isPii) tr.classList.add("pii-row");

    tr.innerHTML = `
      <td>${escapeHtml(col.source_file || "")}</td>
      <td>${escapeHtml(col.name)}</td>
      <td>
        <span class="status-badge ${isPii ? "danger" : "success"}">
          ${isPii ? "PII" : "NO PII"}
        </span>
      </td>
      <td>${probPct}%</td>
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
  ];
  const rows = currentColumnsAnalysis.map((col) => [
    col.source_file || "",
    col.name,
    col.is_pii ? "PII" : "NO PII",
    (col.pii_probability * 100).toFixed(2),
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
