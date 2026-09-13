// ==========================================
// 1. TIENDA DE ESTADO GLOBAL (APP STATE)
// ==========================================
const AppState = {
  // Parámetros y Métricas
  periodoEjecucion: "Sep 2026",
  criterioAntiguedad: "> 6 meses",
  espacioTotalMB: 0,

  // Listas de datos
  bundles: [],

  // Vista activa
  currentFlow: "HOME", // "HOME", "NEW", "LEGACY"
  currentSection: "CLEANUP", // "CLEANUP" o "HISTORIC"
  currentEnv: "UAT", // "UAT" o "PROD-1" (Para NEW FLOW)

  // Inicialización de datos desde Flask Backend
  async init() {
    try {
      const url = getWebAppBackendUrl("/scan-bundles");
      const response = await fetch(url);
      const data = await response.json();

      if (data.status === "success") {
        this.bundles = data.bundles;
        this.periodoEjecucion = data.periodo_ejecucion || this.periodoEjecucion;

        // Calcular espacio total en MB
        this.espacioTotalMB = this.bundles.reduce(
          (acc, b) => acc + (b.size_mb || 0),
          0,
        );

        this.renderMetrics();
        this.renderCurrentView();
      }
    } catch (error) {
      console.error("Error al conectar con el backend Flask:", error);
    }
  },

  // Recálculo reactivo de métricas
  getMetrics() {
    const espacioALiberar = this.bundles
      .filter((b) => b.estado === "Descartado")
      .reduce((acc, b) => acc + (b.size_mb || 0), 0);

    const espacioResultante = Math.max(
      0,
      this.espacioTotalMB - espacioALiberar,
    );

    return {
      total: this.espacioTotalMB.toFixed(2),
      aLiberar: espacioALiberar.toFixed(2),
      resultante: espacioResultante.toFixed(2),
    };
  },

  // Alternar estado de una versión
  toggleStatus(s3_path) {
    const item = this.bundles.find((b) => b.s3_path === s3_path);
    if (item) {
      item.estado = item.estado === "Conservado" ? "Descartado" : "Conservado";
      this.renderMetrics();
      this.renderCurrentView();
    }
  },
};

// ==========================================
// 2. RENDERIZADO DE COMPONENTES UI
// ==========================================

// Actualiza el pie de página con las métricas dinámicas
AppState.renderMetrics = function () {
  const metrics = this.getMetrics();
  document.getElementById("stat-total").innerText = `${metrics.total} MB`;
  document.getElementById("stat-liberar").innerText = `${metrics.aLiberar} MB`;
  document.getElementById("stat-resultante").innerText =
    `${metrics.resultante} MB`;
  document.getElementById("stat-periodo").innerText =
    `Periodo de ejecución: ${this.periodoEjecucion}`;
  document.getElementById("stat-criterio").innerText =
    `Antigüedad de versionamientos: ${this.criterioAntiguedad}`;
};

// Enrutador de Vistas basado en el estado
AppState.renderCurrentView = function () {
  const mainContainer = document.getElementById("main-content-container");
  if (!mainContainer) return;

  if (this.currentFlow === "HOME") {
    mainContainer.innerHTML = renderHomeView();
  } else if (this.currentFlow === "NEW" && this.currentSection === "CLEANUP") {
    mainContainer.innerHTML = renderNewFlowCleanup(this.bundles);
  } else if (this.currentFlow === "NEW" && this.currentSection === "HISTORIC") {
    mainContainer.innerHTML = renderNewFlowHistoric(
      this.bundles,
      this.currentEnv,
    );
  } else if (
    this.currentFlow === "LEGACY" &&
    this.currentSection === "CLEANUP"
  ) {
    mainContainer.innerHTML = renderLegacyCleanup(this.bundles);
  } else if (
    this.currentFlow === "LEGACY" &&
    this.currentSection === "HISTORIC"
  ) {
    mainContainer.innerHTML = renderLegacyHistoric(this.bundles);
  }
};

// ==========================================
// 3. PLANTILLAS DE VISTAS (COMPONENTES SVG/HTML)
// ==========================================

