// ==========================================
// VARIABLES GLOBALES
// ==========================================
let listaInstancias = [];
let todosLosProyectosInactivos = []; // Proyectos devueltos por el backend
let proyectosPreservados = []; // [{ instancia_id, proyecto_id, nombre_proyecto, nombre_instancia }]
let proyectoSeleccionadoActual = null;

// ==========================================
// 1. INICIALIZACIÓN
// ==========================================
$(document).ready(function () {
  cargarInstancias();
  registrarEventos();
  cargarImagenLogo();
});

// ==========================================
// 2. REGISTRO DE EVENTOS
// ==========================================
function registrarEventos() {
  // Guardar nueva instancia desde el formulario principal
  $("#btn-registrar").on("click", function () {
    guardarInstancia();
  });

  // Delegación de eventos para los botones de la tabla dinámicos
  $("#tabla-instancias-body").on("click", ".btn-edit", function () {
    const id = $(this).data("id");
    abrirModalEditar(id);
  });

  $("#tabla-instancias-body").on("click", ".btn-delete", function () {
    const id = $(this).data("id");
    eliminarInstancia(id);
  });

  // Acciones dentro del Modal de Edición
  $("#btn-cancelar-edicion").on("click", function () {
    $("#modal-editar").addClass("hidden");
  });

  $("#btn-guardar-edicion").on("click", function () {
    guardarEdicionInstancia();
  });

  // ---- Menú desplegable ----
  $("#btn-menu-principal").on("click", function (e) {
    e.stopPropagation(); // Evita que el clic se propague al documento
    $("#dropdown-content").toggleClass("hidden");
  });

  // Cerrar el menú si se hace clic fuera de él
  $(document).on("click", function () {
    $("#dropdown-content").addClass("hidden");
  });

  // ---- Navegación tipo SPA ----
  $(".nav-link").on("click", function (e) {
    e.preventDefault();
    const targetView = $(this).data("target");

    // Actualizar estilo del menú
    $(".nav-link").removeClass("active");
    $(this).addClass("active");

    // Ocultar todas las vistas y mostrar la seleccionada
    $(".view-section").addClass("hidden");
    $("#" + targetView).removeClass("hidden");

    // Si entramos a la vista de análisis, cargamos los proyectos inactivos
    if (targetView === "view-analisis") {
      cargarProyectosInactivos();
    }
  });
}

// ==========================================
// 3. OBTENER / CARGAR INSTANCIAS (GET)
// ==========================================
function cargarInstancias() {
  $.ajax({
    url: getWebAppBackendUrl("/obtener-instancias"),
    type: "GET",
    success: function (response) {
      if (response.status === "ok") {
        listaInstancias = response.instancias || [];
        renderizarTabla(listaInstancias);
      } else {
        alert("Error al cargar instancias: " + response.message);
      }
    },
    error: function (err) {
      console.error("Error en la petición GET:", err);
    },
  });
}

// ==========================================
// 4. REGISTRAR INSTANCIA (POST)
// ==========================================
function guardarInstancia() {
  const nombre = $("#nombre-instancia").val().trim();
  const url = $("#url-instancia").val().trim();
  const apiKey = $("#api-key").val().trim();

  if (!nombre || !url || !apiKey) {
    alert("Usted no ha completado todos los campos del formulario");
    return;
  }

  const payload = {
    nombre: nombre,
    url: url,
    api_key: apiKey,
  };

  $.ajax({
    url: getWebAppBackendUrl("/registrar-instancia"),
    type: "POST",
    contentType: "application/json",
    data: JSON.stringify(payload),
    success: function (response) {
      if (response.status === "ok") {
        alert("Su instancia se ha registrado con éxito");
        limpiarFormulario();
        cargarInstancias();
      } else {
        alert("Error al registrar: " + response.message);
      }
    },
    error: function (err) {
      console.error("Error en POST:", err);
    },
  });
}

