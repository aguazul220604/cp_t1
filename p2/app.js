// Guarda el último resultado del análisis para poder generar el CSV después
let currentColumnsAnalysis = [];

document
  .getElementById("btnProcess")
  .addEventListener("click", handleProcessClick);
document
  .getElementById("btnGenerateCsv")
  .addEventListener("click", handleGenerateCsvClick);

function handleProcessClick() {
  const fileInput = document.getElementById("datasetFile");
  const file = fileInput.files[0];

  hideError();

  if (!file) {
    showError("Por favor, selecciona un archivo CSV o Excel.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

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
          data.message || "Error desconocido al procesar la tabla.",
        );
      }

      currentColumnsAnalysis = data.columns_analysis || [];
      renderSummary(currentColumnsAnalysis);

      document.getElementById("piiSummarySection").style.display = "block";
    })
    .catch((error) => {
      document.getElementById("loadingSpinner").style.display = "none";
      showError(error.message);
    });
}

// Genera las filas del listado, resaltando en rojo las columnas PII
function renderSummary(columns) {
  const tbody = document.getElementById("piiListBody");
  tbody.innerHTML = "";

  columns.forEach((col) => {
    const probPct = (col.pii_probability * 100).toFixed(2);
    const isPii = col.is_pii;

    const tr = document.createElement("tr");
    if (isPii) {
      tr.classList.add("pii-row");
    }

    tr.innerHTML = `
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

// Construye y descarga el CSV a partir de lo que ya está en pantalla
function handleGenerateCsvClick() {
  if (!currentColumnsAnalysis.length) {
    showError("Primero analiza una tabla antes de generar el CSV.");
    return;
  }

  const header = ["Nombre de Columna", "Prediccion", "Probabilidad PII (%)"];
  const rows = currentColumnsAnalysis.map((col) => [
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
  // El BOM (\ufeff) evita que Excel muestre mal los acentos al abrir el CSV
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
  const errorEl = document.getElementById("uploadError");
  errorEl.textContent = message;
  errorEl.style.display = "block";
}

function hideError() {
  const errorEl = document.getElementById("uploadError");
  errorEl.style.display = "none";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
