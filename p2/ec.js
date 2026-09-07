
App · JS
(function () {
  'use strict';
 
  // ==== Api ====
  // Único lugar del archivo que hace fetch. Todo lo demás pasa por aquí.
  const Api = {
    async get(path) {
      const res = await fetch(getWebAppBackendUrl(path));
      return res.json();
    },
    async post(path, body) {
      const res = await fetch(getWebAppBackendUrl(path), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      return res.json();
    }
  };
 
  // ==== UI ====
  // Único lugar que toca SweetAlert2. Si algún día cambia la librería
  // (por bloqueo de CDN, por ejemplo), solo se edita aquí.
  const UI = {
    success(msg) {
      return Swal.fire({ text: msg, confirmButtonText: 'Confirmar', confirmButtonColor: '#0a222c' });
    },
    error(msg) {
      return Swal.fire({ text: msg, confirmButtonText: 'Confirmar', confirmButtonColor: '#0a222c' });
    },
    async confirm(msg) {
      const r = await Swal.fire({
        text: msg,
        showCancelButton: true,
        confirmButtonText: 'Confirmar',
        cancelButtonText: 'Cancelar',
        confirmButtonColor: '#0a222c'
      });
      return r.isConfirmed;
    },
    async editModal(instancia) {
      const { value } = await Swal.fire({
        title: 'Editar Registro de Instancia',
        html:
          `<input id="swal-nombre" class="swal2-input" placeholder="Nombre actual" value="${instancia.nombre}">` +
          `<input id="swal-url" class="swal2-input" placeholder="URL actual" value="${instancia.url}">` +
          `<input id="swal-apikey" class="swal2-input" placeholder="Global API Key actual" value="${instancia.api_key ?? ''}">`,
        confirmButtonText: 'Confirmar',
        confirmButtonColor: '#0a222c',
        focusConfirm: false,
        preConfirm: () => ({
          nombre: document.getElementById('swal-nombre').value.trim(),
          url: document.getElementById('swal-url').value.trim(),
          api_key: document.getElementById('swal-apikey').value.trim()
        })
      });
      return value; // undefined si el usuario canceló
    }
  };
 
  // ==== Views ====
  // Cada vista solo orquesta: pide datos a Api, pinta con DOM/UI, nunca hace fetch directo.
  const Views = {
    registro: {
      _instancias: [],
 
      async render() {
        const data = await Api.get('/obtener-instancias');
        if (data.status !== 'ok') {
          UI.error(data.message || 'No se pudieron cargar las instancias');
          return;
        }
        this._instancias = data.instancias;
 
        const tbody = document.querySelector('#tablaInstancias tbody');
        tbody.innerHTML = '';
        data.instancias.forEach((inst) => {
          const tr = document.createElement('tr');
          tr.innerHTML = `
            <td>${inst.nombre}</td>
            <td>${inst.url}</td>
            <td>
              <button class="btn btn-blue btn-sm" data-action="editar" data-id="${inst.id}">Editar</button>
              <button class="btn btn-red btn-sm" data-action="eliminar" data-id="${inst.id}">Eliminar</button>
            </td>`;
          tbody.appendChild(tr);
        });
      },
 
      init() {
        const form = document.getElementById('formRegistro');
        form.addEventListener('submit', async (e) => {
          e.preventDefault();
          const body = {
            nombre: document.getElementById('regNombre').value.trim(),
            url: document.getElementById('regUrl').value.trim(),
            api_key: document.getElementById('regApiKey').value.trim()
          };
          const data = await Api.post('/registrar-instancia', body);
          if (data.status === 'ok') {
            form.reset();
            await UI.success('Su instancia se ha registrado con éxito');
            this.render();
          } else {
            await UI.error(data.message || 'Error al registrar');
          }
        });
 
        document.querySelector('#tablaInstancias tbody').addEventListener('click', async (e) => {
          const btn = e.target.closest('button[data-action]');
          if (!btn) return;
          const id = btn.dataset.id;
          const instancia = this._instancias.find((i) => String(i.id) === id);
 
          if (btn.dataset.action === 'eliminar') {
            const ok = await UI.confirm('¿Está seguro de eliminar la instancia?');
            if (!ok) return;
            const data = await Api.post('/eliminar-instancia', { id });
            if (data.status === 'ok') {
              await UI.success('Su instancia se ha eliminado con éxito');
              this.render();
            } else {
              await UI.error(data.message || 'Error al eliminar');
            }
          }
 
          if (btn.dataset.action === 'editar') {
            const values = await UI.editModal(instancia);
            if (!values) return;
            const data = await Api.post('/actualizar-instancia', { id, ...values });
            if (data.status === 'ok') {
              await UI.success('Su instancia se ha actualizado con éxito');
              this.render();
            } else {
              await UI.error(data.message || 'Error al actualizar');
            }
          }
        });
 
        this.render();
      }
    },
 
    limpieza: {
      init() {
        // Pendiente: conectar aquí las rutas de métricas por proyecto
        // (jobs ejecutados, última modificación, distribución de actividad)
        // una vez que existan en el backend.
      }
    }
  };
 
  // ==== Router ====
  // El hash es la única fuente de verdad; el <select> solo lo lee/escribe.
  const Router = {
    views: ['registro', 'limpieza'],
    initialized: {},
 
    navigate(name) {
      if (!this.views.includes(name)) name = this.views[0];
 
      document.querySelectorAll('.view').forEach((el) => {
        el.hidden = el.dataset.view !== name;
      });
      document.getElementById('viewSelector').value = name;
 
      if (!this.initialized[name] && Views[name] && Views[name].init) {
        Views[name].init();
        this.initialized[name] = true;
      }
    },
 
    start() {
      window.addEventListener('hashchange', () => this.navigate(location.hash.slice(1)));
      document.getElementById('viewSelector').addEventListener('change', (e) => {
        location.hash = e.target.value;
      });
      this.navigate(location.hash.slice(1) || this.views[0]);
    }
  };
 
  // ==== Bootstrap ====
  document.addEventListener('DOMContentLoaded', () => Router.start());
})();