// ==========================================
// 5. EDITAR INSTANCIA (MODAL & POST)
// ==========================================
function abrirModalEditar(id) {
  const instancia = listaInstancias.find((item) => item.id === id);
  if (!instancia) return;

  $("#edit-id").val(instancia.id);
  $("#edit-nombre").val(instancia.nombre);
  $("#edit-url").val(instancia.url);
  $("#edit-api-key").val(instancia.api_key);

  $("#modal-editar").removeClass("hidden");
}

function guardarEdicionInstancia() {
  const payload = {
    id: $("#edit-id").val(),
    nombre: $("#edit-nombre").val().trim(),
    url: $("#edit-url").val().trim(),
    api_key: $("#edit-api-key").val().trim(),
  };

  if (!payload.nombre || !payload.url || !payload.api_key) {
    alert("Usted no ha completado todos los campos del formulario");
    return;
  }

  $.ajax({
    url: getWebAppBackendUrl("/actualizar-instancia"),
    type: "POST",
    contentType: "application/json",
    data: JSON.stringify(payload),
    success: function (response) {
      if (response.status === "ok") {
        alert("Su instancia se ha actualizado con éxito");
        $("#modal-editar").addClass("hidden");
        cargarInstancias();
      } else {
        alert("Error al actualizar: " + response.message);
      }
    },
    error: function (err) {
      console.error("Error al actualizar:", err);
    },
  });
}

// ==========================================
// 6. ELIMINAR INSTANCIA (POST)
// ==========================================
function eliminarInstancia(id) {
  if (!confirm("¿Está seguro de que desea eliminar esta instancia?")) {
    return;
  }

  $.ajax({
    url: getWebAppBackendUrl("/eliminar-instancia"),
    type: "POST",
    contentType: "application/json",
    data: JSON.stringify({ id: id }),
    success: function (response) {
      if (response.status === "ok") {
        alert("Su instancia se ha eliminado con éxito");
        cargarInstancias();
      } else {
        alert("Error al eliminar: " + response.message);
      }
    },
    error: function (err) {
      console.error("Error al eliminar:", err);
    },
  });
}

// ==========================================
// 7. CARGAR IMAGEN DESDE MANAGED FOLDER
// ==========================================
function cargarImagenLogo() {
  $.ajax({
    url: getWebAppBackendUrl("/obtener-imagen"),
    type: "GET",
    success: function (response) {
      if (response.status === "ok") {
        $("#mi-imagen-dinamica").attr(
          "src",
          "data:image/png;base64," + response.data,
        );
      } else {
        console.warn("No se pudo cargar la imagen del logo.");
      }
    },
    error: function (err) {
      console.error("Error en la petición de la imagen:", err);
    },
  });
}

// ==========================================
// 8. RENDERIZADO DINÁMICO Y AUXILIARES
// ==========================================
function renderizarTabla(instancias) {
  const tbody = $("#tabla-instancias-body");
  tbody.empty();

  if (!instancias || instancias.length === 0) {
    tbody.append(
      '<tr><td colspan="3" class="text-center">No hay instancias registradas.</td></tr>',
    );
    return;
  }

  instancias.forEach(function (item) {
    const fila = `
      <tr>
        <td>${item.nombre}</td>
        <td>${item.url}</td>
        <td class="text-center">
          <div class="action-buttons">
            <button class="btn btn-action btn-edit" data-id="${item.id}">Editar</button>
            <button class="btn btn-action btn-delete" data-id="${item.id}">Eliminar</button>
          </div>
        </td>
      </tr>
    `;
    tbody.append(fila);
  });
}

function limpiarFormulario() {
  $("#nombre-instancia").val("");
  $("#url-instancia").val("");
  $("#api-key").val("");
}

// ==========================================
// 9. LÓGICA DE LA VISTA 2 (ANÁLISIS DE PROYECTOS Y LIMPIEZA)
// ==========================================

