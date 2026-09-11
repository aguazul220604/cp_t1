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

  // Corrección de texto según maqueta visual: "Seleccionar ambiente"
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

    // Si el botón está dentro de un historial, deshabilitar toggle (solo lectura)
    const activeView = getActiveView();
    if (activeView === views.newHistory || activeView === views.legacyHistory) {
      return;
    }

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

  // Helper para obtener la vista activa
  function getActiveView() {
    return Object.values(views).find(
      (v) => v && !v.classList.contains("hidden"),
    );
  }

  // ==========================================
  // 3. RECÁLCULO DINÁMICO DE MÉTRICAS DE ESPACIO
  // ==========================================
  function recalculateMetrics() {
    let bytesToFree = 0;
    const activeView = getActiveView();
    if (!activeView) return;

    // Sumar bytes de todos los botones marcados como discard
    const discardButtons = activeView.querySelectorAll(
      '.btn-toggle[data-state="discard"]',
    );

    discardButtons.forEach((btn) => {
      const bytes = parseFloat(btn.getAttribute("data-size-bytes") || "0");
      bytesToFree += bytes;
    });

    // Base de cálculo inicial (se puede ajustar dinámicamente según API)
    const totalSizeBytes = 80 * 1024 * 1024 * 1024; // 80 GB
    const freeSizeBytes = bytesToFree;
    const resultSizeBytes = Math.max(0, totalSizeBytes - freeSizeBytes);

    const totalElem = document.getElementById("metric-total-space");
    const freeElem = document.getElementById("metric-free-space");
    const resultElem = document.getElementById("metric-result-space");

    if (totalElem) totalElem.textContent = formatBytes(totalSizeBytes);
    if (freeElem) freeElem.textContent = formatBytes(freeSizeBytes);
    if (resultElem) resultElem.textContent = formatBytes(resultSizeBytes);
  }

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 GB";
    const gb = bytes / (1024 * 1024 * 1024);
    return gb.toFixed(2) + " GB";
  }

  // Helper genérico para renderizar un botón de estado con tamaño en bytes
  function renderToggleButton(status, sizeBytes = 0) {
    const isPreserve = status.toLowerCase() === "preserve";
    const stateAttr = isPreserve ? "preserve" : "discard";
    const classStatus = isPreserve ? "status-preserved" : "status-discarded";
    const icon = isPreserve ? "&#10004;" : "&#10008;";
    const label = isPreserve ? "Conservado" : "Descartado";

    return `
      <button class="btn-toggle ${classStatus}" data-state="${stateAttr}" data-size-bytes="${sizeBytes}">
        <span class="icon">${icon}</span>
        <span class="label">${label}</span>
      </button>
    `;
  }

  // ==========================================
  // 4. INTEGRACIÓN CON BACKEND (FETCH API)
  // ==========================================

  // Cargar datos principales de New Flow (Servidores UAT y PROD-1)
  async function loadNewFlowData() {
    try {
      const response = await fetch("/extension-api/get-bundles-new");
      const data = await response.json();

      // Mapeo dinámico para contenedores UAT y PROD-1 si se recibe payload
      if (data && data.environments) {
        renderNewFlowCards(data.environments);
      }
      recalculateMetrics();
    } catch (error) {
      console.error("Error cargando bundles de New Flow:", error);
    }
  }

  // Función de apoyo para renderizar tarjetas UAT y PROD-1
  function renderNewFlowCards(environments) {
    const uatContainer = document.getElementById("container-uat-bundles");
    const prodContainer = document.getElementById("container-prod-bundles");

    if (uatContainer && environments.UAT) {
      uatContainer.innerHTML = buildEnvironmentCardHTML(environments.UAT);
    }
    if (prodContainer && environments["PROD-1"]) {
      prodContainer.innerHTML = buildEnvironmentCardHTML(
        environments["PROD-1"],
      );
    }
  }

  function buildEnvironmentCardHTML(serversData) {
    let html = "";
    // Iterar nicknames (DKUD, RISP, DISU, DKUU, etc.)
    Object.keys(serversData).forEach((nickname) => {
      html += `<div class="nickname-group"><h4>${nickname}</h4><ul>`;
      serversData[nickname].forEach((item) => {
        html += `
          <li class="action-row">
            <span class="bundle-target">${item.bundle_id || item.name}</span>
            ${renderToggleButton(item.status || "preserve", item.size_bytes || 0)}
          </li>
        `;
      });
      html += `</ul></div>`;
    });
    return html;
  }

  // Cargar datos principales de Legacy Flow
  async function loadLegacyData() {
    try {
      const response = await fetch("/extension-api/get-bundles-legacy");
      const data = await response.json();

      const tbody = document.getElementById("tbody-legacy-main");
      if (tbody && Array.isArray(data)) {
        tbody.innerHTML = "";
        data.forEach((item) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td class="cell-project">${item.project}</td>
            <td class="cell-versions" colspan="2">
              <div class="version-row">
                <span class="version-name">${item.version}</span>
                ${renderToggleButton(item.status || "preserve", item.size_bytes || 0)}
              </div>
            </td>
          `;
          tbody.appendChild(tr);
        });
      }
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
        const sizeBytes = item.size_bytes || 0;

        if (flowType === "NEW") {
          tr.innerHTML = `
            <td class="cell-server">${item.server || item.nickname || ""}</td>
            <td class="cell-project">${item.project}</td>
            <td class="cell-versions" colspan="2">
              <div class="version-row">
                <span class="version-name">${item.version}</span>
                ${renderToggleButton(item.status, sizeBytes)}
              </div>
            </td>
          `;
        } else {
          tr.innerHTML = `
            <td class="cell-project">${item.project}</td>
            <td class="cell-versions" colspan="2">
              <div class="version-row">
                <span class="version-name">${item.version}</span>
                ${renderToggleButton(item.status, sizeBytes)}
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
      const activeView = getActiveView();
      if (!activeView) return;

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
            itemsToDiscard.push({
              target: bundleTarget,
              size_bytes: parseFloat(
                btn.getAttribute("data-size-bytes") || "0",
              ),
            });
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
