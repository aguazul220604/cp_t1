// ==========================================
// APP STATE
// ==========================================
window.AppState = {
  periodoEjecucion: "Sep 2026",
  criterioAntiguedad: "> 6 meses",
  espacioTotalMB: 0,

  // Separación de estados para evitar cruce de datos
  scanBundles: [], // Provenientes de /scan-bundles (S3 activo)
  historicBundles: [], // Provenientes de /get-historical (Tabla historical)

  currentFlow: "NEW",
  currentSection: "CLEANUP", // "CLEANUP" o "HISTORIC"
  currentEnv: "UAT",

  isLoading: false,

  async init() {
    this.renderCurrentView();
    await this.fetchScanBundles();
  },

  // Obtener versionamiento activo desde S3
  async fetchScanBundles() {
    this.isLoading = true;
    this.renderCurrentView();

    try {
      const url = getWebAppBackendUrl("/scan-bundles");
      const response = await fetch(url);
      const data = await response.json();

      if (data.status === "success") {
        this.scanBundles = data.bundles || [];
        this.periodoEjecucion = data.periodo_ejecucion || this.periodoEjecucion;
        this.criterioAntiguedad =
          data.criterio_antiguedad || this.criterioAntiguedad;
      }
    } catch (error) {
      console.error("Error al obtener /scan-bundles:", error);
    } finally {
      this.isLoading = false;
      this.renderMetrics();
      this.renderCurrentView();
    }
  },

  // Obtener registros preservados desde el dataset 'historical'
  async fetchHistoricBundles() {
    this.isLoading = true;
    this.renderCurrentView();

    try {
      const url = getWebAppBackendUrl("/get-historical");
      const response = await fetch(url);
      const data = await response.json();

      if (data.status === "success") {
        this.historicBundles = data.bundles || [];
      }
    } catch (error) {
      console.error("Error al obtener /get-historical:", error);
    } finally {
      this.isLoading = false;
      this.renderMetrics();
      this.renderCurrentView();
    }
  },

  // Cambiar de sección y cargar el endpoint correspondiente si es necesario
  async switchSection(section) {
    this.currentSection = section;

    if (section === "HISTORIC" && this.historicBundles.length === 0) {
      await this.fetchHistoricBundles();
    } else if (section === "CLEANUP" && this.scanBundles.length === 0) {
      await this.fetchScanBundles();
    } else {
      this.renderMetrics();
      this.renderCurrentView();
    }
  },

  // Retorna los bundles correspondientes a la sección actual
  get activeBundles() {
    return this.currentSection === "CLEANUP"
      ? this.scanBundles
      : this.historicBundles;
  },

  getMetrics() {
    const currentList = this.activeBundles;
    const totalMB = currentList.reduce((acc, b) => acc + (b.size_mb || 0), 0);
    const espacioALiberar = currentList
      .filter((b) => b.estado === "Descartado")
      .reduce((acc, b) => acc + (b.size_mb || 0), 0);

    const espacioResultante = Math.max(0, totalMB - espacioALiberar);

    return {
      total: totalMB.toFixed(2),
      aLiberar: espacioALiberar.toFixed(2),
      resultante: espacioResultante.toFixed(2),
    };
  },

  toggleStatus(s3_path) {
    const item = this.activeBundles.find((b) => b.s3_path === s3_path);
    if (item) {
      item.estado = item.estado === "Conservado" ? "Descartado" : "Conservado";
      this.renderMetrics();
      this.renderCurrentView();
    }
  },
};

// ==========================================
// RENDERIZADO DE VISTAS
// ==========================================

window.AppState.renderMetrics = function () {
  const statTotal = document.getElementById("stat-total");
  const statLiberar = document.getElementById("stat-liberar");
  const statResultante = document.getElementById("stat-resultante");
  const statPeriodo = document.getElementById("stat-periodo");
  const statCriterio = document.getElementById("stat-criterio");

  if (statTotal) statTotal.innerText = `${this.getMetrics().total} MB`;
  if (statLiberar) statLiberar.innerText = `${this.getMetrics().aLiberar} MB`;
  if (statResultante)
    statResultante.innerText = `${this.getMetrics().resultante} MB`;
  if (statPeriodo)
    statPeriodo.innerText = `Periodo de ejecución: ${this.periodoEjecucion}`;
  if (statCriterio)
    statCriterio.innerText = `Antigüedad de versionamientos: ${this.criterioAntiguedad}`;
};