// 9.1 CARGAR PROYECTOS DESDE EL BACKEND
function cargarProyectosInactivos() {
  $("#sidebar-projects").html(
    '<p class="text-center text-muted">Cargando proyectos inactivos...</p>',
  );

  $.ajax({
    url: getWebAppBackendUrl("/obtener-proyectos-inactivos"),
    type: "GET",
    success: function (response) {
      if (response.status === "ok") {
        todosLosProyectosInactivos = response.datos || [];
        renderizarPaneles();
      } else {
        $("#sidebar-projects").html(
          `<p class="text-center text-danger">Error al obtener proyectos: ${response.message}</p>`,
        );
      }
    },
    error: function (err) {
      console.error("Error al obtener proyectos:", err);
      $("#sidebar-projects").html(
        '<p class="text-center text-danger">Error de conexión.</p>',
      );
    },
  });
}

// 9.2 RENDERIZAR PANEL IZQUIERDO Y DERECHO
function renderizarPaneles() {
  renderizarPanelIzquierdo();
  renderizarPanelDerecho();
}

// Panel Izquierdo: Muestra solo los proyectos que NO han sido preservados
function renderizarPanelIzquierdo() {
  const container = $("#sidebar-projects");
  container.empty();

  if (todosLosProyectosInactivos.length === 0) {
    container.html(
      '<p class="text-center text-muted">No se encontraron proyectos inactivos (>4 meses).</p>',
    );
    return;
  }

  todosLosProyectosInactivos.forEach((instancia) => {
    // Filtrar proyectos que NO estén en la lista de preservados
    const proyectosSinPreservar = instancia.proyectos.filter(
      (p) =>
        !proyectosPreservados.some(
          (pres) =>
            pres.instancia_id === instancia.id_instancia &&
            pres.proyecto_id === p.id_proyecto,
        ),
    );

    let htmlGroup = `
      <div class="instance-group mb-3 card-panel">
        <h5 class="instance-title" style="font-size:13px; font-weight:bold; color:#178096;">
          ⚙️ ${instancia.nombre_instancia} (${proyectosSinPreservar.length})
        </h5>
        <div class="list-group projects-list">
    `;

    if (proyectosSinPreservar.length === 0) {
      htmlGroup += `<p class="text-muted small ps-2">Todos los proyectos preservados</p>`;
    } else {
      proyectosSinPreservar.forEach((p) => {
        const esSeleccionado =
          proyectoSeleccionadoActual &&
          proyectoSeleccionadoActual.instancia_id === instancia.id_instancia &&
          proyectoSeleccionadoActual.proyecto_id === p.id_proyecto;

        htmlGroup += `
          <button class="list-group-item list-group-item-action project-pill btn-project ${esSeleccionado ? "active" : ""}" 
                  onclick="seleccionarProyecto(${instancia.id_instancia}, '${p.id_proyecto}', '${p.nombre_proyecto}', '${instancia.nombre_instancia}')">
            <span>${p.nombre_proyecto}</span>
            <small class="d-block text-muted" style="font-size:10px;">${p.id_proyecto}</small>
          </button>
        `;
      });
    }

    htmlGroup += `</div></div>`;
    container.append(htmlGroup);
  });
}

// 9.3 SELECCIONAR PROYECTO PARA ANALIZAR
function seleccionarProyecto(
  idInstancia,
  idProyecto,
  nombreProyecto,
  nombreInstancia,
) {
  proyectoSeleccionadoActual = {
    instancia_id: idInstancia,
    proyecto_id: idProyecto,
    nombre_proyecto: nombreProyecto,
    nombre_instancia: nombreInstancia,
  };

  renderizarPanelIzquierdo(); // Refrescar estado activo en la lista

  $("#btn-preservar-centro").removeClass("hidden"); // Mostrar botón de preservar

  consultarMétricasProyecto(idInstancia, idProyecto, nombreProyecto);
}