// Vista Base (Pantalla de bienvenida)
function renderHomeView() {
  return `
        <div class="home-card">
            <div class="bird-icon-container">
                <svg width="80" height="80" viewBox="0 0 24 24" fill="#00A896">
                    <path d="M21 5c-1.11-.35-2.33-.5-3.5-.5-1.95 0-4.05.4-5.5 1.5-1.45-1.1-3.55-1.5-5.5-1.5S2.45 4.9 1 6v14.65c0 .25.25.5.5.5.1 0 .15-.05.25-.05C3.2 20.1 5.2 19.5 7 19.5c1.95 0 4.05.4 5.5 1.5 1.35-.85 3.13-1.3 4.96-1.42V6.7c1.19.14 2.34.45 3.39.92.17.08.35.13.53.13.3 0 .62-.22.62-.65V5.5c-.32-.2-.67-.37-1-.5z"/>
                </svg>
            </div>
            <h2>Gestión y Automatización de Eliminación</h2>
            <h3>Bundles Dataiku en S3</h3>
        </div>
    `;
}

// Vista NEW FLOW | Versionamiento de Proyectos por Ambiente (Limpieza)
function renderNewFlowCleanup(bundles) {
  const newBundles = bundles.filter((b) => b.flow === "NEW");
  const uatItems = newBundles.filter((b) => b.env === "UAT");
  const prodItems = newBundles.filter((b) => b.env === "PROD-1");

  return `
        <div class="view-header">
            <h2>NEW FLOW | Versionamiento de Proyectos por Ambiente</h2>
            <button class="btn-subnav" onclick="AppState.currentSection='HISTORIC'; AppState.renderCurrentView();">Consultar histórico</button>
        </div>
        <div class="cards-grid-2">
            <div class="env-card">
                <h3 class="env-title">UAT</h3>
                ${renderProjectGroups(uatItems)}
            </div>
            <div class="env-card">
                <h3 class="env-title">PROD-1</h3>
                ${renderProjectGroups(prodItems)}
            </div>
        </div>
    `;
}

// Vista NEW FLOW | Histórico por Ambiente
function renderNewFlowHistoric(bundles, selectedEnv) {
  const items = bundles.filter(
    (b) => b.flow === "NEW" && b.env === selectedEnv,
  );

  return `
        <div class="view-header">
            <h2>NEW FLOW | Histórico de Proyectos por Ambiente</h2>
            <select class="dropdown-select" onchange="AppState.currentEnv=this.value; AppState.renderCurrentView();">
                <option value="UAT" ${selectedEnv === "UAT" ? "selected" : ""}>UAT</option>
                <option value="PROD-1" ${selectedEnv === "PROD-1" ? "selected" : ""}>PROD-1</option>
            </select>
        </div>
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Servidor</th>
                        <th>Proyecto</th>
                        <th>Versiones</th>
                        <th>Estatus final</th>
                    </tr>
                </thead>
                <tbody>
                    ${items
                      .map(
                        (b) => `
                        <tr>
                            <td>${b.nickname}</td>
                            <td>${b.proyecto}</td>
                            <td>${b.filename}</td>
                            <td>
                                <button class="status-toggle-btn ${b.estado.toLowerCase()}" onclick="AppState.toggleStatus('${b.s3_path}')">
                                    <span class="icon">${b.estado === "Conservado" ? "✔" : "✖"}</span>
                                    <span>${b.estado}</span>
                                </button>
                            </td>
                        </tr>
                    `,
                      )
                      .join("")}
                </tbody>
            </table>
        </div>
    `;
}

// Helper para agrupar versiones por proyecto en las tarjetas
function renderProjectGroups(items) {
  const grouped = {};
  items.forEach((item) => {
    if (!grouped[item.proyecto]) grouped[item.proyecto] = [];
    grouped[item.proyecto].push(item);
  });

  return Object.keys(grouped)
    .map(
      (proj) => `
        <div class="project-box">
            <span class="server-tag">${grouped[proj][0].nickname}</span>
            <div class="versions-list">
                ${grouped[proj]
                  .map(
                    (b) => `
                    <div class="version-row">
                        <span class="version-name">${b.proyecto}/${b.filename}</span>
                        <button class="status-toggle-btn ${b.estado.toLowerCase()}" onclick="AppState.toggleStatus('${b.s3_path}')">
                            <span class="icon">${b.estado === "Conservado" ? "✔" : "✖"}</span>
                            <span>${b.estado}</span>
                        </button>
                    </div>
                `,
                  )
                  .join("")}
            </div>
        </div>
    `,
    )
    .join("");
}

