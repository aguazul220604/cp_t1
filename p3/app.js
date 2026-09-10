document.addEventListener("DOMContentLoaded", () => {
  // ==========================================
  // CONFIGURACIÓN Y ESTADO INICIAL
  // ==========================================
  // Tamaño aproximado estimado por bundle
  const BUNDLE_SIZE_GB = 8;

  // Selección de elementos del DOM
  const preserveButtons = document.querySelectorAll(
    ".btn-preserve, .btn-revert",
  );
  const authorizeButton = document.getElementById("btn-authorize");

  const totalSpaceEl = document.getElementById("total-space");
  const freeSpaceEl = document.getElementById("free-space");
  const resultSpaceEl = document.getElementById("result-space");

  let totalSpace = 80;
  let freeSpace = 16;
  let resultSpace = totalSpace - freeSpace;

  // ==========================================
  // FUNCIÓN: Actualizar Métricas en pantalla
  // ==========================================
  function updateMetricsDisplay() {
    resultSpace = totalSpace - freeSpace;

    // Evitar valores negativos
    if (freeSpace < 0) freeSpace = 0;
    if (resultSpace > totalSpace) resultSpace = totalSpace;

    totalSpaceEl.textContent = `${totalSpace} GB`;
    freeSpaceEl.textContent = `${freeSpace} GB`;
    resultSpaceEl.textContent = `${resultSpace} GB`;
  }

  // ==========================================
  // FUNCIÓN: Alternar Estado de Preservar / Revertir
  // ==========================================
  function togglePreserveState(button) {
    const currentState = button.getAttribute("data-state");

    if (currentState === "preserve") {
      // Transición de Preservar -> Revertir
      button.setAttribute("data-state", "revert");
      button.classList.remove("btn-preserve");
      button.classList.add("btn-revert");
      button.textContent = "Revertir";

      // Espacio por liberar
      freeSpace += BUNDLE_SIZE_GB;
    } else {
      // Transición de Revertir -> Preservar
      button.setAttribute("data-state", "preserve");
      button.classList.remove("btn-revert");
      button.classList.add("btn-preserve");
      button.textContent = "Preservar";

      // Disminuye espacio por liberar
      freeSpace -= BUNDLE_SIZE_GB;
    }

    updateMetricsDisplay();
  }

  // ==========================================
  // EVENT LISTENERS
  // ==========================================

  // Asignar el evento Click a cada botón de acción en los bundles
  preserveButtons.forEach((button) => {
    button.addEventListener("click", (e) => {
      togglePreserveState(e.currentTarget);
    });
  });

  // Evento del botón Autorizar
  authorizeButton.addEventListener("click", () => {
    // Recopilar elementos marcados para preservación / eliminación
    const itemsToPreserve = [];
    const itemsToDelete = [];

    document.querySelectorAll(".nickname-group").forEach((group) => {
      const nickname =
        group.querySelector(".nickname-label")?.textContent || "";

      group.querySelectorAll(".action-row, .bundle-list li").forEach((row) => {
        const btn = row.querySelector(".btn");
        const bundleText =
          row.querySelector(".bundle-target, span")?.textContent || "";

        if (btn && bundleText) {
          const state = btn.getAttribute("data-state");
          if (state === "preserve") {
            itemsToPreserve.push({ nickname, path: bundleText });
          } else if (state === "revert") {
            itemsToDelete.push({ nickname, path: bundleText });
          }
        }
      });
    });

    // Confirmación y payload
    const payload = {
      action: "AUTHORIZE_S3_CLEANUP",
      metrics: {
        totalSpaceGB: totalSpace,
        freeSpaceGB: freeSpace,
        resultingSpaceGB: resultSpace,
      },
      preserveList: itemsToPreserve,
      deleteList: itemsToDelete,
    };

    console.log("Payload a enviar al backend de Dataiku:", payload);

    alert(
      `Proceso Autorizado\n\nEspacio a liberar: ${freeSpace} GB\nEspacio resultante: ${resultSpace} GB\n\nRevisa la consola para ver la estructura de datos lista para enviar al Backend.`,
    );
  });

  // Inicializar vista de métricas al cargar
  updateMetricsDisplay();
});
