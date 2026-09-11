document.addEventListener("DOMContentLoaded", () => {
  // ==========================================
  // CONFIGURACIÓN Y ESTADO INICIAL
  // ==========================================
  let totalSpaceBytes = 0;
  let freeSpaceBytes = 0;
  // Vistas
  const viewNewFlowMain = document.getElementById("view-new-flow-main");
  const viewNewFlowHistory = document.getElementById("view-new-flow-history");
  const viewLegacyFlow = document.getElementById("view-legacy-flow");

  // Botones de Navegación
  const btnSwitchFlow = document.getElementById("btn-switch-flow");
  const btnGoHistory = document.getElementById("btn-go-history");
  const btnSelectEnv = document.getElementById("btn-select-env");
  const btnAuthorize = document.getElementById("btn-authorize");

  // Elementos de Métricas
  const elTotalSpace = document.getElementById("metric-total-space");
  const elFreeSpace = document.getElementById("metric-free-space");
  const elResultSpace = document.getElementById("metric-result-space");

  // Valores base de métricas
  let totalSpace = 80;
  let freeSpace = 16;
  let resultSpace = totalSpace - freeSpace;

  // Estado del flujo actual ('NEW' / 'LEGACY')
  let currentFlow = "NEW";

  // ==========================================
  // FUNCIÓN: Actualizar Métricas
  // ==========================================
  // 1. Obtener datos de S3
  function fetchS3Data() {
    fetch("/api/get-s3-bundles")
      .then((res) => res.json())
      .then((data) => {
        if (data.status === "SUCCESS") {
          totalSpaceBytes = data.metrics.totalSpaceGB * 1024 ** 3;
          freeSpaceBytes = data.metrics.freeSpaceGB * 1024 ** 3;

          // Renderizar dinámicamente
          renderS3Items(data.items);
          updateMetricsDisplay();
        }
      });
  }

  // 2. Modificación del Toggle
  function toggleStatus(button) {
    const currentState = button.getAttribute("data-state");
    // Obtener el peso real en bytes del atributo
    const itemSizeBytes =
      parseFloat(button.getAttribute("data-size-bytes")) || 0;

    if (currentState === "preserve") {
      button.setAttribute("data-state", "discard");
      // ... estilos visuales ...
      freeSpaceBytes += itemSizeBytes; // Sumar peso real
    } else {
      button.setAttribute("data-state", "preserve");
      // ... estilos visuales ...
      freeSpaceBytes -= itemSizeBytes; // Restar peso real
    }

    updateMetricsDisplay();
  }

  // 3. Renderizar métricas
  function updateMetricsDisplay() {
    const resultBytes = totalSpaceBytes - freeSpaceBytes;

    elTotalSpace.textContent = `${(totalSpaceBytes / 1024 ** 3).toFixed(2)} GB`;
    elFreeSpace.textContent = `${(freeSpaceBytes / 1024 ** 3).toFixed(2)} GB`;
    elResultSpace.textContent = `${(resultBytes / 1024 ** 3).toFixed(2)} GB`;
  }

  // ==========================================
  // FUNCIÓN: Alternar Estado de Toggle
  // ==========================================
  function toggleStatus(button) {
    const currentState = button.getAttribute("data-state");
    const iconEl = button.querySelector(".icon");
    const labelEl = button.querySelector(".label");

    if (currentState === "preserve") {
      // Conservado -> Descartado
      button.setAttribute("data-state", "discard");
      button.classList.remove("status-preserved");
      button.classList.add("status-discarded");

      if (iconEl) iconEl.innerHTML = "&#10008;";
      if (labelEl) labelEl.textContent = "Descartado";

      // Al descartar, incrementa el espacio a liberar
      freeSpace += BUNDLE_SIZE_GB;
    } else {
      // Descartado -> Conservado
      button.setAttribute("data-state", "preserve");
      button.classList.remove("status-discarded");
      button.classList.add("status-preserved");

      if (iconEl) iconEl.innerHTML = "&#10004;";
      if (labelEl) labelEl.textContent = "Conservado";

      // Al conservar, disminuye el espacio a liberar
      freeSpace -= BUNDLE_SIZE_GB;
    }

    updateMetricsDisplay();
  }

  // ==========================================
  // NAVEGACIÓN ENTRE VISTAS
  // ==========================================
  function showView(viewToShow) {
    [viewNewFlowMain, viewNewFlowHistory, viewLegacyFlow].forEach((view) => {
      if (view) {
        view.classList.remove("active");
        view.classList.add("hidden");
      }
    });

    if (viewToShow) {
      viewToShow.classList.remove("hidden");
      viewToShow.classList.add("active");
    }
  }

  // Cambiar entre NEW FLOW y LEGACY FLOW desde el Header
  btnSwitchFlow.addEventListener("click", () => {
    if (currentFlow === "NEW") {
      currentFlow = "LEGACY";
      showView(viewLegacyFlow);
      btnSwitchFlow.textContent = "Ver New Flow";
    } else {
      currentFlow = "NEW";
      showView(viewNewFlowMain);
      btnSwitchFlow.textContent = "Seleccionar flujo";
    }
  });

  // Ir al Histórico de New Flow
  btnGoHistory.addEventListener("click", () => {
    showView(viewNewFlowHistory);
  });

  // Alternar Filtro de Ambiente en Histórico (UAT / PROD-1)
  btnSelectEnv.addEventListener("click", () => {
    const currentText = btnSelectEnv.textContent;
    if (currentText.includes("PROD-1")) {
      btnSelectEnv.textContent = "Ambiente: UAT";
    } else {
      btnSelectEnv.textContent = "Ambiente: PROD-1";
    }
  });

  // ==========================================
  // EVENT DELEGATION PARA TOGGLES DE ESTADO
  // ==========================================
  document.addEventListener("click", (e) => {
    const toggleBtn = e.target.closest(".btn-toggle");
    if (toggleBtn) {
      toggleStatus(toggleBtn);
    }
  });

  // ==========================================
  // EVENTO: AUTORIZAR
  // ==========================================
  btnAuthorize.addEventListener("click", () => {
    const itemsToPreserve = [];
    const itemsToDiscard = [];

    const activeSection = document.querySelector(".view-section.active");
    if (activeSection) {
      const toggleButtons = activeSection.querySelectorAll(".btn-toggle");
      toggleButtons.forEach((btn) => {
        const state = btn.getAttribute("data-state");
        const parentRow = btn.closest(".action-row, .version-row, li");
        const pathOrName = parentRow
          ? parentRow.innerText.replace(/\n/g, " ").trim()
          : "";

        if (pathOrName) {
          if (state === "preserve") itemsToPreserve.push(pathOrName);
          if (state === "discard") itemsToDiscard.push(pathOrName);
        }
      });
    }

    const payload = {
      timestamp: new Date().toISOString(),
      activeFlow: currentFlow,
      metrics: { totalSpace, freeSpace, resultSpace },
      details: {
        preserveList: itemsToPreserve,
        discardList: itemsToDiscard,
      },
    };

    // Enviar datos al Backend
    fetch("/api/authorize-cleanup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.status === "SUCCESS") {
          alert(
            `Limpieza autorizada\n\n` +
              `Archivos eliminados en S3: ${data.deletedCount}\n` +
              `Archivos preservados: ${data.preservedCount}\n` +
              `Reporte CSV generado: ${data.reportFileName}`,
          );
          location.reload(); // Recargar
        } else {
          alert(`Error en la ejecución: ${data.message}`);
        }
      })
      .catch((err) =>
        console.error("Error al conectar con backend Python:", err),
      );
  });

  // Inicializar display de métricas
  updateMetricsDisplay();
});
