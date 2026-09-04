/* ==========================================
ESTADO DE LA APLICACIÓN 
   ========================================== */
let proyectosData = {
  "Instancia DEV 1": [
    {
      id: "DEV1_P1",
      nombre: "Proyecto 1",
      jobs: 12,
      ultima_ejec: "2026-01-02",
      ultima_mod: "2025-12-15",
      usuarios: 3,
      escenarios: 5,
      actividad: [13, 21, 5, 19, 10],
    },
    {
      id: "DEV1_P2",
      nombre: "Proyecto 2",
      jobs: 0,
      ultima_ejec: "2025-10-10",
      ultima_mod: "2025-09-01",
      usuarios: 1,
      escenarios: 0,
      actividad: [5, 2, 0, 0, 0],
    },
    {
      id: "DEV1_P3",
      nombre: "Proyecto 3",
      jobs: 45,
      ultima_ejec: "2026-02-15",
      ultima_mod: "2026-02-10",
      usuarios: 5,
      escenarios: 12,
      actividad: [20, 15, 30, 25, 40],
    },
  ],
  "Instancia DEV 2": [
    {
      id: "DEV2_P1",
      nombre: "Proyecto Alpha",
      jobs: 2,
      ultima_ejec: "2025-08-20",
      ultima_mod: "2025-08-15",
      usuarios: 2,
      escenarios: 1,
      actividad: [1, 0, 2, 0, 0],
    },
  ],
};

let proyectosPreservados = {};
let proyectoSeleccionadoActual = null;
let instanciaSeleccionadaActual = null;

// Variables para destruir gráficas previas de Chart.js
let chartActividad = null;
let chartDistribucion = null;

/* ==========================================
   INICIALIZACIÓN Y RENDERIZADO
   ========================================== */
document.addEventListener("DOMContentLoaded", () => {
  // Asignar eventos de escucha
  const btnPreservar = document.getElementById("btn-conservar-proyecto");
  const btnLimpiar = document.getElementById("btn-autorizar-limpieza");

  if (btnPreservar) btnPreservar.addEventListener("click", preservarProyecto);
  if (btnLimpiar) btnLimpiar.addEventListener("click", confirmarLimpieza);

  if (typeof dataiku !== "undefined" && dataiku.fetch) {
    dataiku
      .fetch("get_proyectos", { method: "GET" })
      .then((response) => {
        if (!response.ok)
          throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
      })
      .then((data) => {
        proyectosData = data;
        renderizarColumnaIzquierda();
      })
      .catch((error) => {
        console.error(
          "Error cargando proyectos desde backend, usando mock data:",
          error,
        );
        renderizarColumnaIzquierda();
      });
  } else {
    renderizarColumnaIzquierda();
  }

  renderizarColumnaDerecha();
});

function renderizarColumnaIzquierda() {
  const contenedor = document.getElementById("lista-instancias-container");
  if (!contenedor) return;
  contenedor.innerHTML = "";

  for (const [instancia, proyectos] of Object.entries(proyectosData)) {
    if (!proyectos || proyectos.length === 0) continue;

    const divInstancia = document.createElement("div");
    divInstancia.className = "instance-group";

    const titulo = document.createElement("h3");
    titulo.className = "instance-name";
    titulo.textContent = instancia;
    divInstancia.appendChild(titulo);

    proyectos.forEach((proyecto) => {
      const btn = document.createElement("button");
      btn.className = "btn-project";
      btn.textContent = proyecto.nombre;

      if (
        proyectoSeleccionadoActual &&
        proyectoSeleccionadoActual.id === proyecto.id
      ) {
        btn.classList.add("active");
      }

      btn.addEventListener("click", () =>
        seleccionarProyecto(instancia, proyecto),
      );
      divInstancia.appendChild(btn);
    });

    contenedor.appendChild(divInstancia);
  }
}

function renderizarColumnaDerecha() {
  const contenedor = document.getElementById("lista-preservados-container");
  if (!contenedor) return;
  contenedor.innerHTML = "";

  for (const [instancia, proyectos] of Object.entries(proyectosPreservados)) {
    proyectos.forEach((proyecto) => {
      const item = document.createElement("div");
      item.className = "preserved-item";
      item.innerHTML = `
        <div class="preserved-info">
            <span class="preserved-instance">${instancia}</span>
            <span class="preserved-project">${proyecto.nombre}</span>
        </div>
        <button class="btn btn-action btn-revertir" onclick="revertirProyecto('${instancia}', '${proyecto.id}')">Revertir</button>
      `;
      contenedor.appendChild(item);
    });
  }
}

/* ==========================================
   LÓGICA DE SELECCIÓN Y GRÁFICAS
   ========================================== */