window.AppState.renderCurrentView = function () {
  const mainContainer = document.getElementById("main-content-container");
  if (!mainContainer) return;

  if (this.isLoading) {
    mainContainer.innerHTML = `<div style="text-align:center; padding: 40px; color: #64748b;">Cargando información...</div>`;
    return;
  }

  const bundles = this.activeBundles;

  if (this.currentFlow === "NEW" && this.currentSection === "CLEANUP") {
    mainContainer.innerHTML = renderNewFlowCleanup(bundles);
  } else if (this.currentFlow === "NEW" && this.currentSection === "HISTORIC") {
    mainContainer.innerHTML = renderNewFlowHistoric(bundles, this.currentEnv);
  } else if (
    this.currentFlow === "LEGACY" &&
    this.currentSection === "CLEANUP"
  ) {
    mainContainer.innerHTML = renderLegacyCleanup(bundles);
  } else if (
    this.currentFlow === "LEGACY" &&
    this.currentSection === "HISTORIC"
  ) {
    mainContainer.innerHTML = renderLegacyHistoric(bundles);
  }
};

// ==========================================
// VISTAS
// ==========================================

function renderNewFlowCleanup(bundles) {
  const newBundles = bundles.filter((b) => b.flow === "NEW");
  const uatItems = newBundles.filter((b) => b.env === "UAT");
  const prodItems = newBundles.filter((b) => b.env === "PROD-1");

  return `
        <div class="view-header">
            <h2>NEW FLOW | Versionamiento de Proyectos por Ambiente</h2>
            <button class="btn-subnav" onclick="AppState.switchSection('HISTORIC')">Consultar histórico</button>
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

function renderNewFlowHistoric(bundles, selectedEnv) {
  const items = bundles.filter(
    (b) => b.flow === "NEW" && b.env === selectedEnv,
  );

  return `
        <div class="view-header">
            <h2>NEW FLOW | Histórico de Proyectos por Ambiente</h2>
            <div class="controls-group">
                <button class="btn-subnav" onclick="AppState.switchSection('CLEANUP')">Consultar versionamiento</button>
                <select class="dropdown-select" onchange="AppState.currentEnv=this.value; AppState.renderCurrentView();">
                    <option value="UAT" ${selectedEnv === "UAT" ? "selected" : ""}>UAT</option>
                    <option value="PROD-1" ${selectedEnv === "PROD-1" ? "selected" : ""}>PROD-1</option>
                </select>
            </div>
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
                    ${items.length === 0 ? `<tr><td colspan="4" style="text-align:center; padding: 20px;">No hay registros para este ambiente</td></tr>` : ""}
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

function renderLegacyCleanup(bundles) {
  const items = bundles.filter((b) => b.flow === "LEGACY");

  return `
        <div class="view-header">
            <h2>LEGACY FLOW | Versionamiento de Proyectos</h2>
            <button class="btn-subnav" onclick="AppState.switchSection('HISTORIC')">Consultar histórico</button>
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
                    ${items.length === 0 ? `<tr><td colspan="3" style="text-align:center; padding: 20px;">No hay registros en Legacy Flow</td></tr>` : ""}
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

function renderLegacyHistoric(bundles) {
  const items = bundles.filter((b) => b.flow === "LEGACY");

  return `
        <div class="view-header">
            <h2>LEGACY FLOW | Histórico de Proyectos</h2>
            <button class="btn-subnav" onclick="AppState.switchSection('CLEANUP')">Consultar versionamiento</button>
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
                    ${items.length === 0 ? `<tr><td colspan="3" style="text-align:center; padding: 20px;">No hay registros históricos</td></tr>` : ""}
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

function renderProjectGroups(items) {
  if (!items || items.length === 0) {
    return `<p style="text-align:center; color: #64748b; padding: 20px;">Sin versionamientos detectados</p>`;
  }

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

// ==========================================
// ACCIONES Y EVENTOS
// ==========================================

window.triggerAuthorize = async function () {
  if (!confirm("¿Está seguro de autorizar la eliminación en S3?")) return;

  try {
    const url = getWebAppBackendUrl("/authorize-cleanup");
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bundles: window.AppState.scanBundles }),
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

      alert("Limpieza ejecutada con éxito");
      window.AppState.historicBundles = []; // Limpiar caché histórico para recargarlo cuando consulte
      window.AppState.init();
    }
  } catch (error) {
    alert("Error al procesar la autorización");
  }
};

window.triggerGlobalReport = function () {
  const url = getWebAppBackendUrl("/global-report");
  window.open(url, "_blank");
};

document.addEventListener("DOMContentLoaded", () => {
  window.AppState.init();

  const flowDropdown = document.getElementById("select-flow-dropdown");
  if (flowDropdown) {
    flowDropdown.addEventListener("change", (e) => {
      window.AppState.currentFlow = e.target.value;
      window.AppState.switchSection("CLEANUP");
    });
  }
});
