// ==========================================
// APP STATE (Métricas Globales S3)
// ==========================================
window.AppState = {
  periodoEjecucion: "Sep 2026",
  criterioAntiguedad: "> 6 meses",

  // Arreglos de estado
  scanBundles: [], // S3 activo -> ORIGEN DE VERDAD PARA MÉTRICAS
  historicBundles: [], // Dataset 'historical' -> SOLO PARA LA TABLA HISTÓRICO

  currentFlow: "NEW",
  currentSection: "CLEANUP", // "CLEANUP" o "HISTORIC"
  currentEnv: "UAT",

  isLoading: false,

  async init() {
    this.renderCurrentView();
    await this.fetchScanBundles();
  },

  getBundleSize(b) {
    const v = b.size ?? b.size_mb;
    return parseFloat(v) || 0;
  },

  // Unión deduplicada por s3_path (scan + histórico) para métricas y authorize.
  getUnionBundles() {
    const map = new Map();
    for (const b of this.scanBundles || []) {
      if (b && b.s3_path) map.set(b.s3_path, b);
    }
    for (const b of this.historicBundles || []) {
      if (b && b.s3_path && !map.has(b.s3_path)) map.set(b.s3_path, b);
    }
    return [...map.values()];
  },

  async fetchScanBundles() {
    this.isLoading = true;
    this.renderCurrentView();

    try {
      const url = getWebAppBackendUrl("/scan-bundles");
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();

      if (data.status === "success") {
        this.scanBundles = data.bundles || [];
        this.periodoEjecucion = data.periodo_ejecucion || this.periodoEjecucion;
        this.criterioAntiguedad =
          data.criterio_antiguedad || this.criterioAntiguedad;
      } else {
        alert(
          "Error al obtener versionamiento: respuesta inválida del backend",
        );
      }
    } catch (error) {
      console.error("Error al obtener /scan-bundles:", error);
      alert(
        "No se pudo cargar el versionamiento (S3). Revise la conexión e intente de nuevo.",
      );
    } finally {
      this.isLoading = false;
      this.renderMetrics();
      this.renderCurrentView();
    }
  },

  async fetchHistoricBundles() {
    this.isLoading = true;
    this.renderCurrentView();

    try {
      const url = getWebAppBackendUrl("/get-historical");
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();

      if (data.status === "success") {
        this.historicBundles = data.bundles || [];
      } else {
        alert("Error al obtener histórico: respuesta inválida del backend");
      }
    } catch (error) {
      console.error("Error al obtener /get-historical:", error);
      alert(
        "No se pudo cargar el histórico. Revise la conexión e intente de nuevo.",
      );
    } finally {
      this.isLoading = false;
      this.renderMetrics(); // Re-renderiza las métricas globales para asegurar coherencia
      this.renderCurrentView();
    }
  },

  async switchSection(section) {
    this.currentSection = section;

    if (section === "HISTORIC" && this.historicBundles.length === 0) {
      await this.fetchHistoricBundles();
    } else {
      this.renderMetrics();
      this.renderCurrentView();
    }
  },

  get activeBundles() {
    return this.currentSection === "CLEANUP"
      ? this.scanBundles
      : this.historicBundles;
  },

  // MÉTRICAS SIEMPRE GLOBALES (unión S3 + histórico, dedup por s3_path)
  getMetrics() {
    const all = this.getUnionBundles();

    const totalMB = all.reduce((acc, b) => acc + this.getBundleSize(b), 0);

    const espacioALiberar = all
      .filter((b) => b.estado === "Descartado")
      .reduce((acc, b) => acc + this.getBundleSize(b), 0);

    const espacioResultante = Math.max(0, totalMB - espacioALiberar);

    return {
      total: Number(totalMB).toFixed(2),
      aLiberar: Number(espacioALiberar).toFixed(2),
      resultante: Number(espacioResultante).toFixed(2),
    };
  },

  // CAMBIO DE ESTATUS: actualiza cada listado en su propio array (sin
  // inyectar copias cruzadas). S3 es case-sensitive: no usar toLowerCase().
  toggleStatus(s3_path) {
    if (!s3_path) return;

    const normalizePath = (path) => (path || "").trim().replace(/\/+$/, "");
    const targetPath = normalizePath(s3_path);

    const scanItem = (this.scanBundles || []).find(
      (b) => normalizePath(b.s3_path) === targetPath,
    );
    const historicItem = (this.historicBundles || []).find(
      (b) => normalizePath(b.s3_path) === targetPath,
    );

    // Determinar el nuevo estado
    const currentStatus = (scanItem || historicItem)?.estado || "Conservado";
    const newStatus =
      currentStatus === "Conservado" ? "Descartado" : "Conservado";

    if (scanItem) scanItem.estado = newStatus;
    if (historicItem) historicItem.estado = newStatus;

    // 5. Recalcular métricas globales y refrescar la interfaz
    this.renderMetrics();
    this.renderCurrentView();
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

// Escape HTML para evitar XSS al interpolar datos de S3 en innerHTML.
function escHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Escape para atributo data-s3-path (comillas + HTML).
function escAttr(value) {
  return escHtml(value).replace(/'/g, "&#39;");
}

function statusBtnHtml(b) {
  const estado = b.estado || "Conservado";
  const cls = estado.toLowerCase();
  const icon = estado === "Descartado" ? "✖" : "✔";
  return `
    <button class="status-toggle-btn ${cls}" data-s3-path="${escAttr(b.s3_path)}">
        <span class="icon">${icon}</span>
        <span>${escHtml(estado)}</span>
    </button>`;
}

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
  // Normalizamos a mayúsculas y eliminamos espacios para evitar inconsistencias
  const targetEnv = (selectedEnv || "").trim().toUpperCase();

  const items = bundles.filter((b) => {
    const bundleFlow = (b.flow || "").trim().toUpperCase();
    const bundleEnv = (b.env || "").trim().toUpperCase();

    return bundleFlow === "NEW" && bundleEnv === targetEnv;
  });

  return `
        <div class="view-header">
            <h2>NEW FLOW | Histórico de Proyectos por Ambiente</h2>
            <div class="controls-group">
                <button class="btn-subnav" onclick="AppState.switchSection('CLEANUP')">Consultar versionamiento</button>
                <select class="dropdown-select" onchange="AppState.currentEnv=this.value; AppState.renderCurrentView();">
                    <option value="UAT" ${targetEnv === "UAT" ? "selected" : ""}>UAT</option>
                    <option value="PROD-1" ${targetEnv === "PROD-1" ? "selected" : ""}>PROD-1</option>
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
                            <td>${escHtml(b.nickname || "N/A")}</td>
                            <td>${escHtml(b.proyecto)}</td>
                            <td>${escHtml(b.filename || b.s3_path)}</td>
                            <td>${statusBtnHtml(b)}</td>
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
                            <td>${escHtml(b.proyecto)}</td>
                            <td title="${escAttr(b.s3_path)}">${escHtml(b.filename || b.s3_path)}</td>
                            <td>${statusBtnHtml(b)}</td>
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
                            <td>${escHtml(b.proyecto)}</td>
                            <td title="${escAttr(b.s3_path)}">${escHtml(b.filename || b.s3_path)}</td>
                            <td>${statusBtnHtml(b)}</td>
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

  // Vista 1 §5: agrupar por Servidor/Nickname; mismo proyecto bajo
  // distintos nicknames = tarjetas independientes.
  const grouped = {};
  items.forEach((item) => {
    const key = `${item.nickname || "N/A"}|||${item.proyecto}`;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(item);
  });

  return Object.keys(grouped)
    .sort()
    .map((key) => {
      const [nickname, proj] = key.split("|||");
      return `
        <div class="project-box">
            <span class="server-tag">${escHtml(nickname)} · ${escHtml(proj)}</span>
            <div class="versions-list">
                ${grouped[key]
                  .map(
                    (b) => `
                    <div class="version-row">
                        <span class="version-name" title="${escAttr(b.s3_path)}">${escHtml(b.proyecto)}/${escHtml(b.filename)}</span>
                        ${statusBtnHtml(b)}
                    </div>
                `,
                  )
                  .join("")}
            </div>
        </div>
    `;
    })
    .join("");
}

// ==========================================
// ACCIONES Y EVENTOS
// ==========================================

window.triggerAuthorize = async function () {
  if (!confirm("¿Está seguro de autorizar la eliminación en S3?")) return;

  try {
    const url = getWebAppBackendUrl("/authorize-cleanup");
    // Enviar unión dedup scan + histórico para no perder registros (§6.2 incremental).
    const payload = window.AppState.getUnionBundles();
    if (payload.length === 0) {
      alert("No hay bundles para autorizar");
      return;
    }
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bundles: payload }),
    });

    if (!response.ok) {
      let msg = `HTTP ${response.status}`;
      try {
        const err = await response.json();
        if (err && err.message) msg = err.message;
      } catch (_) {}
      alert(`Error al procesar la autorización: ${msg}`);
      return;
    }
    const blob = await response.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `Reporte_Limpieza_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();

    alert(
      "Limpieza ejecutada con éxito (revise la columna Estado del CSV para errores por item)",
    );
    window.AppState.historicBundles = []; // Limpiar caché histórico para recargarlo cuando consulte
    await window.AppState.fetchScanBundles();
  } catch (error) {
    console.error("Error en authorize:", error);
    alert("Error al procesar la autorización");
  }
};

window.triggerGlobalReport = async function () {
  try {
    const url = getWebAppBackendUrl("/global-report");
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    window.open(downloadUrl, "_blank");
  } catch (error) {
    console.error("Error en global-report:", error);
    alert("No se pudo generar el reporte global");
  }
};

// Delegación global: un solo listener para todos los botones de estado
// (evita onclick inline con rutas S3 sin escapar).
document.addEventListener("click", (e) => {
  const btn =
    e.target && e.target.closest
      ? e.target.closest(".status-toggle-btn")
      : null;
  if (btn && btn.dataset && btn.dataset.s3Path) {
    window.AppState.toggleStatus(btn.dataset.s3Path);
  }
});

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
