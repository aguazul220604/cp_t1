// Variable global para almacenar el listado en memoria
let listaInstancias = [];

// ==========================================
// 1. INICIALIZACIÓN
// ==========================================
$(document).ready(function () {
  cargarInstancias();
  registrarEventos();
  cargarImagenLogo(); // <-- Agregamos la llamada para cargar la imagen al iniciar
});

// ==========================================
// 2. REGISTRO DE EVENTOS Y LISTAGEM
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
