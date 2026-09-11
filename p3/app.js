document.addEventListener("DOMContentLoaded", () => {
  // ==========================================
  // 1. GESTIÓN DE VISTAS Y NAVEGACIÓN
  // ==========================================
  const views = {
    newMain: document.getElementById("view-new-flow-main"),
    newHistory: document.getElementById("view-new-flow-history"),
    legacyMain: document.getElementById("view-legacy-flow"),
    legacyHistory: document.getElementById("view-legacy-flow-history"),
  };

  let currentFlow = "NEW"; // "NEW" o "LEGACY"

  function switchView(targetView) {
    Object.values(views).forEach((view) => {
      if (view) view.classList.add("hidden");
    });
    if (targetView) targetView.classList.remove("hidden");
  }

  // Botón Global: Cambiar flujo (NEW <-> LEGACY)
  document.getElementById("btn-switch-flow")?.addEventListener("click", () => {
    if (currentFlow === "NEW") {
      currentFlow = "LEGACY";
      switchView(views.legacyMain);
      loadLegacyData();
    } else {
      currentFlow = "NEW";
      switchView(views.newMain);
      loadNewFlowData();
    }
  });

  // Navegación dentro de NEW FLOW
  document.getElementById("btn-go-history")?.addEventListener("click", () => {
    switchView(views.newHistory);
    loadHistoryData("NEW");
  });

  document.getElementById("btn-select-env")?.addEventListener("click", () => {
    switchView(views.newMain);
  });

  // Navegación dentro de LEGACY FLOW
  document
    .getElementById("btn-go-legacy-history")
    ?.addEventListener("click", () => {
      switchView(views.legacyHistory);
      loadHistoryData("LEGACY");
    });

  document
    .getElementById("btn-back-legacy-main")
    ?.addEventListener("click", () => {
      switchView(views.legacyMain);
    });

  // ==========================================
  // 2. LÓGICA DE BOTONES DE ESTADO (CONSERVAR/DESCARTAR)
  // ==========================================
  document.addEventListener("click", (e) => {
    const button = e.target.closest(".btn-toggle");
    if (!button) return;

    const currentState = button.getAttribute("data-state");
    const isPreserved = currentState === "preserve";

    if (isPreserved) {
      // Cambiar a Descartado
      button.setAttribute("data-state", "discard");
      button.className = "btn-toggle status-discarded";
      button.querySelector(".icon").innerHTML = "&#10008;";
      button.querySelector(".label").textContent = "Descartado";
    } else {
      // Cambiar a Conservado
      button.setAttribute("data-state", "preserve");
      button.className = "btn-toggle status-preserved";
      button.querySelector(".icon").innerHTML = "&#10004;";
      button.querySelector(".label").textContent = "Conservado";
    }

    recalculateMetrics();
  });

  // ==========================================
  // 3. RECÁLCULO DINÁMICO DE MÉTRICAS DE ESPACIO
  // ==========================================
  function recalculateMetrics() {
    let bytesToFree = 0;

    // Seleccionar solo los botones de la vista activa
    const activeView = Object.values(views).find(
      (v) => !v.classList.contains("hidden"),
    );
    if (!activeView) return;

    const discardButtons = activeView.querySelectorAll(
      '.btn-toggle[data-state="discard"]',
    );

    discardButtons.forEach((btn) => {
      const bytes = parseFloat(btn.getAttribute("data-size-bytes") || "0");
      bytesToFree += bytes;
    });

    // Valores de ejemplo iniciales (pueden venir de API)
    const totalSizeBytes = 80 * 1024 * 1024 * 1024; // 80 GB
    const freeSizeBytes = bytesToFree;
    const resultSizeBytes = totalSizeBytes - freeSizeBytes;

    document.getElementById("metric-total-space").textContent =
      formatBytes(totalSizeBytes);
    document.getElementById("metric-free-space").textContent =
      formatBytes(freeSizeBytes);
    document.getElementById("metric-result-space").textContent =
      formatBytes(resultSizeBytes);
  }

  function formatBytes(bytes) {
    if (bytes === 0) return "0 GB";
    const gb = bytes / (1024 * 1024 * 1024);
    return gb.toFixed(2) + " GB";
  }

  // ==========================================
  // 4. INTEGRACIÓN CON BACKEND (FETCH API)
  // ==========================================

  // Cargar datos iniciales de New Flow
  async function loadNewFlowData() {
    try {
      const response = await fetch("/extension-api/get-bundles-new");
      const data = await response.json();
      // Lógica para actualizar las tarjetas UAT/PROD-1 dinámicamente si aplica
      recalculateMetrics();
    } catch (error) {
      console.error("Error cargando bundles de New Flow:", error);
    }
  }

  // Cargar datos iniciales de Legacy Flow
  async function loadLegacyData() {
    try {
      const response = await fetch("/extension-api/get-bundles-legacy");
      const data = await response.json();
      // Lógica para renderizar tbody-legacy-main
      recalculateMetrics();
    } catch (error) {
      console.error("Error cargando bundles de Legacy Flow:", error);
    }
  }

  // Cargar Históricos (API genérica por flujo)
  async function loadHistoryData(flowType) {
    try {
      const response = await fetch(
        `/extension-api/get-historico?flow=${flowType}`,
      );
      const historyList = await response.json();

      const targetTbodyId =
        flowType === "NEW" ? "tbody-new-history" : "tbody-legacy-history";
      const tbody = document.getElementById(targetTbodyId);

      if (!tbody) return;
      tbody.innerHTML = "";

      historyList.forEach((item) => {
        const tr = document.createElement("tr");
        if (flowType === "NEW") {
          tr.innerHTML = `
                        <td class="cell-server">${item.server}</td>
                        <td class="cell-project">${item.project}</td>
                        <td class="cell-versions" colspan="2">
                            <div class="version-row">
                                <span class="version-name">${item.version}</span>
                                <button class="btn-toggle status-${item.status.toLowerCase()}" data-state="${item.status.toLowerCase()}">
                                    <span class="icon">${item.status === "preserve" ? "&#10004;" : "&#10008;"}</span>
                                    <span class="label">${item.status === "preserve" ? "Conservado" : "Descartado"}</span>
                                </button>
                            </div>
                        </td>
                    `;
        } else {
          tr.innerHTML = `
                        <td class="cell-project">${item.project}</td>
                        <td class="cell-versions" colspan="2">
                            <div class="version-row">
                                <span class="version-name">${item.version}</span>
                                <button class="btn-toggle status-${item.status.toLowerCase()}" data-state="${item.status.toLowerCase()}">
                                    <span class="icon">${item.status === "preserve" ? "&#10004;" : "&#10008;"}</span>
                                    <span class="label">${item.status === "preserve" ? "Conservado" : "Descartado"}</span>
                                </button>
                            </div>
                        </td>
                    `;
        }
        tbody.appendChild(tr);
      });
      recalculateMetrics();
    } catch (error) {
      console.error(`Error cargando histórico para ${flowType}:`, error);
    }
  }

  // Evento de Autorización (Ejecución de la limpieza/subida)
  document
    .getElementById("btn-authorize")
    ?.addEventListener("click", async () => {
      const activeView = Object.values(views).find(
        (v) => !v.classList.contains("hidden"),
      );
      const itemsToDiscard = [];

      activeView
        .querySelectorAll('.btn-toggle[data-state="discard"]')
        .forEach((btn) => {
          const container =
            btn.closest(".action-row") || btn.closest(".version-row");
          const bundleTarget = container
            ? container.querySelector(".bundle-target")?.textContent ||
              container.querySelector(".version-name")?.textContent
            : "";
          if (bundleTarget) {
            itemsToDiscard.push(bundleTarget);
          }
        });

      if (itemsToDiscard.length === 0) {
        alert("No hay elementos marcados para descartar/eliminar.");
        return;
      }

      const confirmAction = confirm(
        `¿Está seguro de procesar y eliminar ${itemsToDiscard.length} bundles seleccionados?`,
      );
      if (!confirmAction) return;

      try {
        const response = await fetch("/extension-api/authorize-cleanup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            flow: currentFlow,
            targets: itemsToDiscard,
          }),
        });

        const result = await response.json();
        if (result.status === "success") {
          alert("Proceso de limpieza ejecutado correctamente.");
          location.reload();
        } else {
          alert("Error al ejecutar la limpieza: " + result.message);
        }
      } catch (error) {
        console.error("Error al enviar autorización:", error);
        alert("Error de comunicación con el backend.");
      }
    });

  // Inicialización
  recalculateMetrics();
});
