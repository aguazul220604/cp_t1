// Estado global
let listaInstancias = [];
let estadoProyectos = [];
let proyectoSeleccionadoActual = null;

// ==========================================
// UTILIDADES
// ==========================================
function escapeHtml(valor) {
  if (valor === null || valor === undefined) return "";
  return String(valor)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// ==========================================
// INICIALIZACIÓN
// ==========================================
document.addEventListener("DOMContentLoaded", () => {
  cargarInstancias();
  cargarProyectosInactivos();
  registrarEventos();
});

// ==========================================
// REGISTRO DE EVENTOS
// ==========================================
function registrarEventos() {
  // Menú (Header)
  const btnMenu = document.getElementById("btn-menu-principal");
  const dropdownContent = document.getElementById("dropdown-content");

  if (btnMenu && dropdownContent) {
    btnMenu.addEventListener("click", (e) => {
      e.stopPropagation();
      dropdownContent.classList.toggle("hidden");
    });

    document.addEventListener("click", () => {
      dropdownContent.classList.add("hidden");
    });
  }

  // Navegación SPA
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const targetView = link.getAttribute("data-target");
      const textoOpcion = link.textContent.trim();

      if (btnMenu) btnMenu.textContent = textoOpcion;

      document
        .querySelectorAll(".nav-link")
        .forEach((l) => l.classList.remove("active"));
      link.classList.add("active");

      document
        .querySelectorAll(".view-section")
        .forEach((view) => view.classList.add("hidden"));
      const targetElement = document.getElementById(targetView);
      if (targetElement) targetElement.classList.remove("hidden");

      if (targetView === "view-analisis") {
        cargarProyectosInactivos();
      } else if (targetView === "view-registro") {
        cargarInstancias();
      }
    });
  });

  // Botón Registrar Instancia + submit con Enter
  const btnRegistrar = document.getElementById("btn-registrar");
  if (btnRegistrar) {
    btnRegistrar.addEventListener("click", guardarInstancia);
  }
  const formRegistro = document.getElementById("form-registro");
  if (formRegistro) {
    formRegistro.addEventListener("submit", (e) => {
      e.preventDefault();
      guardarInstancia();
    });
  }

  // Delegación: tabla de instancias (Editar / Eliminar)
  const tbody = document.getElementById("tabla-instancias-body");
  if (tbody && !tbody.dataset.delegacionActiva) {
    tbody.dataset.delegacionActiva = "1";
    tbody.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-accion]");
      if (!btn) return;
      const id = btn.getAttribute("data-id");
      if (btn.getAttribute("data-accion") === "editar") abrirModalEditar(id);
      else if (btn.getAttribute("data-accion") === "eliminar")
        eliminarInstancia(id);
    });
  }

  // Delegación: lista de preservados (Revertir)
  const listaPreservados = document.getElementById("lista-preservados");
  if (listaPreservados && !listaPreservados.dataset.delegacionActiva) {
    listaPreservados.dataset.delegacionActiva = "1";
    listaPreservados.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-accion='revertir']");
      if (!btn) return;
      revertirProyecto(
        btn.getAttribute("data-id-instancia"),
        btn.getAttribute("data-id-proyecto"),
      );
    });
  }

  // Modal Edición
  const btnCancelar = document.getElementById("btn-cancelar-edicion");
  if (btnCancelar) {
    btnCancelar.addEventListener("click", () => {
      document.getElementById("modal-editar").classList.add("hidden");
    });
  }

  const modalEditar = document.getElementById("modal-editar");
  if (modalEditar && !modalEditar.dataset.cierreActivo) {
    modalEditar.dataset.cierreActivo = "1";
    modalEditar.addEventListener("click", (e) => {
      if (e.target === modalEditar) modalEditar.classList.add("hidden");
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") modalEditar.classList.add("hidden");
    });
  }

  const btnGuardarEdicion = document.getElementById("btn-guardar-edicion");
  if (btnGuardarEdicion) {
    btnGuardarEdicion.addEventListener("click", guardarEdicionInstancia);
  }

  // Filtro Select Instancias
  const selectFiltro = document.getElementById("select-instancia-filtro");
  if (selectFiltro) {
    selectFiltro.addEventListener("change", (e) => {
      renderizarPanelIzquierdo(e.target.value);
    });
  }

  // Botón Preservar Centro
  const btnPreservar = document.getElementById("btn-preservar-centro");
  if (btnPreservar) {
    btnPreservar.addEventListener("click", preservarProyectoActual);
  }

  // Botón Autorizar Limpieza
  const btnAutorizar = document.getElementById("btn-autorizar-cambios");
  if (btnAutorizar) {
    btnAutorizar.addEventListener("click", ejecutarLimpiezaCompleta);
  }
}

