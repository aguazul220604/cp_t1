// Estado global (instancia actual únicamente)
let estadoProyectos = [];
let proyectoSeleccionadoActual = null;

// Profundidad de limpieza global (memoria única).
// 4 = base (solo >=4m, oscuro) .. 1 = profunda (todo >=1m).
const PROFUNDIDAD_DEFECTO = 4;
let profundidadActual = PROFUNDIDAD_DEFECTO;

function getProfundidad() {
  return [1, 2, 3, 4].includes(profundidadActual)
    ? profundidadActual
    : PROFUNDIDAD_DEFECTO;
}

function nivelesActivos(profundidad) {
  const d = parseInt(profundidad, 10);
  if (![1, 2, 3, 4].includes(d)) return [4];
  return [4, 3, 2, 1].filter((u) => u >= d);
}

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
  cargarProyectosInactivos();
  registrarEventos();
});

// ==========================================
// REGISTRO DE EVENTOS
// ==========================================
function registrarEventos() {
  // Delegación: lista de preservados (Revertir)
  const listaPreservados = document.getElementById("lista-preservados");
  if (listaPreservados && !listaPreservados.dataset.delegacionActiva) {
    listaPreservados.dataset.delegacionActiva = "1";
    listaPreservados.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-accion='revertir']");
      if (!btn) return;
      revertirProyecto(btn.getAttribute("data-id-proyecto"));
    });
  }

  // Select Profundidad de limpieza: el backend ya filtra solo Eliminar,
  // por lo que cambiarla requiere reconsultar (refetch).
  const selectUmbral = document.getElementById("select-umbral-tiempo");
  if (selectUmbral) {
    selectUmbral.addEventListener("change", (e) => {
      const nueva = parseInt(e.target.value, 10);
      profundidadActual = [1, 2, 3, 4].includes(nueva)
        ? nueva
        : PROFUNDIDAD_DEFECTO;

      cargarProyectosInactivos();
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

const COLORES_UMBRAL = {
  4: "#d90429",
  3: "#f45d01",
  2: "#f48c06",
  1: "#e9b308",
};

function normalizarCortes(corteIdx, umbralOuCortes, profundidad) {
  // Acepta: array [{umbral, idx}], número legacy, o nada (deriva de profundidad).
  if (Array.isArray(umbralOuCortes) && umbralOuCortes.length > 0) {
    return umbralOuCortes
      .filter((c) => c && c.idx !== null && c.idx !== undefined)
      .map((c) => ({
        umbral: parseInt(c.umbral, 10) || 4,
        idx: parseInt(c.idx, 10),
      }))
      .filter((c) => !Number.isNaN(c.idx));
  }
  if (Array.isArray(corteIdx) && corteIdx.length > 0) {
    return normalizarCortes(null, corteIdx, profundidad);
  }
  if (typeof corteIdx === "number" && typeof umbralOuCortes === "number") {
    return [{ umbral: umbralOuCortes, idx: corteIdx }];
  }
  if (typeof corteIdx === "number") {
    return [{ umbral: 4, idx: corteIdx }];
  }
  const d = [1, 2, 3, 4].includes(parseInt(profundidad, 10))
    ? parseInt(profundidad, 10)
    : PROFUNDIDAD_DEFECTO;
  return nivelesActivos(d).map((u) => ({ umbral: u, idx: 11 - u }));
}

function construirSvgActividad(
  meses,
  valores,
  corteIdx,
  umbralOuCortes,
  profundidad,
) {
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

  const cortes = normalizarCortes(corteIdx, umbralOuCortes, profundidad).filter(
    (c) => c.idx >= 0 && c.idx < n,
  );
  // Dibujar primero los más profundos para que la base (>=4) quede al frente.
  const ordenados = [...cortes].sort((a, b) => a.umbral - b.umbral);
  const lineasCorte = ordenados
    .map((c) => {
      const x = posX(c.idx);
      const color = COLORES_UMBRAL[c.umbral] || "#ff3b3b";
      const esBase = c.umbral === 4;
      return `<line x1="${x}" y1="${margenSup}" x2="${x}" y2="${alto - margenInf}" stroke="${color}" stroke-width="${esBase ? 2 : 1.5}" stroke-dasharray="4,3"></line>
       <text x="${x}" y="${margenSup - 4}" font-size="8" fill="${color}" text-anchor="middle">Umbral ${c.umbral}M</text>`;
    })
    .join("");

  return `
    <svg class="grafica-actividad-svg" viewBox="0 0 ${ancho} ${alto}" xmlns="http://www.w3.org/2000/svg">
      <line x1="${margenIzq}" y1="${margenSup}" x2="${margenIzq}" y2="${alto - margenInf}" stroke="#ddd" stroke-width="1"></line>
      <line x1="${margenIzq}" y1="${alto - margenInf}" x2="${ancho - margenDer}" y2="${alto - margenInf}" stroke="#ddd" stroke-width="1"></line>
      ${lineasCorte}
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

function renderizarGraficasProyecto(actividad, estructura, profundidad) {
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

  const prof =
    datosActividad.umbral_meses || profundidad || PROFUNDIDAD_DEFECTO;
  const cortesEntrada = datosActividad.cortes
    ? datosActividad.cortes
    : datosActividad.corte_umbral !== undefined &&
        datosActividad.corte_umbral !== null
      ? [
          {
            umbral: prof,
            idx: datosActividad.corte_umbral,
          },
        ]
      : datosActividad.corte_4_meses;

  contenedor.innerHTML = `
    <div class="grafica-panel">
      <h4>Nivel de Actividad (Histórico)</h4>
      ${construirSvgActividad(datosActividad.meses, datosActividad.valores, cortesEntrada, null, prof)}
    </div>
    <div class="grafica-panel">
      <h4>Estructura del Proyecto</h4>
      ${construirHtmlEstructura(datosEstructura.datasets, datosEstructura.recetas, datosEstructura.escenarios)}
    </div>
  `;

  contenedor.classList.remove("hidden");
}

// ==========================================
// ANÁLISIS Y PROYECTOS INACTIVOS (instancia actual)
// ==========================================
async function cargarProyectosInactivos() {
  const listContainer = document.getElementById("sidebar-projects-list");
  if (!listContainer) return;
  listContainer.innerHTML =
    '<p class="text-center">Analizando actividad de proyectos...</p>';

  // Recordar qué proyectos ya estaban preservados antes de refrescar,
  // para no perder ese estado al volver a consultar el backend.
  const preservadosPrevios = new Set(
    estadoProyectos.filter((p) => p.preservado).map((p) => `${p.id_proyecto}`),
  );

  try {
    // El backend ya devuelve SOLO proyectos con Decision == Eliminar
    // (filtro exacto con jobs+timeline) para la profundidad elegida.
    const response = await fetch(
      getWebAppBackendUrl(
        `/obtener-proyectos-inactivos?umbral=${getProfundidad()}`,
      ),
    );
    const data = await response.json();

    if (data.status === "ok") {
      estadoProyectos = [];
      (data.datos || []).forEach((proyecto) => {
        const clave = `${proyecto.id_proyecto}`;
        estadoProyectos.push({
          id_proyecto: proyecto.id_proyecto,
          nombre_proyecto: proyecto.nombre_proyecto,
          ultima_modificacion: proyecto.ultima_modificacion || "-",
          ultima_ejecucion: proyecto.ultima_ejecucion || "-",
          bucket:
            proyecto.bucket !== undefined && proyecto.bucket !== null
              ? proyecto.bucket
              : 4,
          preservado: preservadosPrevios.has(clave),
        });
      });

      proyectoSeleccionadoActual = null;
      resetearDashboardCentral();
      renderizarPanelIzquierdo();
      renderizarPanelPreservados();
    } else {
      listContainer.innerHTML = `<p class="text-center text-red">Error: ${escapeHtml(data.message)}</p>`;
    }
  } catch (err) {
    console.error("Error al obtener proyectos:", err);
    listContainer.innerHTML = '<p class="text-center">Error de conexión.</p>';
  }
}

function renderizarPanelIzquierdo() {
  const listContainer = document.getElementById("sidebar-projects-list");
  if (!listContainer) return;
  listContainer.innerHTML = "";

  // Todo lo listado ya es candidato a eliminación; solo se excluyen
  // los preservados explícitamente.
  const activos = estadoProyectos.filter((p) => !p.preservado);

  if (activos.length === 0) {
    listContainer.innerHTML =
      '<p class="text-center">No hay proyectos pendientes.</p>';
    return;
  }

  activos.forEach((proyecto) => {
    const esActivo =
      proyectoSeleccionadoActual &&
      proyectoSeleccionadoActual.id_proyecto == proyecto.id_proyecto
        ? "active"
        : "";

    const bucket = proyecto.bucket ?? 4;
    const btn = document.createElement("button");
    btn.className = `btn-project umbral-${bucket} ${esActivo}`;
    btn.textContent = proyecto.nombre_proyecto;
    btn.title = `Mod: ${proyecto.ultima_modificacion || "-"} | Ejec: ${proyecto.ultima_ejecucion || "-"}`;
    btn.onclick = () => {
      document
        .querySelectorAll(".btn-project")
        .forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      consultarMetricasProyecto(proyecto.id_proyecto, proyecto.nombre_proyecto);
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
        <strong>${escapeHtml(p.nombre_proyecto)}</strong>
      </div>
      <button class="btn btn-action btn-revertir" data-accion="revertir" data-id-proyecto="${escapeHtml(p.id_proyecto)}">
        Revertir
      </button>
    `;
    contenedor.appendChild(div);
  });
}

function resetearDashboardCentral() {
  document.getElementById("subtitulo-instancia-actual").textContent =
    "Instancia actual";
  document.getElementById("titulo-proyecto-seleccionado").textContent =
    "Seleccione un proyecto";
  document.getElementById("contenedor-grafica-backend").classList.add("hidden");

  const msgGrafica = document.getElementById("mensaje-grafica-vacia");
  msgGrafica.classList.remove("hidden");
  msgGrafica.textContent = "Esperando selección...";

  document.getElementById("metric-last-mod").textContent = "-";
  document.getElementById("metric-last-exec").textContent = "-";
  document.getElementById("btn-preservar-centro").classList.add("hidden");
}

async function consultarMetricasProyecto(idProyecto, nombreProyecto) {
  proyectoSeleccionadoActual = {
    id_proyecto: idProyecto,
    nombre_proyecto: nombreProyecto,
  };

  document.getElementById("subtitulo-instancia-actual").textContent =
    "Instancia actual";
  document.getElementById("titulo-proyecto-seleccionado").textContent =
    nombreProyecto;
  document.getElementById("btn-preservar-centro").classList.remove("hidden");

  document.getElementById("contenedor-grafica-backend").classList.add("hidden");
  const msgGrafica = document.getElementById("mensaje-grafica-vacia");
  msgGrafica.classList.remove("hidden");
  msgGrafica.textContent = "Calculando métricas...";

  document.getElementById("metric-last-mod").textContent = "...";
  document.getElementById("metric-last-exec").textContent = "...";

  try {
    const profundidad = getProfundidad();
    const response = await fetch(getWebAppBackendUrl("/analizar-proyecto"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proyecto_id: idProyecto,
        umbral_meses: profundidad,
      }),
    });
    const data = await response.json();

    if (data.status === "ok") {
      // Si el análisis refinado resulta Preservar (actividad nueva entre
      // listado y análisis), retirar del listado sin mostrar meses/decisión.
      if (data.metricas?.decision === "Preservar") {
        estadoProyectos = estadoProyectos.filter(
          (p) => String(p.id_proyecto) !== String(idProyecto),
        );
        proyectoSeleccionadoActual = null;
        renderizarPanelIzquierdo();
        renderizarPanelPreservados();
        resetearDashboardCentral();
        msgGrafica.classList.remove("hidden");
        msgGrafica.textContent =
          "El proyecto mostró actividad reciente y ya no es candidato.";
        return;
      }

      msgGrafica.classList.add("hidden");
      renderizarGraficasProyecto(
        data.actividad,
        data.estructura,
        data.metricas?.umbral_meses ?? profundidad,
      );

      const m = data.metricas;
      document.getElementById("metric-last-mod").textContent =
        m.ultima_modificacion ?? "-";
      document.getElementById("metric-last-exec").textContent =
        m.ultima_ejecucion ?? "-";
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
      String(p.id_proyecto) === String(proyectoSeleccionadoActual.id_proyecto),
  );
  if (!proyecto) return;

  proyecto.preservado = true;
  proyectoSeleccionadoActual = null;

  renderizarPanelIzquierdo();
  renderizarPanelPreservados();
  resetearDashboardCentral();
}

function revertirProyecto(idProyecto) {
  const proyecto = estadoProyectos.find(
    (p) => String(p.id_proyecto) === String(idProyecto),
  );
  if (!proyecto) return;

  proyecto.preservado = false;

  renderizarPanelIzquierdo();
  renderizarPanelPreservados();
}

async function ejecutarLimpiezaCompleta() {
  // Todo lo listado ya es Eliminar; solo se excluyen preservados.
  const pendientes = estadoProyectos.filter((p) => !p.preservado);
  const proyectosALimpiar = pendientes.map((p) => ({
    proyecto_id: p.id_proyecto,
  }));

  if (proyectosALimpiar.length === 0) {
    alert("No hay proyectos pendientes por limpiar");
    return;
  }

  const confirmacion = confirm(
    `Está a punto de eliminar ${proyectosALimpiar.length} proyecto(s) de la instancia actual de forma permanente.\n` +
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

      renderizarPanelIzquierdo();
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

// Exponer en window para depuración desde consola en la WebApp Dataiku.
window.revertirProyecto = revertirProyecto;
window.preservarProyectoActual = preservarProyectoActual;
