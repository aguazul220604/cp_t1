// Estado global de la aplicación
let allBundles = [];
let currentFlow = "NEW"; // 'NEW' o 'LEGACY'
let isHistoricView = false; // false = Versionamiento, true = Histórico
let selectedEnv = "UAT"; // 'UAT' o 'PROD-1' para vistas individuales

document.addEventListener("DOMContentLoaded", () => {
  fetchBundles();
  setupEventListeners();
});

async function fetchBundles() {
  try {
    const response = await fetch("/api/get-bundles");
    allBundles = await response.json();
    renderView();
  } catch (error) {
    console.error("Error al cargar los bundles:", error);
  }
}

function setupEventListeners() {
  document.getElementById("btn-select-flow").addEventListener("click", () => {
    currentFlow = currentFlow === "NEW" ? "LEGACY" : "NEW";
    isHistoricView = false;
    renderView();
  });

  document
    .getElementById("btn-toggle-historic")
    ?.addEventListener("click", () => {
      isHistoricView = !isHistoricView;
      renderView();
    });

  document
    .getElementById("btn-authorize")
    .addEventListener("click", handleAuthorize);
}

function renderView() {
  updateHeaderTitle();

  const container = document.getElementById("view-container");
  container.innerHTML = "";

  if (currentFlow === "NEW" && !isHistoricView) {
    // Vista 1: NEW FLOW - Versionamiento por Ambiente (UAT vs PROD-1)
    container.appendChild(createDualEnvView());
  } else if (currentFlow === "NEW" && isHistoricView) {
    // Vista 2: NEW FLOW - Histórico por Ambiente
    container.appendChild(createHistoricView("NEW"));
  } else if (currentFlow === "LEGACY" && !isHistoricView) {
    // Vista 3: LEGACY FLOW - Versionamiento
    container.appendChild(createSingleTableView("LEGACY", false));
  } else if (currentFlow === "LEGACY" && isHistoricView) {
    // Vista 4: LEGACY FLOW - Histórico
    container.appendChild(createHistoricView("LEGACY"));
  }

  calculateMetrics();
}

function updateHeaderTitle() {
  const titleElem = document.getElementById("view-title");
  const flowText = currentFlow === "NEW" ? "NEW FLOW" : "LEGACY FLOW";
  const viewText = isHistoricView
    ? "Histórico de Proyectos"
    : "Versionamiento de Proyectos";
  titleElem.textContent = `${flowText} | ${viewText}`;
}

// Vista 1: Doble columna (UAT y PROD-1)
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

// Vista 2 y 4: Función generadora para Históricos (corrige el ReferenceError)
function createHistoricView(flow) {
  const wrapper = document.createElement("div");
  wrapper.className = "historic-container";

  if (flow === "NEW") {
    const navDiv = document.createElement("div");
    navDiv.className = "historic-selector-bar";
    navDiv.innerHTML = `<label>Seleccionar ambiente: </label>`;

    const selector = document.createElement("select");
    selector.innerHTML = `<option value="UAT">UAT</option><option value="PROD-1">PROD-1</option>`;
    selector.value = selectedEnv;
    selector.addEventListener("change", (e) => {
      selectedEnv = e.target.value;
      renderView();
    });
    navDiv.appendChild(selector);
    wrapper.appendChild(navDiv);
  }

  const filtered = allBundles.filter(
    (b) =>
      b.flow === flow &&
      b.status === "Preservado" &&
      (flow === "NEW" ? b.env === selectedEnv : true),
  );

  wrapper.appendChild(buildBundleListUI(filtered, true));
  return wrapper;
}

// Vista 3: Tabla Única para Legacy Flow
function createSingleTableView(flow, isHistoric) {
  const wrapper = document.createElement("div");
  const filtered = allBundles.filter((b) => b.flow === flow);
  wrapper.appendChild(buildBundleListUI(filtered, false));
  return wrapper;
}

// Render de filas con Toggle
function buildBundleListUI(bundles, showServer = false) {
  const list = document.createElement("div");
  list.className = "bundle-list";

  if (bundles.length === 0) {
    list.innerHTML =
      '<p class="empty-msg">No hay elementos registrados en esta vista.</p>';
    return list;
  }

  bundles.forEach((item) => {
    const row = document.createElement("div");
    row.className = `bundle-row ${item.status.toLowerCase()}`;
    const isPreserved = item.status === "Preservado";

    row.innerHTML = `
            ${showServer ? `<span class="col-server">${item.server || "N/A"}</span>` : ""}
            <span class="col-project"><strong>${item.project}</strong></span>
            <span class="col-filename">${item.filename}</span>
            <span class="col-size">${item.size_gb} GB</span>
            <button class="btn-toggle ${isPreserved ? "preserved" : "discarded"}" data-path="${item.s3_path}">
                ${isPreserved ? "✔ Preservado" : "✖ Descartado"}
            </button>
        `;

    row.querySelector(".btn-toggle").addEventListener("click", () => {
      toggleStatus(item.s3_path);
    });

    list.appendChild(row);
  });

  return list;
}

function toggleStatus(s3Path) {
  const item = allBundles.find((b) => b.s3_path === s3Path);
  if (item) {
    item.status = item.status === "Preservado" ? "Descartado" : "Preservado";

    fetch("/api/save-selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(allBundles),
    });

    renderView();
  }
}

function calculateMetrics() {
  const totalOccupied = allBundles.reduce(
    (acc, curr) => acc + (curr.size_gb || 0),
    0,
  );
  const toLiberate = allBundles
    .filter((b) => b.status === "Descartado")
    .reduce((acc, curr) => acc + (curr.size_gb || 0), 0);
  const resulting = totalOccupied - toLiberate;

  document.getElementById("stat-total").textContent =
    `${totalOccupied.toFixed(2)} GB`;
  document.getElementById("stat-liberate").textContent =
    `${toLiberate.toFixed(2)} GB`;
  document.getElementById("stat-result").textContent =
    `${resulting.toFixed(2)} GB`;
}

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
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `reporte_limpieza_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();

      alert("Proceso de eliminación completado y reporte descargado.");
      fetchBundles();
    } else {
      alert("Ocurrió un error al ejecutar la autorización.");
    }
  } catch (error) {
    console.error("Error al autorizar:", error);
  }
}