// 9.4 CONSULTAR MÉTRICAS DEL PROYECTO
function consultarMétricasProyecto(idInstancia, idProyecto, nombreProyecto) {
  $("#titulo-proyecto-seleccionado").text(nombreProyecto);

  // Mostrar mensaje de carga
  $("#css-charts-wrapper").addClass("hidden");
  $("#mensaje-grafica-vacia")
    .removeClass("hidden")
    .text("Calculando métricas...");

  $(
    "#metric-jobs, #metric-datasets, #metric-scenarios, #metric-last-mod, #metric-users",
  ).text("...");

  const payload = { instancia_id: idInstancia, proyecto_id: idProyecto };

  $.ajax({
    url: getWebAppBackendUrl("/analizar-proyecto"),
    type: "POST",
    contentType: "application/json",
    data: JSON.stringify(payload),
    success: function (response) {
      if (response.status === "ok") {
        $("#mensaje-grafica-vacia").addClass("hidden");
        $("#css-charts-wrapper").removeClass("hidden");

        // DIBUJAR GRÁFICAS CSS
        renderizarGraficasCSS(response.datos_graficas);

        // ACTUALIZAR MÉTRICAS DE TEXTO
        const m = response.metricas;
        $("#metric-jobs").text(m.jobs_ejecutados);
        $("#metric-datasets").text(m.total_datasets);
        $("#metric-last-mod").text(m.ultima_modificacion);
        $("#metric-users").text(m.propietario);
        $("#metric-scenarios").text(m.escenarios_ejecutados);
      } else {
        $("#mensaje-grafica-vacia")
          .removeClass("hidden")
          .text("Error: " + response.message);
      }
    },
    error: function (err) {
      $("#mensaje-grafica-vacia")
        .removeClass("hidden")
        .text("Error en la solicitud.");
    },
  });
}

// Función auxiliar para dibujar las barras
function renderizarGraficasCSS(datosGraficas) {
  // Gráfica Vertical (Tendencia)
  const vContainer = $("#chart-vertical");
  vContainer.empty();
  const vData = datosGraficas.tendencia;
  const vMax = Math.max(...vData.valores, 1); // Evitar división por cero

  vData.valores.forEach((val, i) => {
    const heightPct = (val / vMax) * 100;
    vContainer.append(`
      <div class="v-bar-container" title="Valor: ${val}">
        <div class="v-bar" style="height: ${heightPct}%"></div>
        <div class="v-label">${vData.etiquetas[i]}</div>
      </div>
    `);
  });

  // Gráfica Horizontal (Estructura)
  const hContainer = $("#chart-horizontal");
  hContainer.empty();
  const hData = datosGraficas.estructura;
  const hMax = Math.max(...hData.valores, 1);

  hData.valores.forEach((val, i) => {
    const widthPct = (val / hMax) * 80; // 80% máximo para dejar espacio al número
    hContainer.append(`
      <div class="h-bar-container">
        <div class="h-label">${hData.etiquetas[i]}</div>
        <div class="h-bar" style="width: ${widthPct}%"></div>
        <div class="h-val">${val}</div>
      </div>
    `);
  });
}

// 9.5 ACCIÓN: PRESERVAR PROYECTO (PANEL CENTRAL -> DERECHO)
function preservarProyectoActual() {
  if (!proyectoSeleccionadoActual) return;

  const yaExiste = proyectosPreservados.some(
    (p) =>
      p.instancia_id === proyectoSeleccionadoActual.instancia_id &&
      p.proyecto_id === proyectoSeleccionadoActual.proyecto_id,
  );

  if (!yaExiste) {
    proyectosPreservados.push({ ...proyectoSeleccionadoActual });
  }

  // Limpiar panel central
  $("#btn-preservar-centro").addClass("hidden");
  $("#titulo-proyecto-seleccionado").text("Selecciona un proyecto");
  $("#css-charts-wrapper").addClass("hidden");
  $("#mensaje-grafica-vacia")
    .removeClass("hidden")
    .text("Proyecto preservado exitosamente.");

  // Limpiar contadores de métricas
  $(
    "#metric-jobs, #metric-datasets, #metric-scenarios, #metric-last-mod, #metric-users",
  ).text("0");

  proyectoSeleccionadoActual = null;
  renderizarPaneles();
}