// ==========================================
// OBTENER Y POBLAR INSTANCIAS
// ==========================================
async function cargarInstancias() {
  try {
    const url = getWebAppBackendUrl("/obtener-instancias");
    const response = await fetch(url);
    const data = await response.json();

    if (data.status === "ok") {
      listaInstancias = data.instancias || [];
      renderizarTabla(listaInstancias);
      poblarSelectInstancias(listaInstancias);
    } else {
      alert("Error al cargar instancias: " + data.message);
    }
  } catch (err) {
    console.error("Error en GET /obtener-instancias:", err);
  }
}

function poblarSelectInstancias(instancias) {
  const select = document.getElementById("select-instancia-filtro");
  if (!select) return;

  select.innerHTML = '<option value="">Seleccionar instancia</option>';
  instancias.forEach((instancia) => {
    const option = document.createElement("option");
    option.value = instancia.id;
    option.textContent = instancia.nombre;
    select.appendChild(option);
  });
}

// ==========================================
// GESTIÓN DE INSTANCIAS
// ==========================================
async function guardarInstancia() {
  const nombre = document.getElementById("nombre-instancia").value.trim();
  const urlInstancia = document.getElementById("url-instancia").value.trim();
  const apiKey = document.getElementById("api-key").value.trim();

  if (!nombre || !urlInstancia || !apiKey) {
    alert("Usted no ha completado todos los campos del formulario");
    return;
  }

  const btn = document.getElementById("btn-registrar");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Registrando...";
  }
  try {
    const response = await fetch(getWebAppBackendUrl("/registrar-instancia"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, url: urlInstancia, api_key: apiKey }),
    });
    const data = await response.json();

    if (data.status === "ok") {
      alert("Su instancia se ha registrado con éxito");
      limpiarFormulario();
      cargarInstancias();
    } else {
      alert("Error al registrar: " + data.message);
    }
  } catch (err) {
    console.error("Error al registrar instancia:", err);
    alert("Ocurrió un error de conexión al registrar la instancia.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Registrar";
    }
  }
}

function abrirModalEditar(id) {
  const instancia = listaInstancias.find(
    (item) => String(item.id) === String(id),
  );
  if (!instancia) return;

  document.getElementById("edit-id").value = instancia.id;
  document.getElementById("edit-nombre").value = instancia.nombre;
  document.getElementById("edit-url").value = instancia.url;
  document.getElementById("edit-api-key").value = instancia.api_key;

  document.getElementById("modal-editar").classList.remove("hidden");
}

