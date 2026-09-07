// Variable global para almacenar el listado en memoria
let listaInstancias = [];

// ==========================================
// 1. INICIALIZACIÓN
// ==========================================
$(document).ready(function () {
  cargarInstancias();
  registrarEventos();
  cargarImagenLogo();
});

// ==========================================
// 2. REGISTRO DE EVENTOS (TODO EN UN SOLO LUGAR)
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

  // ---- Selección de proyecto en la vista de análisis ----
  // Delegado sobre document porque .btn-project se crea dinámicamente
  $(document).on("click", ".btn-project", function () {
    // Resaltar el botón activo
    $(".btn-project").removeClass("active");
    $(this).addClass("active");

    const idInstancia = $(this).data("instancia");
    const idProyecto = $(this).data("proyecto");
    const nombreProyecto = $(this).text();

    consultarMétricasProyecto(idInstancia, idProyecto, nombreProyecto);
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

  // Validación básica del formulario (Frame 3)
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
        // Asigna la cadena Base64 al atributo src de tu etiqueta img en el HTML
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
// 9. LÓGICA DE LA VISTA 2 (ANÁLISIS DE PROYECTOS)
// ==========================================

// Carga la lista de instancias y sus proyectos inactivos en la barra lateral izquierda
function cargarProyectosInactivos() {
  const sidebar = $(".sidebar-projects");
  sidebar
    .empty()
    .append('<p class="text-center">Consultando proyectos en Dataiku...</p>');

  $.ajax({
    url: getWebAppBackendUrl("/obtener-proyectos-inactivos"),
    type: "GET",
    success: function (response) {
      if (response.status === "ok") {
        renderizarSidebarProyectos(response.datos);
      } else {
        sidebar
          .empty()
          .append(
            `<p class="text-center text-red">Error: ${response.message}</p>`,
          );
      }
    },
    error: function (err) {
      console.error("Error al obtener proyectos:", err);
      sidebar
        .empty()
        .append('<p class="text-center">Ocurrió un error de conexión.</p>');
    },
  });
}

function renderizarSidebarProyectos(datosPorInstancia) {
  const sidebar = $(".sidebar-projects");
  sidebar.empty();

  if (!datosPorInstancia || datosPorInstancia.length === 0) {
    sidebar.append(
      '<p class="text-center">No se encontraron proyectos inactivos.</p>',
    );
    return;
  }

  // Iterar por cada instancia que regrese el backend
  datosPorInstancia.forEach(function (instancia) {
    let grupoHTML = `
      <div class="instance-group card-panel">
        <h3>Instancia ${instancia.nombre_instancia}</h3>
        <div class="projects-list">
    `;

    instancia.proyectos.forEach(function (proyecto) {
      grupoHTML += `
        <button class="btn-project" 
                data-instancia="${instancia.id_instancia}" 
                data-proyecto="${proyecto.id_proyecto}">
          ${proyecto.nombre_proyecto}
        </button>
      `;
    });

    grupoHTML += `</div></div>`;
    sidebar.append(grupoHTML);
  });
}

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

        // 1. DIBUJAR GRÁFICAS CSS
        renderizarGraficasCSS(response.datos_graficas);

        // 2. ACTUALIZAR MÉTRICAS DE TEXTO
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
