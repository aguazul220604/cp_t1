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

  // Botón Registrar Instancia
  const btnRegistrar = document.getElementById("btn-registrar");
  if (btnRegistrar) {
    btnRegistrar.addEventListener("click", guardarInstancia);
  }

  // Modal Edición
  const btnCancelar = document.getElementById("btn-cancelar-edicion");
  if (btnCancelar) {
    btnCancelar.addEventListener("click", () => {
      document.getElementById("modal-editar").classList.add("hidden");
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
          <button class="btn btn-action btn-edit" onclick="abrirModalEditar('${escapeHtml(item.id)}')">Editar</button>
          <button class="btn btn-action btn-delete" onclick="eliminarInstancia('${escapeHtml(item.id)}')">Eliminar</button>
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
        instancia.proyectos.forEach((proyecto) => {
          const clave = `${instancia.id_instancia}-${proyecto.id_proyecto}`;
          estadoProyectos.push({
            id_instancia: instancia.id_instancia,
            nombre_instancia: instancia.nombre_instancia,
            id_proyecto: proyecto.id_proyecto,
            nombre_proyecto: proyecto.nombre_proyecto,
            preservado: preservadosPrevios.has(clave),
          });
        });
      });

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
    btn.textContent = proyecto.nombre_proyecto;
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
      <button class="btn btn-action btn-revertir" onclick="revertirProyecto('${escapeHtml(p.id_instancia)}', '${escapeHtml(p.id_proyecto)}')">
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
      document
        .getElementById("contenedor-grafica-backend")
        .classList.remove("hidden");
      document.getElementById("img-grafica-analisis").src =
        "data:image/png;base64," + data.grafica_b64;

      const m = data.metricas;
      document.getElementById("metric-jobs").textContent = m.jobs_ejecutados;
      document.getElementById("metric-last-mod").textContent =
        m.ultima_modificacion;
      document.getElementById("metric-users").textContent = m.propietario;
      document.getElementById("metric-commits").textContent = m.commits;
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