// Panel Derecho: Muestra proyectos preservados con su botón de revertir
function renderizarPanelDerecho() {
  const container = $("#lista-preservados");
  container.empty();

  if (proyectosPreservados.length === 0) {
    container.html(
      '<p class="text-center text-muted small mt-3">No hay proyectos preservados.</p>',
    );
    return;
  }

  proyectosPreservados.forEach((p, idx) => {
    container.append(`
      <div class="item-preservado-card p-2 mb-2 border rounded background-light d-flex justify-content-between align-items-center">
        <div>
          <strong style="font-size:12px; display:block;">${p.nombre_proyecto}</strong>
          <small class="text-muted" style="font-size:10px;">${p.nombre_instancia} | ${p.proyecto_id}</small>
        </div>
        <button class="btn btn-sm btn-outline-warning" onclick="revertirProyecto(${idx})" title="Regresar a lista de limpieza">
          ↩️
        </button>
      </div>
    `);
  });
}

// 9.6 ACCIÓN: REVERTIR PROYECTO (PANEL DERECHO -> IZQUIERDO)
function revertirProyecto(index) {
  proyectosPreservados.splice(index, 1);
  renderizarPaneles();
}

// 9.7 ACCIÓN: CONSERVAR CAMBIOS Y AUTORIZAR (EJECUTAR LIMPIEZA)
function ejecutarLimpiezaCompleta() {
  // Construir lista de proyectos a borrar (Todos los inactivos MENOS los preservados)
  const proyectosALimpiar = [];

  todosLosProyectosInactivos.forEach((instancia) => {
    instancia.proyectos.forEach((p) => {
      const estaPreservado = proyectosPreservados.some(
        (pres) =>
          pres.instancia_id === instancia.id_instancia &&
          pres.proyecto_id === p.id_proyecto,
      );

      if (!estaPreservado) {
        proyectosALimpiar.push({
          instancia_id: instancia.id_instancia,
          proyecto_id: p.id_proyecto,
          nombre_proyecto: p.nombre_proyecto,
          nombre_instancia: instancia.nombre_instancia,
        });
      }
    });
  });

  if (proyectosALimpiar.length === 0) {
    alert(
      "No hay proyectos en la lista de limpieza. Todos los proyectos inactivos están preservados.",
    );
    return;
  }

  const confirmacion = confirm(
    `⚠️ ATENCIÓN: Se procederá a LIMPIAR / ELIMINAR ${proyectosALimpiar.length} proyectos inactivos de las instancias Dataiku.\n\n¿Estás seguro de autorizar esta operación?`,
  );

  if (!confirmacion) return;

  $("#btn-autorizar-cambios")
    .prop("disabled", true)
    .text("Ejecutando limpieza...");

  $.ajax({
    url: getWebAppBackendUrl("/ejecutar-limpieza"),
    type: "POST",
    contentType: "application/json",
    data: JSON.stringify({ proyectos_a_limpiar: proyectosALimpiar }),
    success: function (response) {
      $("#btn-autorizar-cambios")
        .prop("disabled", false)
        .text("Conservar cambios y autorizar");
      if (response.status === "ok") {
        alert(
          `✅ Proceso finalizado.\n\nExitosos: ${response.exitosos}\nFallidos: ${response.fallidos}`,
        );
        proyectosPreservados = [];
        cargarProyectosInactivos(); // Recargar el estado real desde Dataiku
      } else {
        alert("Error durante la limpieza: " + response.message);
      }
    },
    error: function () {
      $("#btn-autorizar-cambios")
        .prop("disabled", false)
        .text("Conservar cambios y autorizar");
      alert("Error de comunicación con el servidor al autorizar la limpieza.");
    },
  });
}