async function guardarEdicionInstancia() {
  const payload = {
    id: document.getElementById("edit-id").value,
    nombre: document.getElementById("edit-nombre").value.trim(),
    url: document.getElementById("edit-url").value.trim(),
    api_key: document.getElementById("edit-api-key").value.trim(),
  };

  if (!payload.nombre || !payload.url || !payload.api_key) {
    alert("Usted no ha completado todos los campos del formulario");
    return;
  }

  try {
    const response = await fetch(getWebAppBackendUrl("/actualizar-instancia"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();

    if (data.status === "ok") {
      alert("Su instancia se ha actualizado con éxito");
      document.getElementById("modal-editar").classList.add("hidden");
      cargarInstancias();
    } else {
      alert("Error al actualizar: " + data.message);
    }
  } catch (err) {
    console.error("Error al actualizar:", err);
  }
}

async function eliminarInstancia(id) {
  if (!confirm("¿Está seguro de que desea eliminar esta instancia?")) return;

  try {
    const response = await fetch(getWebAppBackendUrl("/eliminar-instancia"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    const data = await response.json();

    if (data.status === "ok") {
      alert("Su instancia se ha eliminado con éxito");
      cargarInstancias();
    } else {
      alert("Error al eliminar: " + data.message);
    }
  } catch (err) {
    console.error("Error al eliminar:", err);
  }
}

function renderizarTabla(instancias) {
  const tbody = document.getElementById("tabla-instancias-body");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (!instancias || instancias.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="3" class="text-center">No hay instancias registradas.</td></tr>';
    return;
  }

  instancias.forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.nombre)}</td>
      <td>${escapeHtml(item.url)}</td>
      <td class="text-center">
        <div class="action-buttons">
          <button class="btn btn-action btn-edit" data-accion="editar" data-id="${escapeHtml(item.id)}">Editar</button>
          <button class="btn btn-action btn-delete" data-accion="eliminar" data-id="${escapeHtml(item.id)}">Eliminar</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function limpiarFormulario() {
  document.getElementById("nombre-instancia").value = "";
  document.getElementById("url-instancia").value = "";
  document.getElementById("api-key").value = "";
}

// ==========================================
// GRÁFICAS NATIVAS (SVG + CSS, sin librerías)
// ==========================================
let estilosGraficasInyectados = false;

function inyectarEstilosGraficas() {
  if (estilosGraficasInyectados) return;

  const style = document.createElement("style");
  style.textContent = `
    .grafica-panel {
      background: #ffffff;
      border-radius: 10px;
      padding: 14px 16px;
      margin-bottom: 14px;
    }
    .grafica-panel:last-child {
      margin-bottom: 0;
    }
    .grafica-panel h4 {
      margin: 0 0 10px 0;
      font-size: 0.85rem;
      font-weight: 700;
      color: #333;
    }
    .grafica-actividad-svg {
      width: 100%;
      height: auto;
      display: block;
    }
    .grafica-estructura-lista {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .grafica-estructura-fila {
      display: grid;
      grid-template-columns: 90px 1fr 36px;
      align-items: center;
      gap: 8px;
      font-size: 0.8rem;
      color: #333;
    }
    .grafica-estructura-barra-fondo {
      background: #e3edf7;
      border-radius: 6px;
      height: 14px;
      overflow: hidden;
    }
    .grafica-estructura-barra-relleno {
      background: #0055ff;
      height: 100%;
      border-radius: 6px;
      transition: width 0.4s ease;
    }
  `;
  document.head.appendChild(style);
  estilosGraficasInyectados = true;
}

function construirSvgActividad(meses, valores, corteIdx) {
  const ancho = 560;
  const alto = 200;
  const margenIzq = 30;
  const margenDer = 10;
  const margenSup = 16;
  const margenInf = 30;

  const anchoUtil = ancho - margenIzq - margenDer;
  const altoUtil = alto - margenSup - margenInf;

  const n = valores.length;
  const maxValor = Math.max(1, ...valores);

  const posX = (i) => margenIzq + (n === 1 ? 0 : (i / (n - 1)) * anchoUtil);
  const posY = (v) => margenSup + altoUtil - (v / maxValor) * altoUtil;

  const puntos = valores.map((v, i) => `${posX(i)},${posY(v)}`).join(" ");

  const circulos = valores
    .map(
      (v, i) =>
        `<circle cx="${posX(i)}" cy="${posY(v)}" r="3" fill="#0044ff"></circle>`,
    )
    .join("");

  const etiquetasEje = meses
    .map((m, i) => {
      return `<text x="${posX(i)}" y="${alto - 8}" font-size="9" text-anchor="middle" fill="#666">${escapeHtml(m)}</text>`;
    })
    .join("");

  const hayCorte =
    corteIdx !== null &&
    corteIdx !== undefined &&
    corteIdx >= 0 &&
    corteIdx < n;
  const xCorte = hayCorte ? posX(corteIdx) : 0;
  const lineaCorte = hayCorte
    ? `<line x1="${xCorte}" y1="${margenSup}" x2="${xCorte}" y2="${alto - margenInf}" stroke="#ff3b3b" stroke-width="1.5" stroke-dasharray="4,3"></line>
       <text x="${xCorte}" y="${margenSup - 4}" font-size="8" fill="#ff3b3b" text-anchor="middle">Umbral 4M</text>`
    : "";

  return `
    <svg class="grafica-actividad-svg" viewBox="0 0 ${ancho} ${alto}" xmlns="http://www.w3.org/2000/svg">
      <line x1="${margenIzq}" y1="${margenSup}" x2="${margenIzq}" y2="${alto - margenInf}" stroke="#ddd" stroke-width="1"></line>
      <line x1="${margenIzq}" y1="${alto - margenInf}" x2="${ancho - margenDer}" y2="${alto - margenInf}" stroke="#ddd" stroke-width="1"></line>
      ${lineaCorte}
      <polyline points="${puntos}" fill="none" stroke="#0044ff" stroke-width="2"></polyline>
      ${circulos}
      ${etiquetasEje}
    </svg>
  `;
}

function construirHtmlEstructura(datasets, recetas, escenarios) {
  const items = [
    { label: "Datasets", valor: datasets || 0 },
    { label: "Recetas", valor: recetas || 0 },
    { label: "Escenarios", valor: escenarios || 0 },
  ];
  const maxValor = Math.max(1, ...items.map((i) => i.valor));

  const filas = items
    .map((item) => {
      const porcentaje = Math.round((item.valor / maxValor) * 100);
      return `
        <div class="grafica-estructura-fila">
          <span>${escapeHtml(item.label)}</span>
          <div class="grafica-estructura-barra-fondo">
            <div class="grafica-estructura-barra-relleno" style="width: ${porcentaje}%;"></div>
          </div>
          <span>${escapeHtml(String(item.valor))}</span>
        </div>
      `;
    })
    .join("");

  return `<div class="grafica-estructura-lista">${filas}</div>`;
}

function renderizarGraficasProyecto(actividad, estructura) {
  inyectarEstilosGraficas();

  const contenedor = document.getElementById("contenedor-grafica-backend");
  if (!contenedor) return;

  const datosActividad = actividad || {
    meses: [],
    valores: [],
    corte_4_meses: null,
  };
  const datosEstructura = estructura || {
    datasets: 0,
    recetas: 0,
    escenarios: 0,
  };

  contenedor.innerHTML = `
    <div class="grafica-panel">
      <h4>Nivel de Actividad (Histórico)</h4>
      ${construirSvgActividad(datosActividad.meses, datosActividad.valores, datosActividad.corte_4_meses)}
    </div>
    <div class="grafica-panel">
      <h4>Estructura del Proyecto</h4>
      ${construirHtmlEstructura(datosEstructura.datasets, datosEstructura.recetas, datosEstructura.escenarios)}
    </div>
  `;

  contenedor.classList.remove("hidden");
}

// ==========================================
// ANÁLISIS Y PROYECTOS INACTIVOS
// ==========================================
async function cargarProyectosInactivos() {
  const listContainer = document.getElementById("sidebar-projects-list");
  if (!listContainer) return;
  listContainer.innerHTML =
    '<p class="text-center">Consultando proyectos...</p>';

  // Recordar qué proyectos ya estaban preservados antes de refrescar,
  // para no perder ese estado al volver a consultar el backend.
  const preservadosPrevios = new Set(
    estadoProyectos
      .filter((p) => p.preservado)
      .map((p) => `${p.id_instancia}-${p.id_proyecto}`),
  );

  try {
    const response = await fetch(
      getWebAppBackendUrl("/obtener-proyectos-inactivos"),
    );
    const data = await response.json();

    if (data.status === "ok") {
      estadoProyectos = [];
      (data.datos || []).forEach((instancia) => {
        (instancia.proyectos || []).forEach((proyecto) => {
          const clave = `${instancia.id_instancia}-${proyecto.id_proyecto}`;
          estadoProyectos.push({
            id_instancia: instancia.id_instancia,
            nombre_instancia: instancia.nombre_instancia,
            id_proyecto: proyecto.id_proyecto,
            nombre_proyecto: proyecto.nombre_proyecto,
            ultima_modificacion:
              proyecto.ultima_modificacion || proyecto.ultima_actividad || "",
            months_since_last_modified:
              proyecto.months_since_last_modified ??
              proyecto.months_since_last_activity ??
              null,
            months_since_last_activity:
              proyecto.months_since_last_activity ?? null,
            decision: proyecto.decision || "Eliminar",
            preservado: preservadosPrevios.has(clave),
          });
        });
      });
      // Ordenar por inactividad descendente para priorizar limpieza.
      estadoProyectos.sort(
        (a, b) =>
          (b.months_since_last_activity ?? -1) -
          (a.months_since_last_activity ?? -1),
      );

      proyectoSeleccionadoActual = null;
      resetearDashboardCentral();
      renderizarPanelIzquierdo(
        document.getElementById("select-instancia-filtro").value,
      );
      renderizarPanelPreservados();
    } else {
      listContainer.innerHTML = `<p class="text-center text-red">Error: ${escapeHtml(data.message)}</p>`;
    }
  } catch (err) {
    console.error("Error al obtener proyectos:", err);
    listContainer.innerHTML = '<p class="text-center">Error de conexión.</p>';
  }
}

function renderizarPanelIzquierdo(idInstanciaFiltro) {
  const listContainer = document.getElementById("sidebar-projects-list");
  if (!listContainer) return;
  listContainer.innerHTML = "";

  let activos = estadoProyectos.filter((p) => !p.preservado);

  if (idInstanciaFiltro) {
    activos = activos.filter(
      (p) => String(p.id_instancia) === String(idInstanciaFiltro),
    );
  }

  if (activos.length === 0) {
    listContainer.innerHTML =
      '<p class="text-center">No hay proyectos pendientes.</p>';
    return;
  }

  activos.forEach((proyecto) => {
    const esActivo =
      proyectoSeleccionadoActual &&
      proyectoSeleccionadoActual.id_instancia == proyecto.id_instancia &&
      proyectoSeleccionadoActual.id_proyecto == proyecto.id_proyecto
        ? "active"
        : "";

    const btn = document.createElement("button");
    btn.className = `btn-project ${esActivo}`;
    const mesesTxt =
      proyecto.months_since_last_activity === null ||
      proyecto.months_since_last_activity === undefined
        ? ""
        : ` (${proyecto.months_since_last_activity}m)`;
    btn.textContent = `${proyecto.nombre_proyecto}${mesesTxt}`;
    if (
      proyecto.months_since_last_activity !== null &&
      proyecto.months_since_last_activity !== undefined
    ) {
      btn.title = `${proyecto.months_since_last_activity} meses sin actividad — ${proyecto.decision || ""}`;
    }
    btn.onclick = () => {
      document
        .querySelectorAll(".btn-project")
        .forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      consultarMetricasProyecto(
        proyecto.id_instancia,
        proyecto.id_proyecto,
        proyecto.nombre_proyecto,
        proyecto.nombre_instancia,
      );
    };

    listContainer.appendChild(btn);
  });
}

function renderizarPanelPreservados() {
  const contenedor = document.getElementById("lista-preservados");
  if (!contenedor) return;
  contenedor.innerHTML = "";

  const preservados = estadoProyectos.filter((p) => p.preservado);

  if (preservados.length === 0) {
    contenedor.innerHTML =
      '<p class="text-center">Aún no hay proyectos preservados.</p>';
    return;
  }

  preservados.forEach((p) => {
    const div = document.createElement("div");
    div.className = "preserved-item";
    div.innerHTML = `
      <div class="preserved-item-info">
        <small class="preserved-item-instancia">${escapeHtml(p.nombre_instancia)}</small>
        <strong>${escapeHtml(p.nombre_proyecto)}</strong>
      </div>
      <button class="btn btn-action btn-revertir" data-accion="revertir" data-id-instancia="${escapeHtml(p.id_instancia)}" data-id-proyecto="${escapeHtml(p.id_proyecto)}">
        Revertir
      </button>
    `;
    contenedor.appendChild(div);
  });
}

function resetearDashboardCentral() {
  document.getElementById("subtitulo-instancia-actual").textContent =
    "Instancia --";
  document.getElementById("titulo-proyecto-seleccionado").textContent =
    "Seleccione un proyecto";
  document.getElementById("contenedor-grafica-backend").classList.add("hidden");

  const msgGrafica = document.getElementById("mensaje-grafica-vacia");
  msgGrafica.classList.remove("hidden");
  msgGrafica.textContent = "Esperando selección...";

  document.getElementById("metric-jobs").textContent = "0";
  document.getElementById("metric-last-mod").textContent = "-";
  document.getElementById("metric-users").textContent = "-";
  document.getElementById("metric-commits").textContent = "0";
  const mMeses = document.getElementById("metric-meses");
  if (mMeses) mMeses.textContent = "-";
  const mDecision = document.getElementById("metric-decision");
  if (mDecision) mDecision.textContent = "-";
  document.getElementById("btn-preservar-centro").classList.add("hidden");
}

async function consultarMetricasProyecto(
  idInstancia,
  idProyecto,
  nombreProyecto,
  nombreInstancia,
) {
  proyectoSeleccionadoActual = {
    id_instancia: idInstancia,
    id_proyecto: idProyecto,
    nombre_proyecto: nombreProyecto,
  };

  document.getElementById("subtitulo-instancia-actual").textContent =
    nombreInstancia || `Instancia ${idInstancia}`;
  document.getElementById("titulo-proyecto-seleccionado").textContent =
    nombreProyecto;
  document.getElementById("btn-preservar-centro").classList.remove("hidden");

  document.getElementById("contenedor-grafica-backend").classList.add("hidden");
  const msgGrafica = document.getElementById("mensaje-grafica-vacia");
  msgGrafica.classList.remove("hidden");
  msgGrafica.textContent = "Calculando métricas...";

  document.getElementById("metric-jobs").textContent = "...";
  document.getElementById("metric-last-mod").textContent = "...";
  document.getElementById("metric-users").textContent = "...";
  document.getElementById("metric-commits").textContent = "...";
  const mMesesLoading = document.getElementById("metric-meses");
  if (mMesesLoading) mMesesLoading.textContent = "...";
  const mDecisionLoading = document.getElementById("metric-decision");
  if (mDecisionLoading) mDecisionLoading.textContent = "...";

  try {
    const response = await fetch(getWebAppBackendUrl("/analizar-proyecto"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instancia_id: idInstancia,
        proyecto_id: idProyecto,
      }),
    });
    const data = await response.json();

    if (data.status === "ok") {
      msgGrafica.classList.add("hidden");
      renderizarGraficasProyecto(data.actividad, data.estructura);

      const m = data.metricas;
      document.getElementById("metric-jobs").textContent = m.jobs_ejecutados;
      document.getElementById("metric-last-mod").textContent =
        m.ultima_modificacion;
      document.getElementById("metric-users").textContent = m.propietario;
      document.getElementById("metric-commits").textContent = m.commits;
      const elMeses = document.getElementById("metric-meses");
      if (elMeses) {
        const detalleMod =
          m.months_since_last_modified ?? m.months_since_last_activity;
        elMeses.textContent =
          `${m.months_since_last_activity ?? "-"} meses` +
          (detalleMod !== undefined &&
          detalleMod !== null &&
          detalleMod !== m.months_since_last_activity
            ? ` (mod: ${detalleMod}m)`
            : "") +
          (m.ultima_actividad ? ` · act: ${m.ultima_actividad}` : "");
      }
      const elDecision = document.getElementById("metric-decision");
      if (elDecision) {
        elDecision.textContent = `${m.decision ?? "-"} (umbral ≥${m.umbral_meses ?? 4}m)`;
      }
      // Refrescar lista izquierda con el valor refinado (jobs+timeline).
      const actual = estadoProyectos.find(
        (p) =>
          String(p.id_instancia) === String(idInstancia) &&
          String(p.id_proyecto) === String(idProyecto),
      );
      if (actual && m.months_since_last_activity !== undefined) {
        actual.months_since_last_activity = m.months_since_last_activity;
        actual.months_since_last_modified = m.months_since_last_modified;
        actual.decision = m.decision;
      }
    } else {
      msgGrafica.classList.remove("hidden");
      msgGrafica.textContent = "Error: " + data.message;
    }
  } catch (err) {
    msgGrafica.classList.remove("hidden");
    msgGrafica.textContent = "Error en la solicitud.";
  }
}

function preservarProyectoActual() {
  if (!proyectoSeleccionadoActual) return;

  const proyecto = estadoProyectos.find(
    (p) =>
      String(p.id_instancia) ===
        String(proyectoSeleccionadoActual.id_instancia) &&
      String(p.id_proyecto) === String(proyectoSeleccionadoActual.id_proyecto),
  );
  if (!proyecto) return;

  proyecto.preservado = true;
  proyectoSeleccionadoActual = null;

  renderizarPanelIzquierdo(
    document.getElementById("select-instancia-filtro").value,
  );
  renderizarPanelPreservados();
  resetearDashboardCentral();
}

function revertirProyecto(idInstancia, idProyecto) {
  const proyecto = estadoProyectos.find(
    (p) =>
      String(p.id_instancia) === String(idInstancia) &&
      String(p.id_proyecto) === String(idProyecto),
  );
  if (!proyecto) return;

  proyecto.preservado = false;

  renderizarPanelIzquierdo(
    document.getElementById("select-instancia-filtro").value,
  );
  renderizarPanelPreservados();
}

async function ejecutarLimpiezaCompleta() {
  const proyectosALimpiar = estadoProyectos
    .filter((p) => !p.preservado)
    .map((p) => ({
      instancia_id: p.id_instancia,
      proyecto_id: p.id_proyecto,
    }));

  if (proyectosALimpiar.length === 0) {
    alert("No hay proyectos pendientes por limpiar");
    return;
  }

  const confirmacion = confirm(
    `Está a punto de eliminar ${proyectosALimpiar.length} proyecto(s) de forma permanente.\n` +
      `Los proyectos preservados NO serán afectados.\n¿Desea continuar?`,
  );
  if (!confirmacion) return;

  const btnAutorizar = document.getElementById("btn-autorizar-cambios");
  btnAutorizar.disabled = true;
  btnAutorizar.textContent = "Procesando...";

  try {
    const response = await fetch(getWebAppBackendUrl("/ejecutar-limpieza"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proyectos_a_limpiar: proyectosALimpiar }),
    });
    const data = await response.json();

    btnAutorizar.disabled = false;
    btnAutorizar.textContent = "Conservar cambios y autorizar";

    if (data.status === "ok") {
      alert(
        `Limpieza finalizada.\nExitosos: ${data.exitosos}\nFallidos: ${data.fallidos}`,
      );

      const idsExitosos = (data.detalles || [])
        .filter((d) => d.status === "eliminado")
        .map((d) => String(d.proyecto_id));

      estadoProyectos = estadoProyectos.filter(
        (p) => p.preservado || !idsExitosos.includes(String(p.id_proyecto)),
      );

      renderizarPanelIzquierdo(
        document.getElementById("select-instancia-filtro").value,
      );
      renderizarPanelPreservados();
    } else {
      alert("Error al ejecutar la limpieza: " + data.message);
    }
  } catch (err) {
    btnAutorizar.disabled = false;
    btnAutorizar.textContent = "Conservar cambios y autorizar";
    console.error("Error al ejecutar limpieza:", err);
    alert("Ocurrió un error de conexión al ejecutar la limpieza.");
  }
}

// Exponer en window para compatibilidad con cualquier handler inline
// heredado y para depuración desde consola en la WebApp Dataiku.
window.abrirModalEditar = abrirModalEditar;
window.eliminarInstancia = eliminarInstancia;
window.revertirProyecto = revertirProyecto;
window.preservarProyectoActual = preservarProyectoActual;
window.guardarInstancia = guardarInstancia;