function seleccionarProyecto(instancia, proyecto) {
  proyectoSeleccionadoActual = proyecto;
  instanciaSeleccionadaActual = instancia;

  renderizarColumnaIzquierda();

  document.getElementById("detalle-instancia-titulo").textContent = instancia;
  document.getElementById("detalle-proyecto-titulo").textContent =
    proyecto.nombre;

  document.getElementById("metric-jobs").textContent = proyecto.jobs;
  document.getElementById("metric-last-exec").textContent =
    proyecto.ultima_ejec;
  document.getElementById("metric-last-mod").textContent = proyecto.ultima_mod;
  document.getElementById("metric-users").textContent = proyecto.usuarios;
  document.getElementById("metric-scenarios").textContent = proyecto.escenarios;

  dibujarGraficas(proyecto.actividad);
}

function dibujarGraficas(datos) {
  const labels = ["Clase 1", "Clase 2", "Clase 3", "Clase 4", "Clase 5"];

  if (chartActividad) chartActividad.destroy();
  if (chartDistribucion) chartDistribucion.destroy();

  const canvasBarras = document.getElementById("canvas-barras");
  if (canvasBarras) {
    const ctxBarras = canvasBarras.getContext("2d");
    chartActividad = new Chart(ctxBarras, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Actividad",
            data: datos,
            backgroundColor: "#6b8e23",
          },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false },
    });
  }

  const canvasDist = document.getElementById("canvas-distribucion");
  if (canvasDist) {
    const ctxDist = canvasDist.getContext("2d");
    chartDistribucion = new Chart(ctxDist, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Distribución",
            data: datos,
            backgroundColor: "#a52a2a",
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
      },
    });
  }
}

/* ==========================================
   MOVER PROYECTOS
   ========================================== */
function preservarProyecto() {
  if (!proyectoSeleccionadoActual) return;

  // Remover de la lista original
  proyectosData[instanciaSeleccionadaActual] = proyectosData[
    instanciaSeleccionadaActual
  ].filter((p) => p.id !== proyectoSeleccionadoActual.id);

  // Agregar a preservados
  if (!proyectosPreservados[instanciaSeleccionadaActual]) {
    proyectosPreservados[instanciaSeleccionadaActual] = [];
  }
  proyectosPreservados[instanciaSeleccionadaActual].push(
    proyectoSeleccionadoActual,
  );

  // Resetear selección
  proyectoSeleccionadoActual = null;
  instanciaSeleccionadaActual = null;

  // Resetear interfaz
  document.getElementById("detalle-proyecto-titulo").textContent =
    "Seleccione un proyecto";
  document.getElementById("detalle-instancia-titulo").textContent = "-";

  // Limpiar métricas
  document.getElementById("metric-jobs").textContent = "-";
  document.getElementById("metric-last-exec").textContent = "-";
  document.getElementById("metric-last-mod").textContent = "-";
  document.getElementById("metric-users").textContent = "-";
  document.getElementById("metric-scenarios").textContent = "-";

  if (chartActividad) chartActividad.destroy();
  if (chartDistribucion) chartDistribucion.destroy();

  renderizarColumnaIzquierda();
  renderizarColumnaDerecha();
}

window.revertirProyecto = function (instancia, proyectoId) {
  if (!proyectosPreservados[instancia]) return;

  const proyectoIndex = proyectosPreservados[instancia].findIndex(
    (p) => p.id === proyectoId,
  );

  if (proyectoIndex === -1) return;

  const proyecto = proyectosPreservados[instancia][proyectoIndex];

  proyectosPreservados[instancia].splice(proyectoIndex, 1);
  if (proyectosPreservados[instancia].length === 0) {
    delete proyectosPreservados[instancia];
  }

  if (!proyectosData[instancia]) proyectosData[instancia] = [];
  proyectosData[instancia].push(proyecto);

  renderizarColumnaIzquierda();
  renderizarColumnaDerecha();
};

/* ==========================================
   ENVIAR AL BACKEND 
   ========================================== */
function confirmarLimpieza() {
  if (
    confirm(
      "¿Estás seguro de que deseas limpiar y borrar los proyectos restantes?",
    )
  ) {
    if (typeof dataiku !== "undefined" && dataiku.fetch) {
      dataiku
        .fetch("ejecutar_limpieza", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(proyectosData),
        })
        .then((response) => {
          if (!response.ok) throw new Error("Error en la solicitud");
          return response.json();
        })
        .then((result) => {
          alert(
            `Se limpiaron exitosamente ${result.total_procesados || 0} proyectos.`,
          );
          location.reload();
        })
        .catch((error) => {
          console.error("Error al ejecutar limpieza:", error);
          alert("Ocurrió un error al limpiar los proyectos.");
        });
    } else {
      console.warn("Entorno de Dataiku no detectado.");
    }
  }
}