// Vista LEGACY FLOW | Versionamiento (Limpieza)
function renderLegacyCleanup(bundles) {
  const items = bundles.filter((b) => b.flow === "LEGACY");

  return `
        <div class="view-header">
            <h2>LEGACY FLOW | Versionamiento de Proyectos</h2>
            <button class="btn-subnav" onclick="AppState.currentSection='HISTORIC'; AppState.renderCurrentView();">Consultar histórico</button>
        </div>
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Proyecto</th>
                        <th>Versiones</th>
                        <th>Estatus final</th>
                    </tr>
                </thead>
                <tbody>
                    ${items
                      .map(
                        (b) => `
                        <tr>
                            <td>${b.proyecto}</td>
                            <td>${b.s3_path}</td>
                            <td>
                                <button class="status-toggle-btn ${b.estado.toLowerCase()}" onclick="AppState.toggleStatus('${b.s3_path}')">
                                    <span class="icon">${b.estado === "Conservado" ? "✔" : "✖"}</span>
                                    <span>${b.estado}</span>
                                </button>
                            </td>
                        </tr>
                    `,
                      )
                      .join("")}
                </tbody>
            </table>
        </div>
    `;
}

// Vista LEGACY FLOW | Histórico
function renderLegacyHistoric(bundles) {
  const items = bundles.filter((b) => b.flow === "LEGACY");

  return `
        <div class="view-header">
            <h2>LEGACY FLOW | Histórico de Proyectos</h2>
        </div>
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Proyecto</th>
                        <th>Versiones</th>
                        <th>Estatus final</th>
                    </tr>
                </thead>
                <tbody>
                    ${items
                      .map(
                        (b) => `
                        <tr>
                            <td>${b.proyecto}</td>
                            <td>${b.s3_path}</td>
                            <td>
                                <button class="status-toggle-btn ${b.estado.toLowerCase()}" onclick="AppState.toggleStatus('${b.s3_path}')">
                                    <span class="icon">${b.estado === "Conservado" ? "✔" : "✖"}</span>
                                    <span>${b.estado}</span>
                                </button>
                            </td>
                        </tr>
                    `,
                      )
                      .join("")}
                </tbody>
            </table>
        </div>
    `;
}

// ==========================================
// 4. EVENTOS DE ACCIONES GLOBALES (BOTONES)
// ==========================================

// Disparador del botón "Autorizar"
async function triggerAuthorize() {
  if (
    !confirm(
      "¿Está seguro de autorizar la eliminación en S3 de las versiones en estado 'Descartado'?",
    )
  ) {
    return;
  }

  try {
    const url = getWebAppBackendUrl("/authorize-cleanup");
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bundles: AppState.bundles }),
    });

    if (response.ok) {
      const blob = await response.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = `Reporte_Limpieza_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();

      // Recargar vista tras la limpieza
      alert("Limpieza ejecutada con éxito. El reporte CSV se ha descargado.");
      AppState.init();
    }
  } catch (error) {
    alert("Error al procesar la autorización.");
  }
}

// Disparador del botón "Consulta Global"
function triggerGlobalReport() {
  const url = getWebAppBackendUrl("/global-report");
  window.open(url, "_blank");
}

// Escuchador del selector de flujo superior
document.addEventListener("DOMContentLoaded", () => {
  AppState.init();

  const flowDropdown = document.getElementById("select-flow-dropdown");
  if (flowDropdown) {
    flowDropdown.addEventListener("change", (e) => {
      const val = e.target.value;
      if (val === "NEW") {
        AppState.currentFlow = "NEW";
        AppState.currentSection = "CLEANUP";
      } else if (val === "LEGACY") {
        AppState.currentFlow = "LEGACY";
        AppState.currentSection = "CLEANUP";
      } else {
        AppState.currentFlow = "HOME";
      }
      AppState.renderCurrentView();
    });
  }
});
