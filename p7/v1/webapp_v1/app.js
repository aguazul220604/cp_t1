/* PII v1 con estilo Banamex. Vanilla JS, sin dependencias.
   1. CONFIG  2. HELPERS  3. STATE  4. API  5. RENDER  6. INSPECT  7. BOOT */
"use strict";

const API = { process: "process_table" };

function apiUrl(path) {
  if (typeof getWebAppBackendUrl === "function") {
    try { return getWebAppBackendUrl(path); } catch { return path; }
  }
  return path;
}

const $ = (sel, root = document) => root.querySelector(sel);

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}
const pctText = (p) => (Number(p || 0) * 100).toFixed(2) + "%";

const state = { columns: [], busy: false, filter: "", onlyPii: false };

async function apiProcess(formData) {
  const res = await fetch(apiUrl(API.process), { method: "POST", body: formData });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.status !== "success") {
    throw new Error(data.message || ("HTTP " + res.status + " en " + API.process));
  }
  return data;
}

function visibleColumns() {
  const q = state.filter.trim().toLowerCase();
  return state.columns.filter((c) => {
    if (state.onlyPii && !c.is_pii) return false;
    if (!q) return true;
    return [c.source_file, c.name, c.entity].some((v) =>
      String(v ?? "").toLowerCase().includes(q));
  });
}

function renderMeta() {
  const total = state.columns.length;
  const pii = state.columns.filter((c) => c.is_pii).length;
  $("#resultsMeta").textContent = `${total} columnas · ${pii} PII`;
}

function renderTable() {
  const tb = $("#piiListBody");
  tb.textContent = "";
  const rows = visibleColumns();
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.textContent = state.columns.length
      ? "Ninguna columna coincide con el filtro."
      : "Nada inspeccionado todavía. Cuando lo haya, se numera aquí.";
    tr.append(td); tb.append(tr);
    return;
  }
  for (const col of rows) {
    const tr = document.createElement("tr");
    if (col.is_pii) tr.className = "pii-row";
    const ent = col.entity ?? "—";
    const entP = (col.entity_probability === null || col.entity_probability === undefined)
      ? "—" : pctText(col.entity_probability);
    tr.innerHTML =
      `<td>${escapeHtml(col.source_file || "")}</td>` +
      `<td><strong>${escapeHtml(col.name)}</strong></td>` +
      `<td><span class="status-badge ${col.is_pii ? "danger" : "success"}">${col.is_pii ? "PII" : "NO PII"}</span></td>` +
      `<td><span class="prob-num">${pctText(col.pii_probability)}</span></td>` +
      `<td>${escapeHtml(ent)}</td><td>${escapeHtml(entP)}</td>`;
    tb.append(tr);
  }
}

function showAlert(msg, kind = "error") {
  const box = $("#uploadError");
  if (!msg) { box.hidden = true; return; }
  box.className = "alert " + (kind === "warn" ? "alert-warn" : "alert-error");
  $("#uploadError-text").textContent = msg;
  box.hidden = false;
  $("#field-file").classList.toggle("is-error", kind === "error");
}

function setBusy(b) {
  state.busy = b;
  $("#btnProcess").disabled = b;
  $("#btnProcess").textContent = b ? "Analizando…" : "Analizar PII";
  $("#btnGenerateCsv").disabled = b;
  $("#loadingSkeleton").hidden = !b;
  if (b) $("#upload-result").textContent = "Analizando columnas…";
}

function updateFileHint() {
  const input = $("#datasetFile"), hint = $("#fileHint");
  const n = input.files ? input.files.length : 0;
  if (!n) { hint.textContent = "Ningún archivo seleccionado"; hint.classList.remove("has-files"); return; }
  const names = Array.from(input.files).slice(0, 3).map((f) => f.name).join(", ");
  hint.textContent = `${n} archivo(s): ${names}${n > 3 ? ` +${n - 3} más` : ""}`;
  hint.classList.add("has-files");
}

function clearAll() {
  $("#pii-form").reset();
  updateFileHint();
  showAlert(null);
  $("#note-file").textContent = "Se analizan nombres de columna. Nada sale del servidor.";
  state.columns = []; state.filter = ""; state.onlyPii = false;
  $("#in-filter").value = ""; $("#in-only-pii").checked = false;
  $("#upload-result").textContent = "";
  renderMeta(); renderTable();
  $("#datasetFile").focus();
}

async function onSubmit(e) {
  e.preventDefault();
  if (state.busy) return;
  showAlert(null);
  $("#upload-result").textContent = "";
  const input = $("#datasetFile");
  if (!input.files || !input.files.length) {
    showAlert("Por favor, selecciona uno o más archivos CSV o Excel.");
    input.focus();
    return;
  }
  const fd = new FormData();
  Array.from(input.files).forEach((f) => fd.append("file", f));
  setBusy(true);
  try {
    const data = await apiProcess(fd);
    state.columns = data.columns_analysis || [];
    const pii = state.columns.filter((c) => c.is_pii).length;
    renderMeta(); renderTable();
    $("#upload-result").textContent = `${state.columns.length} columnas · ${pii} PII.`;
    if (data.warnings && data.warnings.length) showAlert(data.warnings.join(" | "), "warn");
  } catch (err) {
    showAlert(err.message || "Error desconocido al procesar las tablas.");
  } finally {
    setBusy(false);
  }
}

function toCsvRow(fields) {
  return fields.map((f) => {
    const v = String(f ?? "");
    return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  }).join(",");
}

function handleCsv() {
  if (!state.columns.length) {
    showAlert("Primero analiza al menos una tabla antes de generar el CSV.");
    return;
  }
  const header = ["Archivo", "Nombre de Columna", "Prediccion", "Probabilidad PII (%)", "Entidad", "Probabilidad Entidad (%)"];
  const rows = state.columns.map((c) => [
    c.source_file || "", c.name, c.is_pii ? "PII" : "NO PII",
    (Number(c.pii_probability || 0) * 100).toFixed(2), c.entity ?? "",
    (c.entity_probability === null || c.entity_probability === undefined) ? "" : (Number(c.entity_probability) * 100).toFixed(2),
  ]);
  const blob = new Blob(["\ufeff" + [header, ...rows].map(toCsvRow).join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "analisis_pii.csv";
  document.body.append(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

function boot() {
  $("#pii-form").addEventListener("submit", onSubmit);
  $("#btn-clear").addEventListener("click", clearAll);
  $("#btnGenerateCsv").addEventListener("click", handleCsv);
  $("#datasetFile").addEventListener("change", updateFileHint);
  const drop = $(".file-drop");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("dragover"); }));
  drop.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files.length) {
      $("#datasetFile").files = e.dataTransfer.files;
      updateFileHint();
    }
  });
  $("#in-filter").addEventListener("input", (e) => { state.filter = e.target.value; renderTable(); });
  $("#in-only-pii").addEventListener("change", (e) => { state.onlyPii = e.target.checked; renderTable(); });
  renderMeta(); renderTable(); updateFileHint();
}

document.addEventListener("DOMContentLoaded", boot);
