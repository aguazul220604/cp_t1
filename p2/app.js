document.getElementById("btnProcess").addEventListener("click", function () {
  const fileInput = document.getElementById("datasetFile");
  const file = fileInput.files[0];

  if (!file) {
    alert("Por favor, selecciona un archivo CSV o Excel.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  // Mostrar pantalla de carga
  document.getElementById("loadingSpinner").style.display = "flex";

  // Petición AJAX al Backend de Dataiku
  fetch(getWebAppBackendUrl("process_table"), {
    method: "POST",
    body: formData,
  })
    .then((response) => {
      if (!response.ok)
        throw new Error("Error en el backend al procesar la tabla.");
      return response.json();
    })
    .then((data) => {
      document.getElementById("loadingSpinner").style.display = "none";

      renderSummary(data.columns_analysis);
      renderPreview(data.columns_analysis, data.sample_rows);

      document.getElementById("piiSummarySection").style.display = "block";
      document.getElementById("tablePreviewSection").style.display = "block";
    })
    .catch((error) => {
      document.getElementById("loadingSpinner").style.display = "none";
      alert("Error: " + error.message);
    });
});

// Generar tabla de resumen PII
function renderSummary(columns) {
  const tbody = document.getElementById("piiListBody");
  tbody.innerHTML = "";

  columns.forEach((col) => {
    const probPct = (col.pii_probability * 100).toFixed(2);
    const isPii = col.is_pii;

    const tr = document.createElement("tr");
    tr.innerHTML = `
            <td><strong>${col.name}</strong></td>
            <td style="color: #666;">${col.description || "Sin descripción"}</td>
            <td>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill ${isPii ? "high" : ""}" style="width: ${probPct}%;">
                        ${probPct}%
                    </div>
                </div>
            </td>
            <td>
                <span class="status-badge ${isPii ? "danger" : "success"}">
                    ${isPii ? "POTENCIAL PII" : "NO PII"}
                </span>
            </td>
        `;
    tbody.appendChild(tr);
  });
}

// Generar vista previa con celdas y encabezados resaltados en rojo
function renderPreview(columns, rows) {
  const thead = document.getElementById("previewThead");
  const tbody = document.getElementById("previewTbody");

  thead.innerHTML = "";
  tbody.innerHTML = "";

  const piiCols = new Set(columns.filter((c) => c.is_pii).map((c) => c.name));

  // Encabezados
  let headerTr = document.createElement("tr");
  columns.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col.name;
    if (piiCols.has(col.name)) {
      th.classList.add("pii-header");
    }
    headerTr.appendChild(th);
  });
  thead.appendChild(headerTr);

  // Celdas de muestra
  rows.forEach((row) => {
    let tr = document.createElement("tr");
    columns.forEach((col) => {
      const td = document.createElement("td");
      td.textContent = row[col.name] !== undefined ? row[col.name] : "";
      if (piiCols.has(col.name)) {
        td.classList.add("pii-cell");
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}
