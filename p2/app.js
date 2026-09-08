// Variable global para almacenar el dataset procesado y la metadata
let processedData = null;

$(document).ready(function () {
  // 1. Manejador del evento Clic en "Analizar PII"
  $("#btnProcess").on("click", function () {
    const fileInput = document.getElementById("datasetFile");
    const file = fileInput.files[0];

    if (!file) {
      alert("Por favor, selecciona un archivo CSV o Excel primero.");
      return;
    }

    // Crear FormData para enviar el archivo al Backend de Dataiku
    const formData = new FormData();
    formData.append("file", file);

    // Mostrar pantalla de carga
    $("#loadingSpinner").css("display", "flex");

    // Petición AJAX al Backend (Flask Endpoint en Dataiku)
    fetch(getWebAppBackendUrl("process_table"), {
      method: "POST",
      body: formData,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Error en el servidor al procesar la tabla.");
        }
        return response.json();
      })
      .then((data) => {
        $("#loadingSpinner").hide();
        processedData = data; // Guardar datos globalmente

        // Renderizar vistas
        renderPIISummaryTable(data.columns_analysis);
        renderDataPreviewTable(data.columns_analysis, data.sample_rows);

        // Mostrar secciones en la UI
        $("#piiSummarySection").fadeIn();
        $("#tablePreviewSection").fadeIn();
      })
      .catch((error) => {
        $("#loadingSpinner").hide();
        alert("Ocurrió un error: " + error.message);
        console.error("Error:", error);
      });
  });

  // 2. Manejador para Guardar la Confirmación de PII (Retroalimentación)
  $("#btnSaveFeedback").on("click", function () {
    if (!processedData) return;

    // Recopilar las selecciones manuales del usuario (Checkboxes)
    const userFeedback = [];
    $("#piiListBody tr").each(function () {
      const colName = $(this).find(".pii-checkbox").data("col-name");
      const isPiiUserConfirmed = $(this).find(".pii-checkbox").is(":checked");
      const probability = $(this).find(".pii-checkbox").data("probability");

      userFeedback.push({
        column_name: colName,
        user_confirmed_pii: isPiiUserConfirmed,
        model_probability: probability,
      });
    });

    $("#loadingSpinner").css("display", "flex");

    // Enviar la confirmación al Backend para re-entrenamiento
    fetch(getWebAppBackendUrl("save_feedback"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ feedback: userFeedback }),
    })
      .then((response) => response.json())
      .then((data) => {
        $("#loadingSpinner").hide();
        if (data.status === "success") {
          alert(
            "¡Confirmación guardada exitosamente! Estos datos servirán para robustecer el modelo LightGBM.",
          );
        } else {
          alert("Error al guardar: " + data.message);
        }
      })
      .catch((error) => {
        $("#loadingSpinner").hide();
        alert("Error al enviar la confirmación: " + error.message);
      });
  });
});

// -------------------------------------------------------------
// FUNCIONES AUXILIARES PARA RENDERIZAR INTERFAZ
// -------------------------------------------------------------

// Función A: Renderizar la lista de columnas con sus porcentajes PII
function renderPIISummaryTable(columnsAnalysis) {
  const $tbody = $("#piiListBody");
  $tbody.empty();

  columnsAnalysis.forEach((col) => {
    const isPII = col.is_pii;
    const probabilityPct = (col.pii_probability * 100).toFixed(2);

    // Checkbox marcado por defecto si el modelo detectó PII
    const checkedAttr = isPII ? "checked" : "";
    const badgeClass = isPII ? "bg-danger" : "bg-success";
    const badgeText = isPII ? "POTENCIAL PII" : "No PII";

    const rowHtml = `
            <tr>
                <td class="text-center">
                    <input type="checkbox" class="form-check-input pii-checkbox" style="transform: scale(1.3);" 
                           data-col-name="${col.name}" 
                           data-probability="${col.pii_probability}" ${checkedAttr}>
                </td>
                <td><strong>${col.name}</strong></td>
                <td class="text-muted">${col.description || "Sin descripción"}</td>
                <td>
                    <div class="d-flex align-items-center">
                        <div class="progress flex-grow-1 me-2" style="height: 18px;">
                            <div class="progress-bar ${isPII ? "bg-danger" : "bg-info"}" 
                                 role="progressbar" 
                                 style="width: ${probabilityPct}%;">
                                 ${probabilityPct}%
                            </div>
                        </div>
                    </div>
                </td>
                <td><span class="badge ${badgeClass}">${badgeText}</span></td>
            </tr>
        `;
    $tbody.append(rowHtml);
  });
}

// Función B: Renderizar la vista previa de la tabla resaltando columnas PII en ROJO
function renderDataPreviewTable(columnsAnalysis, sampleRows) {
  const $thead = $("#previewThead");
  const $tbody = $("#previewTbody");

  $thead.empty();
  $tbody.empty();

  // Identificar qué columnas son PII
  const piiColumnsSet = new Set(
    columnsAnalysis.filter((c) => c.is_pii).map((c) => c.name),
  );

  // 1. Construir Cabecera (Thead)
  let headerHtml = "<tr>";
  columnsAnalysis.forEach((col) => {
    const isPiiCol = piiColumnsSet.has(col.name);
    // Si es PII aplica la clase CSS roja (.pii-column-header)
    const headerClass = isPiiCol ? "pii-column-header" : "table-secondary";
    const icon = isPiiCol ? '<i class="fa-solid fa-lock me-1"></i>' : "";

    headerHtml += `<th class="${headerClass}">${icon}${col.name}</th>`;
  });
  headerHtml += "</tr>";
  $thead.append(headerHtml);

  // 2. Construir Filas de Muestra (Tbody)
  sampleRows.forEach((row) => {
    let rowHtml = "<tr>";
    columnsAnalysis.forEach((col) => {
      const isPiiCol = piiColumnsSet.has(col.name);
      const val = row[col.name] !== undefined ? row[col.name] : "";
      // Si la columna es PII aplica el fondo rojo suave (.pii-cell)
      const cellClass = isPiiCol ? "pii-cell fw-bold text-danger" : "";

      rowHtml += `<td class="${cellClass}">${val}</td>`;
    });
    rowHtml += "</tr>";
    $tbody.append(rowHtml);
  });
}
