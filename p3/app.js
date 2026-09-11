// Estado global de la aplicación
let allBundles = [];
let currentFlow = "NEW"; // 'NEW' o 'LEGACY'
let isHistoricView = false; // false = Versionamiento, true = Histórico
let selectedEnv = "UAT"; // 'UAT' o 'PROD-1' para vistas individuales

// Inicialización de la WebApp
document.addEventListener("DOMContentLoaded", () => {
  fetchBundles();
  setupEventListeners();
});

// 1. OBTENER DATOS DEL BACKEND
async function fetchBundles() {
  try {
    const response = await fetch("/api/get-bundles");
    allBundles = await response.json();
    renderView();
  } catch (error) {
    console.error("Error al cargar los bundles:", error);
  }
}

// 2. CONTROLADORES DE NAVEGACIÓN Y EVENTOS
function setupEventListeners() {
  // Cambio entre NEW FLOW y LEGACY FLOW
  document.getElementById("btn-select-flow").addEventListener("click", () => {
    currentFlow = currentFlow === "NEW" ? "LEGACY" : "NEW";
    isHistoricView = false; // Reinicia a la vista principal del flujo
    renderView();
  });

  // Alternar entre Versionamiento e Histórico
  document
    .getElementById("btn-toggle-historic")
    ?.addEventListener("click", () => {
      isHistoricView = !isHistoricView;
      renderView();
    });

  // Botón principal de Ejecución / Limpieza
  document
    .getElementById("btn-authorize")
    .addEventListener("click", handleAuthorize);
}

// 3. RENDERIZADO DINÁMICO DE VISTAS (1 a 4)
function renderView() {
  updateHeaderTitle();

  const container = document.getElementById("view-container");
  container.innerHTML = "";

  if (currentFlow === "NEW" && !isHistoricView) {
    // VISTA 1: NEW FLOW - Versionamiento por Ambiente (UAT vs PROD-1)
    container.appendChild(createDualEnvView());
  } else if (currentFlow === "NEW" && isHistoricView) {
    // VISTA 2: NEW FLOW - Histórico por Ambiente
    container.appendChild(createHistoricView("NEW"));
  } else if (currentFlow === "LEGACY" && !isHistoricView) {
    // VISTA 3: LEGACY FLOW - Versionamiento
    container.appendChild(createSingleTableView("LEGACY", false));
  } else if (currentFlow === "LEGACY" && isHistoricView) {
    // VISTA 4: LEGACY FLOW - Histórico
    container.appendChild(createSingleTableView("LEGACY", true));
  }

  calculateMetrics();
}

// Actualiza los encabezados de la pantalla según el mockup
function updateHeaderTitle() {
  const titleElem = document.getElementById("view-title");
  const flowText = currentFlow === "NEW" ? "NEW FLOW" : "LEGACY FLOW";
  const viewText = isHistoricView
    ? "Histórico de Proyectos"
    : "Versionamiento de Proyectos";
  titleElem.textContent = `${flowText} | ${viewText}`;
}

// Generador de Vista 1 (Columnas UAT y PROD-1 lado a lado)
function createDualEnvView() {
  const wrapper = document.createElement("div");
  wrapper.className = "dual-env-container";

  ["UAT", "PROD-1"].forEach((env) => {
    const col = document.createElement("div");
    col.className = "env-column";
    col.innerHTML = `<h3>${env}</h3>`;

    const envBundles = allBundles.filter(
      (b) => b.flow === "NEW" && b.env === env,
    );
    col.appendChild(buildBundleListUI(envBundles));
    wrapper.appendChild(col);
  });

  return wrapper;
}

// Generador de Tablas para Vistas 2, 3 y 4
function createSingleTableView(flow, isHistoric) {
  const wrapper = document.createElement("div");
  const filtered = allBundles.filter(
    (b) => b.flow === flow && (isHistoric ? b.status === "Preservado" : true),
  );

  // Si es histórico de New Flow, incluye selector de ambiente
  if (flow === "NEW" && isHistoric) {
    const selector = document.createElement("select");
    selector.innerHTML = `<option value="UAT">UAT</option><option value="PROD-1">PROD-1</option>`;
    selector.value = selectedEnv;
    selector.addEventListener("change", (e) => {
      selectedEnv = e.target.value;
      renderView();
    });
    wrapper.appendChild(selector);
  }

  const targetList =
    flow === "NEW" ? filtered.filter((b) => b.env === selectedEnv) : filtered;
  wrapper.appendChild(buildBundleListUI(targetList, true));
  return wrapper;
}

// Construye los ítems interactivos con botón Toggle (Check/X)
function buildBundleListUI(bundles, showServer = false) {
  const list = document.createElement("div");
  list.className = "bundle-list";

  bundles.forEach((item) => {
    const row = document.createElement("div");
    row.className = `bundle-row ${item.status.toLowerCase()}`;

    const isPreserved = item.status === "Preservado";

    row.innerHTML = `
            ${showServer ? `<span class="col-server">${item.server}</span>` : ""}
            <span class="col-project"><strong>${item.project}</strong></span>
            <span class="col-filename">${item.filename}</span>
            <span class="col-size">${item.size_gb} GB</span>
            <button class="btn-toggle ${isPreserved ? "preserved" : "discarded"}" data-path="${item.s3_path}">
                ${isPreserved ? "✔ Preservado" : "✖ Descartado"}
            </button>
        `;

    // Evento para cambiar de estado al dar clic
    row.querySelector(".btn-toggle").addEventListener("click", (e) => {
      toggleStatus(item.s3_path);
    });

    list.appendChild(row);
  });

  return list;
}

// 4. CAMBIO DE ESTADO Y RECÁLCULO
function toggleStatus(s3Path) {
  const item = allBundles.find((b) => b.s3_path === s3Path);
  if (item) {
    item.status = item.status === "Preservado" ? "Descartado" : "Preservado";

    // Guardar estado persistente en background
    fetch("/api/save-selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(allBundles),
    });

    renderView();
  }
}

// 5. CÁLCULO DE MÉTRICAS DEL PIE DE PÁGINA
function calculateMetrics() {
  const totalOccupied = allBundles.reduce((acc, curr) => acc + curr.size_gb, 0);
  const toLiberate = allBundles
    .filter((b) => b.status === "Descartado")
    .reduce((acc, curr) => acc + curr.size_gb, 0);
  const resulting = totalOccupied - toLiberate;

  document.getElementById("stat-total").textContent =
    `${totalOccupied.toFixed(2)} GB`;
  document.getElementById("stat-liberate").textContent =
    `${toLiberate.toFixed(2)} GB`;
  document.getElementById("stat-result").textContent =
    `${resulting.toFixed(2)} GB`;
}

// 6. ACCIÓN AUTORIZAR Y DESCARGA AUTOMÁTICA DEL REPORTES
async function handleAuthorize() {
  if (
    !confirm(
      "¿Está seguro de ejecutar la eliminación física en S3 para los archivos marcados como Descartados?",
    )
  ) {
    return;
  }

  try {
    const response = await fetch("/api/authorize-cleanup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(allBundles),
    });

    if (response.ok) {
      // Recibir el binario CSV devuelto por el backend
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `reporte_limpieza_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();

      alert("Proceso de eliminación completado y reporte descargado.");
      fetchBundles(); // Recargar datos actualizados
    } else {
      alert("Ocurrió un error al ejecutar la autorización.");
    }
  } catch (error) {
    console.error("Error al autorizar:", error);
  }
}
