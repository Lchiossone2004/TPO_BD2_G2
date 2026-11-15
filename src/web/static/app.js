/* FarmaRed · consola de consultas. Sin dependencias; todo el estado vive en memoria. */
(() => {
  "use strict";

  // ---------- utilidades ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => { const r = (Math.random() * 16) | 0; return (c === "x" ? r : (r & 3) | 8).toString(16); }));
  const money = (n) => "$" + Number(n).toLocaleString("es-AR");
  const fdate = (s) => (s ? String(s).slice(0, 10).split("-").reverse().join("/") : "—");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const state = { catalog: [], ref: null, selected: null, op: uuid(), manual: false, token: 0, last: null, resetArmed: false };

  async function api(path, { method = "GET", body } = {}) {
    const t0 = performance.now();
    let res;
    try {
      res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    } catch (e) {
      return { ok: false, status: 0, ms: 0, data: { error: { code: "SIN_CONEXION", message: "No se pudo contactar al servidor." } } };
    }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    return { ok: res.ok, status: res.status, ms: Math.round(performance.now() - t0), data };
  }

  function errorOf(r) {
    const d = r.data || {};
    if (d.error) return { code: d.error.code, message: d.error.message, details: d.error.details };
    if (Array.isArray(d.detail)) return { code: "VALIDACION_ERROR", message: d.detail.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("; "), details: null };
    return { code: `HTTP_${r.status}`, message: d.message || "Error inesperado.", details: null };
  }

  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg; el.classList.add("show");
    clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("show"), 3200);
  }

  // ---------- salud ----------
  async function loadHealth() {
    const r = await api("/api/health");
    const d = r.data || {};
    $("#pill-date").textContent = d.business_date ? `fecha = ${fdate(d.business_date)}` : "—";
    const set = (id, cls, text) => { const el = $(id); el.className = "pill " + cls; el.innerHTML = `<i class="dot"></i>${text}`; };
    const m = d.mongodb || {}, rd = d.redis || {};
    set("#pill-mongo", m.status === "ok" ? "ok" : "bad", m.status === "ok" ? "MongoDB conectado" : "MongoDB caído");
    set("#pill-redis", rd.status === "ok" ? "ok" : "warn", rd.status === "ok" ? `Redis · ${rd.cached_keys_count ?? 0} claves` : "Redis caído (usa MongoDB)");
  }

  async function loadRef() { const r = await api("/api/demo/reference"); state.ref = r.ok ? r.data : null; }

  // ---------- navegación ----------
  function renderSidebar() {
    const groups = [["Consultas", (q) => q.type !== "Servicio"], ["Servicios de escritura", (q) => q.type === "Servicio"]];
    const datosBtn = `<div class="nav-group">Base de datos</div><button class="nav-item" data-id="datos" aria-current="${state.selected === "datos"}"><span class="nav-num">VER</span><span class="nav-title">Datos en vivo</span><span class="nav-meta"><span class="tag mongo">MongoDB</span></span></button>`;
    $("#sidebar").innerHTML = datosBtn + groups.map(([title, f]) => `
      <div class="nav-group">${title}</div>
      ${state.catalog.filter(f).map((q) => `
        <button class="nav-item ${q.implemented ? "" : "pending"}" data-id="${q.id}" aria-current="${state.selected === q.id}">
          <span class="nav-num">${q.id.toUpperCase()}</span>
          <span class="nav-title">${esc(q.title)}</span>
          <span class="nav-meta">${q.engines.map((e) => `<span class="tag ${e === "Redis" ? "redis" : "mongo"}">${e}</span>`).join("")}${q.implemented ? "" : '<span class="tag soon">pendiente</span>'}</span>
        </button>`).join("")}`).join("");
  }

  function select(id) {
    state.selected = id; state.token++;
    history.replaceState(null, "", "#" + id);
    renderSidebar();
    if (id === "datos") { clearInterval(liveState.timer); renderDatos(); } else renderQuery();
    $("#main").scrollTo?.(0, 0); window.scrollTo(0, 0);
  }

  // ---------- piezas de UI ----------
  const tagHtml = (e) => `<span class="tag ${e === "Redis" ? "redis" : "mongo"}">${e}</span>`;
  function head(q) {
    return `<div class="page-head"><div class="kicker">${q.id.toUpperCase()} · ${esc(q.type)}</div><h1>${esc(q.title)}</h1>
      <div class="tags">${q.engines.map(tagHtml).join("")}<span class="tag">${q.method} <code>${esc(q.endpoint)}</code></span></div></div>
      <div class="two-col"><div class="card"><h2>Qué hace</h2><p>${esc(q.description)}</p></div>
      <div class="card"><h2>Cómo se resuelve</h2><p>${esc(q.relations_strategy)}</p></div></div>`;
  }
  const banner = (cls, icon, title, sub = "") => `<div class="banner ${cls}"><span class="icon">${icon}</span><div><strong>${title}</strong>${sub ? `<span class="sub">${sub}</span>` : ""}</div></div>`;
  const jsonBlock = (obj, label = "Respuesta completa (JSON)") => `<details class="card soft"><summary>${label}</summary><pre class="json">${esc(JSON.stringify(obj, null, 2))}</pre></details>`;

  function cellHtml(v) {
    if (v === null || v === undefined || v === "") return '<span class="muted">—</span>';
    if (typeof v === "object") return `<code>${esc(JSON.stringify(v))}</code>`;
    if (typeof v === "boolean") return v ? "sí" : "no";
    return esc(v);
  }
  function tableHtml(rows) {
    if (!rows.length) return '<p class="muted">La consulta no devolvió filas.</p>';
    const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
    return `<div class="table-wrap"><table class="data"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${
      rows.map((r) => `<tr>${cols.map((c) => `<td class="${typeof r[c] === "number" ? "num" : ""}">${cellHtml(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function rowsOf(res) {
    if (Array.isArray(res)) return res.every((x) => x && typeof x === "object") ? res : res.map((v) => ({ valor: v }));
    if (res && typeof res === "object") {
      for (const k of ["filas", "rows", "items", "resultados", "resultado", "data"]) if (Array.isArray(res[k])) return rowsOf(res[k]);
      return [res];
    }
    return [{ valor: res }];
  }

  function historialHtml(res) {
    const c = res.cliente || {}, h = res.historial || [];
    const ficha = `<div class="card"><h2>Cliente ${esc(c._id)}</h2><p>${esc(c.nombre)} ${esc(c.apellido)} · DNI ${esc(c.dni)} · ${esc(c.ciudad)}, ${esc(c.provincia)} · ${esc(c.obra_social || "sin obra social")} · ${c.activo ? "activo" : "inactivo"}</p></div>`;
    if (!h.length) return ficha + `<div class="card"><h2>Historial</h2><p class="muted">Este cliente no tiene ventas ni recetas registradas. Probá con <code>C001</code> para ver un historial completo.</p></div>`;
    const resumen = (e) => { const d = e.detalle || {};
      return e.tipo === "venta" ? `${esc(d.estado)} · ${esc(d.tipo_venta)} · $${esc(d.total)} · ${(d.items || []).length} ítem(s)${d.id_receta ? ` · receta ${esc(d.id_receta)}` : ""}`
          : `${esc(d.estado)} · ${esc(d.tipo_receta)} · ${esc(d.medico)} · dispensas ${esc(d.dispensas_realizadas)}/${esc(d.dispensas_autorizadas)}${d.proxima_dispensa ? ` · próxima ${esc(d.proxima_dispensa)}` : ""}`; };
    return ficha + `<div class="card"><h2>Historial (${h.length})</h2><div class="table-wrap"><table class="data"><thead><tr><th>Fecha</th><th>Tipo</th><th>ID</th><th>Detalle</th></tr></thead><tbody>${h.map((e) => `<tr><td>${fdate(e.fecha)}</td><td>${esc(e.tipo)}</td><td><code>${esc(e.id)}</code></td><td>${resumen(e)}</td></tr>`).join("")}</tbody></table></div></div>`;
  }

  const delta = (a, b) => { const d = b - a; return `<span class="delta ${d < 0 ? "neg" : d > 0 ? "pos" : "zero"}">${d > 0 ? "+" : ""}${d}</span>`; };

  // ---------- línea de tiempo (paso a paso) ----------
  function stepHtml(s, n) {
    const mark = s.kind === "fail" ? "✕" : s.kind === "skip" ? "–" : s.kind === "info" ? "i" : "✓";
    return `<li class="step ${s.kind || "ok"}"><span class="step-n">${s.kind === "fail" || s.kind === "skip" || s.kind === "info" ? mark : n}</span><div><h3>${s.title}</h3><div class="body">${s.body || ""}</div></div></li>`;
  }
  async function playSteps(host, steps, after) {
    const token = state.token;
    host.innerHTML = `<div class="stepper-bar"><label class="toggle"><input type="checkbox" id="chk-manual" ${state.manual ? "checked" : ""}/> Mostrar paso a paso con botón</label>
      <span class="muted" id="step-count"></span></div><ol class="timeline" id="tl"></ol><div class="actions" id="step-actions"></div><div id="after-slot"></div>`;
    $("#chk-manual", host).addEventListener("change", (e) => { state.manual = e.target.checked; });
    const tl = $("#tl", host), actions = $("#step-actions", host), counter = $("#step-count", host);
    let shown = 0;
    const showNext = () => { if (shown >= steps.length) return; tl.insertAdjacentHTML("beforeend", stepHtml(steps[shown], shown + 1)); shown++; counter.textContent = `Paso ${shown} de ${steps.length}`; };
    const finish = () => { actions.innerHTML = ""; $("#after-slot", host).innerHTML = after || ""; };
    if (state.manual) {
      showNext();
      const render = () => {
        if (shown >= steps.length) return finish();
        actions.innerHTML = `<button class="btn primary" id="btn-next" type="button">Siguiente paso ▸</button><button class="btn" id="btn-all" type="button">Mostrar todo</button>`;
        $("#btn-next", host).onclick = () => { showNext(); render(); };
        $("#btn-all", host).onclick = () => { while (shown < steps.length) showNext(); render(); };
      };
      render();
    } else {
      for (let i = 0; i < steps.length; i++) { if (token !== state.token) return; showNext(); await sleep(i === steps.length - 1 ? 150 : 520); }
      if (token === state.token) finish();
    }
  }

  // ---------- antes / después ----------
  function lotesTable(b, a) {
    const ids = [...new Set([...(b?.lotes || []), ...(a?.lotes || [])].map((l) => l.id_lote))];
    if (!ids.length) return '<p class="muted">No hay lotes para mostrar.</p>';
    const get = (s, id) => (s?.lotes || []).find((l) => l.id_lote === id);
    return `<div class="table-wrap"><table class="data"><thead><tr><th>Producto</th><th>Lote</th><th>Vence</th><th class="num">Antes</th><th class="num">Después</th></tr></thead><tbody>${ids.map((id) => {
      const x = get(b, id), y = get(a, id), l = y || x, ub = x ? x.unidades : 0, ua = y ? y.unidades : 0;
      return `<tr class="${ub !== ua ? "changed" : ""}"><td>${esc(l.id_producto)}</td><td><code>${esc(id)}</code> <span class="muted">${esc(l.nro_lote)}</span></td>
        <td>${fdate(l.vencimiento)}${l.vigente ? "" : ' <span class="tag soon">vencido</span>'}</td><td class="num">${ub}</td><td class="num">${ua}${ub !== ua ? delta(ub, ua) : ""}</td></tr>`;
    }).join("")}</tbody></table></div>`;
  }
  function recetaTable(b, a) {
    const x = b?.receta, y = a?.receta;
    if (!x && !y) return "";
    const fields = [["estado", "estado"], ["dispensas_realizadas", "dispensas realizadas"], ["proxima_dispensa", "próxima dispensa"]];
    const val = (o, k) => (k === "proxima_dispensa" ? fdate(o?.[k]) : o?.[k] ?? "—");
    return `<h3 style="margin-top:14px">Receta ${esc((y || x)._id)} <span class="muted">(${esc((y || x).tipo)})</span></h3><div class="table-wrap"><table class="data"><thead><tr><th>Campo</th><th>Antes</th><th>Después</th></tr></thead><tbody>${
      fields.map(([k, label]) => `<tr class="${val(x, k) !== val(y, k) ? "changed" : ""}"><td>${label}</td><td>${esc(val(x, k))}</td><td>${esc(val(y, k))}</td></tr>`).join("")}</tbody></table></div>`;
  }
  function countersTable(b, a) {
    if (!b || !a) return "";
    const rows = [["Ventas en la colección", b.total_ventas, a.total_ventas], ["Contador de ventas", b.contadores?.venta, a.contadores?.venta], ["Contador de detalles", b.contadores?.detalle, a.contadores?.detalle]];
    return `<h3 style="margin-top:14px">Contadores</h3><div class="table-wrap"><table class="data"><thead><tr><th>Dato</th><th class="num">Antes</th><th class="num">Después</th></tr></thead><tbody>${rows.map(([l, x, y]) =>
      `<tr class="${x !== y ? "changed" : ""}"><td>${l}</td><td class="num">${x ?? "—"}</td><td class="num">${y ?? "—"}${x !== y ? delta(x, y) : ""}</td></tr>`).join("")}</tbody></table></div>`;
  }
  function unchanged(b, a) {
    if (!b || !a) return false;
    const key = (s) => JSON.stringify([s.lotes.map((l) => [l.id_lote, l.unidades]), s.receta && [s.receta.estado, s.receta.dispensas_realizadas, String(s.receta.proxima_dispensa)], s.contadores, s.total_ventas, s.venta && s.venta.stock_aplicado]);
    return key(b) === key(a);
  }
  function beforeAfter(b, a, rejected) {
    return `<div class="card"><h2>Antes y después en MongoDB</h2>${rejected ? (unchanged(b, a)
      ? banner("ok", "✓", "Verificado: no cambió nada", "Ni los lotes, ni la receta, ni los contadores, ni la cantidad de ventas. La transacción se revirtió completa.")
      : banner("warn", "!", "Hay diferencias entre antes y después", "Revisá la tabla.")) : ""}
      <h3 style="margin-top:12px">Lotes de la sucursal ${esc(a?.id_sucursal || b?.id_sucursal || "")} (orden FEFO)</h3>${lotesTable(b, a)}${recetaTable(b, a)}${countersTable(b, a)}</div>`;
  }

  // ---------- consultas genéricas (q01–q12) ----------
  function renderGeneric(q) {
    const p = q.parameters || [];
    const fields = p.map((name) => {
      if (name === "id_cliente" && state.ref) return `<label class="field">Cliente<select name="${name}">${state.ref.clientes.map((c) => `<option value="${c.id}">${c.id} · ${esc(c.nombre)}${c.activo ? "" : " (inactivo)"}</option>`).join("")}</select></label>`;
      if (name === "id_sucursal" && state.ref) return `<label class="field">Sucursal<select name="${name}">${state.ref.sucursales.map((s) => `<option value="${s.id}">${s.id} · ${esc(s.nombre)}</option>`).join("")}</select></label>`;
      return `<label class="field">${esc(name)}<input name="${name}" /></label>`;
    }).join("");
    $("#main").innerHTML = head(q) + `<div class="card"><h2>Ejecutar</h2><form id="frm">${p.length ? `<div class="form-grid">${fields}</div>` : '<p class="muted">Esta consulta no recibe parámetros.</p>'}
      <div class="actions"><button class="btn primary" type="submit">Ejecutar ${q.id.toUpperCase()}</button></div></form></div><div id="out"></div>`;
    $("#frm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const params = new URLSearchParams(new FormData(e.target)); const out = $("#out");
      out.innerHTML = '<div class="card"><div class="skeleton"></div><div class="skeleton" style="width:70%"></div></div>';
      const r = await api(`${q.endpoint}?${params}`);
      if (r.status === 501 || (r.data && r.data.status === "pending")) { out.innerHTML = banner("info", "ⓘ", "Todavía no está implementada", "Se habilita cuando se registre su ejecutor en el backend."); return; }
      if (!r.ok) { const er = errorOf(r); out.innerHTML = banner("bad", "✕", `<span class="badge-code">${esc(er.code)}</span>`, esc(er.message)); return; }
      const res0 = r.data.resultado;
      if (res0 && res0.cliente && Array.isArray(res0.historial)) { out.innerHTML = banner("ok", "✓", `${res0.historial.length} ${res0.historial.length === 1 ? "movimiento" : "movimientos"} en ${r.ms} ms`) + historialHtml(res0) + jsonBlock(r.data); return; }
      const rows = rowsOf(r.data.resultado);
      out.innerHTML = banner("ok", "✓", `${rows.length} ${rows.length === 1 ? "fila" : "filas"} en ${r.ms} ms`) + `<div class="card"><h2>Resultado</h2>${tableHtml(rows)}</div>` + jsonBlock(r.data);
    });
  }

  // ---------- q13 ----------
  const Q13_PRESETS = [
    ["good", "Alta de cliente", { accion: "alta", nombre: "Ana", apellido: "Paz", dni: "30111222", email: "ana.paz@mail.com", telefono: "1155001122", ciudad: "Rosario", provincia: "Santa Fe", obra_social: "OSDE", nro_afiliado: "OS-1234" }],
    ["bad", "Alta con DNI duplicado", { accion: "alta", nombre: "Otra", apellido: "Persona", dni: "31245678", ciudad: "Rosario", provincia: "Santa Fe", obra_social: "Galeno" }],
    ["good", "Modificar contacto de C001", { accion: "modificacion", id_cliente: "C001", email: "lucia.nueva@mail.com", telefono: "1144556677", obra_social: "Galeno", nro_afiliado: "GA-555" }],
    ["bad", "Modificar la ciudad (no permitido)", { accion: "modificacion", id_cliente: "C001", ciudad: "Córdoba" }],
    ["good", "Baja lógica de C005", { accion: "baja", id_cliente: "C005" }],
    ["bad", "Baja de cliente inexistente", { accion: "baja", id_cliente: "C999" }],
  ];
  const Q13_FIELDS = ["nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia", "obra_social", "nro_afiliado"];

  function chipsHtml(presets) { return `<div class="chips">${presets.map(([k, l], i) => `<button type="button" class="chip ${k === "good" ? "good" : k === "bad" ? "bad" : ""}" data-i="${i}">${esc(l)}</button>`).join("")}</div>`; }

  function renderQ13(q) {
    const clientes = state.ref?.clientes || [];
    $("#main").innerHTML = head(q) + `<div class="card"><h2>Casos de demostración</h2><p class="muted">Un click carga el formulario; después ejecutá.</p>${chipsHtml(Q13_PRESETS)}</div>
      <div class="card"><h2>Ejecutar</h2><form id="frm"><div class="form-grid">
        <label class="field">Acción<select name="accion"><option value="alta">alta</option><option value="modificacion">modificación</option><option value="baja">baja</option></select></label>
        <label class="field">Cliente (modificación / baja)<select name="id_cliente"><option value="">—</option>${clientes.map((c) => `<option value="${c.id}">${c.id} · ${esc(c.nombre)}${c.activo ? "" : " (inactivo)"}</option>`).join("")}</select></label>
        ${Q13_FIELDS.map((f) => `<label class="field">${f.replace("_", " ")}<input name="${f}" /></label>`).join("")}
      </div><div class="actions"><button class="btn primary" type="submit">Ejecutar q13</button></div></form></div><div id="out"></div>`;
    const frm = $("#frm");
    $("#main").querySelector(".chips").addEventListener("click", (e) => {
      const b = e.target.closest("[data-i]"); if (!b) return;
      const v = Q13_PRESETS[+b.dataset.i][2]; frm.reset();
      for (const [k, val] of Object.entries(v)) if (frm.elements[k]) frm.elements[k].value = val;
    });
    frm.addEventListener("submit", async (e) => {
      e.preventDefault(); const out = $("#out"); const token = state.token;
      const body = Object.fromEntries([...new FormData(frm)].map(([k, v]) => [k, v === "" ? null : v]));
      out.innerHTML = '<div class="card"><div class="skeleton"></div></div>';
      const r = await api(q.endpoint, { method: "POST", body });
      if (token !== state.token) return;
      const steps = [], res = r.data;
      if (!r.ok) {
        const er = errorOf(r);
        steps.push({ title: "Validación del pedido", kind: "fail", body: `<span class="badge-code">${esc(er.code)}</span> ${esc(er.message)}${er.details ? `<div class="muted">${esc(JSON.stringify(er.details))}</div>` : ""}` });
        steps.push({ title: "Transacción abortada", kind: "info", body: "No se escribió nada: el cliente queda como estaba." });
        out.innerHTML = banner("bad", "✕", "Rechazado", `${esc(er.code)} · ${r.ms} ms`) + '<div class="card"><h2>Proceso</h2><div id="proc"></div></div>' + jsonBlock(r.data);
        return playSteps($("#proc"), steps, "");
      }
      const accion = res.accion;
      if (accion === "alta") {
        steps.push({ title: "Validación", body: "Datos obligatorios completos, DNI con 6 a 9 dígitos, email y teléfono con formato válido." });
        steps.push({ title: "ID desde la colección contadores", body: `<code>find_one_and_update($inc)</code> en <code>contadores</code> → <strong>${esc(res.despues._id)}</strong>. Si la transacción se aborta, el contador se revierte y no quedan huecos.` });
        steps.push({ title: "Inserción dentro de la transacción", body: "El índice único sobre <code>dni</code> impide duplicados incluso con altas simultáneas." });
      } else if (accion === "modificacion") {
        steps.push({ title: "Validación", body: "Solo se pueden modificar email, teléfono, obra social y número de afiliado." });
        steps.push({ title: "Lectura del estado anterior", body: `Cliente <strong>${esc(res.antes._id)}</strong> leído con la sesión de la transacción.` });
        steps.push({ title: "Actualización", body: res.cambio ? "Se aplican solo los campos informados; el DNI y el resto quedan intactos." : "No había diferencias: no se modificó nada." });
      } else {
        steps.push({ title: "Lectura del cliente", body: `<strong>${esc(res.antes._id)}</strong> estaba ${res.antes.activo ? "activo" : "inactivo"}.` });
        steps.push({ title: "Baja lógica", body: res.cambio ? "Se marca <code>activo = false</code>; no se borra ningún documento, así sus ventas siguen siendo consistentes." : "Ya estaba inactivo: operación idempotente, sin cambios." });
      }
      const campos = [...new Set([...Object.keys(res.antes || {}), ...Object.keys(res.despues || {})])];
      const diff = `<div class="card"><h2>Antes y después del cliente</h2><div class="table-wrap"><table class="data"><thead><tr><th>Campo</th><th>Antes</th><th>Después</th></tr></thead><tbody>${campos.map((c) => {
        const a = res.antes?.[c], d = res.despues?.[c]; return `<tr class="${JSON.stringify(a) !== JSON.stringify(d) ? "changed" : ""}"><td>${esc(c)}</td><td>${cellHtml(a)}</td><td>${cellHtml(d)}</td></tr>`; }).join("")}</tbody></table></div></div>` + jsonBlock(res);
      out.innerHTML = banner("ok", "✓", `${accion === "alta" ? "Cliente creado" : accion === "baja" ? "Baja registrada" : "Cliente modificado"}${res.cambio ? "" : " (sin cambios)"}`, `${esc(res.despues._id)} · ${r.ms} ms`) + '<div class="card"><h2>Proceso</h2><div id="proc"></div></div>';
      playSteps($("#proc"), steps, diff);
      loadRef();
    });
  }

  // ---------- q14 ----------
  const Q14_PRESETS = [
    ["good", "Venta libre", { c: "C001", f: "F001", r: "", p: "Efectivo", i: [["PRD001", 2]] }],
    ["good", "Varios lotes (FEFO)", { c: "C001", f: "F001", r: "", p: "Débito", i: [["PRD014", 70]] }],
    ["good", "Con receta simple", { c: "C007", f: "F006", r: "RC006", p: "Obra social", i: [["PRD004", 2]] }],
    ["good", "Receta prolongada", { c: "C006", f: "F002", r: "RC004", p: "Obra social", i: [["PRD006", 1]] }],
    ["bad", "Cliente inactivo", { c: "C008", f: "F001", r: "", p: "Efectivo", i: [["PRD001", 1]] }],
    ["bad", "Farmacéutico de droguería", { c: "C001", f: "F007", r: "", p: "Efectivo", i: [["PRD001", 1]] }],
    ["bad", "Producto inactivo", { c: "C001", f: "F001", r: "", p: "Efectivo", i: [["PRD012", 1]] }],
    ["bad", "Receta vencida", { c: "C002", f: "F001", r: "RC009", p: "Efectivo", i: [["PRD004", 1]] }],
    ["bad", "Receta de otro cliente", { c: "C001", f: "F001", r: "RC006", p: "Efectivo", i: [["PRD004", 1]] }],
    ["bad", "Bajo receta sin receta", { c: "C001", f: "F001", r: "", p: "Efectivo", i: [["PRD003", 1]] }],
    ["bad", "Stock insuficiente (con receta)", { c: "C010", f: "F001", r: "RC014", p: "Efectivo", i: [["PRD003", 1000]] }],
    ["repeat", "Reintento: mismo pedido", null],
    ["conflict", "Mismo id_operacion, otro pedido", null],
  ];

  function q14Form(v) {
    const R = state.ref || { clientes: [], farmaceuticos: [], productos: [], recetas: [] };
    const opt = (val, label, sel) => `<option value="${esc(val)}" ${sel ? "selected" : ""}>${esc(label)}</option>`;
    const row = ([id, qty], idx) => `<div class="item-row" data-idx="${idx}"><select class="it-prod">${R.productos.map((p) => opt(p.id, `${p.id} · ${p.nombre} · ${money(p.precio)} · ${p.condicion}${p.activo ? "" : " (inactivo)"}`, p.id === id)).join("")}</select>
      <input class="it-qty" type="number" min="1" step="1" value="${qty}" aria-label="Cantidad" /><button type="button" class="btn small it-del" aria-label="Quitar ítem">✕</button></div>`;
    return `<form id="frm"><div class="form-grid">
      <label class="field">Cliente<select name="c">${R.clientes.map((c) => opt(c.id, `${c.id} · ${c.nombre}${c.activo ? "" : " (inactivo)"}`, c.id === v.c)).join("")}</select></label>
      <label class="field">Farmacéutico<select name="f">${R.farmaceuticos.map((f) => opt(f.id, `${f.id} · ${f.nombre} · ${f.id_sucursal}${f.tipo_sucursal === "Droguería" ? " Droguería" : ""}${f.activo ? "" : " (inactivo)"}`, f.id === v.f)).join("")}</select></label>
      <label class="field">Receta (si hay productos bajo receta)<select name="r"><option value="">— sin receta —</option>${R.recetas.map((r) => opt(r.id, `${r.id} · ${r.id_cliente} · ${r.tipo === "Tratamiento prolongado" ? "Prolongada" : r.tipo} ${r.realizadas}/${r.autorizadas} · ${r.estado}`, r.id === v.r)).join("")}</select></label>
      <label class="field">Medio de pago<select name="p">${["Efectivo", "Débito", "Crédito", "Transferencia", "Obra social"].map((m) => opt(m, m, m === v.p)).join("")}</select></label></div>
      <div class="items"><div class="items-head"><span>Producto</span><span>Cantidad</span><span></span></div><div id="rows">${v.i.map(row).join("")}</div></div>
      <div class="actions"><button type="button" class="btn small" id="btn-add">+ Agregar producto</button></div>
      <div class="actions"><div class="opid">id_operacion: <code id="opid">${esc(state.op)}</code><button type="button" class="btn small" id="btn-newop">Nuevo pedido</button></div>
      <button class="btn primary" type="submit">Ejecutar q14</button></div></form>`;
  }
  function readQ14() {
    const f = $("#frm");
    return { c: f.elements.c.value, f: f.elements.f.value, r: f.elements.r.value, p: f.elements.p.value,
      i: [...document.querySelectorAll(".item-row")].map((r) => [r.querySelector(".it-prod").value, parseInt(r.querySelector(".it-qty").value, 10) || 0]) };
  }
  function q14Body(v) { return { id_cliente: v.c, id_farmaceutico: v.f, id_receta: v.r || null, medio_pago: v.p, id_operacion: state.op, items: v.i.map(([id, q]) => ({ id_producto: id, cantidad: q })) }; }

  const FAIL_STEP = { OPERACION_CONFLICTO: 1, STOCK_INSUFICIENTE: 4, RESULTADO_POR_VERIFICAR: 6 };

  function renderQ14(q) {
    const first = Q14_PRESETS[0][2];
    $("#main").innerHTML = head(q) + `<div class="card"><h2>Casos de demostración</h2><p class="muted">Los verdes terminan bien; los rojos muestran un rechazo y comprueban que no quedó nada a medias.</p>${chipsHtml(Q14_PRESETS)}</div>
      <div class="card"><h2>Pedido</h2><div id="formhost">${q14Form(first)}</div></div><div id="out"></div>`;
    bindQ14Form(q);
    $("#main").querySelector(".chips").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-i]"); if (!b) return;
      const [kind, , v] = Q14_PRESETS[+b.dataset.i];
      if (kind === "repeat" || kind === "conflict") {
        if (!state.last) return toast("Primero ejecutá una venta para poder reintentarla.");
        const cur = state.last; // vuelve a cargar el último pedido con su mismo id_operacion
        state.op = cur.op;
        const vv = JSON.parse(JSON.stringify(cur.v)); if (kind === "conflict") vv.i[0][1] += 1;
        $("#formhost").innerHTML = q14Form(vv); bindQ14Form(q);
        return runQ14(q);
      }
      state.op = uuid(); $("#formhost").innerHTML = q14Form(v); bindQ14Form(q);
    });
  }
  function bindQ14Form(q) {
    const frm = $("#frm");
    frm.addEventListener("submit", (e) => { e.preventDefault(); runQ14(q); });
    $("#btn-newop").onclick = () => { state.op = uuid(); $("#opid").textContent = state.op; toast("Nuevo id_operacion: se tratará como un pedido distinto."); };
    $("#btn-add").onclick = () => { const v = readQ14(); v.i.push([state.ref.productos[0].id, 1]); $("#formhost").innerHTML = q14Form(v); bindQ14Form(q); };
    frm.addEventListener("click", (e) => { if (e.target.closest(".it-del")) { const v = readQ14(); const idx = +e.target.closest(".item-row").dataset.idx; if (v.i.length > 1) { v.i.splice(idx, 1); $("#formhost").innerHTML = q14Form(v); bindQ14Form(q); } } });
  }

  const snapUrl = (v) => `/api/demo/snapshot?${new URLSearchParams({ id_cliente: v.c, id_farmaceutico: v.f, id_receta: v.r || "", productos: [...new Set(v.i.map((x) => x[0]))].join(",") })}`;

  async function runQ14(q) {
    const v = readQ14(), body = q14Body(v), out = $("#out"), token = state.token;
    out.innerHTML = '<div class="card"><div class="skeleton"></div><div class="skeleton" style="width:60%"></div></div>';
    const before = (await api(snapUrl(v))).data;
    const r = await api(q.endpoint, { method: "POST", body });
    if (token !== state.token) return;
    const after = (await api(snapUrl(v))).data;
    state.last = { v: JSON.parse(JSON.stringify(v)), op: state.op };
    const R = state.ref, cli = R.clientes.find((c) => c.id === v.c), far = R.farmaceuticos.find((f) => f.id === v.f);
    const prods = v.i.map(([id, n]) => ({ ...(R.productos.find((p) => p.id === id) || { id, nombre: id }), n }));
    const steps = [];
    const validations = () => `<div class="chips"><span class="tag">cliente ${esc(v.c)} activo</span><span class="tag">farmacéutico ${esc(v.f)} activo en ${esc(far?.tipo_sucursal || "Farmacia")}</span>${prods.map((p) => `<span class="tag">${esc(p.id)} activo</span>`).join("")}${v.r ? `<span class="tag">receta ${esc(v.r)} vigente y del cliente</span>` : ""}</div>`;
    const idStep = (extra = "") => ({ title: "Idempotencia: ¿ya se procesó este pedido?", body: `Se busca una venta con <code>id_operacion</code> <code>${esc(state.op.slice(0, 13))}…</code> en <code>ventas</code>. ${extra}` });

    if (r.ok && r.data.idempotente) {
      const vta = r.data.venta;
      steps.push({ ...idStep(`Existe la venta <strong>${esc(vta._id)}</strong> y la huella del pedido coincide.`), kind: "info" });
      steps.push({ title: "Se devuelve la venta ya confirmada", body: "No se ejecutan validaciones, no se descuenta stock ni se toca la receta: un reintento nunca duplica una venta." });
      out.innerHTML = banner("info", "↺", `Pedido repetido: se devolvió ${esc(vta._id)}`, `HTTP ${r.status} · ${r.ms} ms · sin cambios en la base`) + '<div class="card"><h2>Proceso</h2><div id="proc"></div></div>';
      return playSteps($("#proc"), steps, beforeAfter(before, after, true) + jsonBlock(r.data));
    }
    if (r.ok) {
      const d = r.data, vta = d.venta;
      steps.push({ ...idStep("No existe: es un pedido nuevo. Se calcula la huella (SHA-256) de los argumentos normalizados."), body: undefined });
      steps[0].body = `Se busca una venta con <code>id_operacion</code> <code>${esc(state.op.slice(0, 13))}…</code>. No existe: es un pedido nuevo y se guarda su huella <code>${esc((vta.huella_solicitud || "").slice(0, 10))}…</code>.`;
      steps.push({ title: "Validaciones con la sesión de la transacción", body: validations() + '<div class="muted">Los precios se leen de MongoDB y el total se calcula en el servidor.</div>' });
      const detalles = vta.items.map((i) => i.id_detalle);
      steps.push({ title: "IDs desde la colección contadores", body: `Venta <strong>${esc(vta._id)}</strong> · detalle ${detalles.map((x) => `<code>${esc(x)}</code>`).join(", ")}.` });
      const lotesInfo = (id) => (before?.lotes || []).find((l) => l.id_lote === id);
      steps.push({ title: "Descuento FEFO con actualización condicional", body: `<div class="table-wrap"><table class="data"><thead><tr><th>Producto</th><th>Lote</th><th>Vence</th><th class="num">Unidades tomadas</th></tr></thead><tbody>${vta.asignaciones_stock.map((a) => `<tr><td>${esc(a.id_producto)}</td><td><code>${esc(a.id_lote)}</code></td><td>${fdate(lotesInfo(a.id_lote)?.vencimiento)}</td><td class="num">${a.unidades}</td></tr>`).join("")}</tbody></table></div><div class="muted">Se consume primero el lote que vence antes; cada <code>update</code> exige <code>unidades ≥ cantidad</code>, así dos ventas simultáneas nunca dejan stock negativo.</div>` });
      steps.push(d.receta_despues ? { title: "Receta actualizada", body: `<strong>${esc(d.receta_despues._id)}</strong>: dispensas ${d.receta_antes.dispensas_realizadas} → ${d.receta_despues.dispensas_realizadas}, estado ${esc(d.receta_antes.estado)} → <strong>${esc(d.receta_despues.estado)}</strong>${d.receta_despues.proxima_dispensa ? `, próxima dispensa ${fdate(d.receta_despues.proxima_dispensa)}` : ""}.` } : { title: "Sin receta", kind: "skip", body: "Venta libre: no hay receta que actualizar." });
      steps.push({ title: "Inserción de la venta y commit", body: `<strong>${esc(vta._id)}</strong> · ${vta.items.length} ${vta.items.length === 1 ? "ítem" : "ítems"} · total <strong>${money(vta.total)}</strong> · <code>estado: Completada</code> · <code>stock_aplicado: true</code>. Contadores, stock, receta y venta se confirman <strong>juntos</strong>.` });
      out.innerHTML = banner("ok", "✓", `Venta ${esc(vta._id)} registrada · ${money(vta.total)}`, `HTTP ${r.status} · ${r.ms} ms · ${esc(cli?.nombre || v.c)} atendido por ${esc(far?.nombre || v.f)}`) + '<div class="card"><h2>Proceso</h2><div id="proc"></div></div>';
      playSteps($("#proc"), steps, beforeAfter(before, after, false) + jsonBlock(d));
      loadRef();
      return;
    }
    // rechazo
    const er = errorOf(r), failAt = FAIL_STEP[er.code] || 2;
    const labels = ["Idempotencia: ¿ya se procesó este pedido?", "Validaciones con la sesión de la transacción", "IDs desde la colección contadores", "Descuento FEFO con actualización condicional", "Actualización de la receta", "Inserción de la venta y commit"];
    for (let n = 1; n <= Math.min(failAt, 6); n++) {
      if (n < failAt) steps.push({ title: labels[n - 1], body: n === 1 ? "El id_operacion no estaba registrado." : n === 2 ? validations() : "Ejecutado dentro de la transacción (todavía sin confirmar)." });
      else steps.push({ title: labels[n - 1], kind: "fail", body: `<span class="badge-code">${esc(er.code)}</span> ${esc(er.message)}${er.details ? `<div class="muted"><code>${esc(JSON.stringify(er.details))}</code></div>` : ""}` });
    }
    steps.push({ title: "Rollback: la transacción se aborta", kind: "info", body: failAt >= 3 ? "Se revierten el contador de IDs, los descuentos ya hechos y cualquier cambio de receta. No queda venta." : "No se había escrito nada: no queda venta, descuento ni cambio de receta." });
    out.innerHTML = banner("bad", "✕", `Pedido rechazado · ${esc(er.code)}`, `HTTP ${r.status} · ${r.ms} ms · ${esc(er.message)}`) + '<div class="card"><h2>Proceso</h2><div id="proc"></div></div>';
    playSteps($("#proc"), steps, beforeAfter(before, after, true) + jsonBlock(r.data));
  }

  // ---------- q15 ----------
  const Q15_PRESETS = [
    ["good", "Descontar el escenario técnico (V900)", "V900"],
    ["repeat", "Repetir sobre V900 (ya aplicado)", "V900"],
    ["info", "Venta histórica V013 (sin desglose)", "V013"],
    ["bad", "Venta pendiente V011", "V011"],
    ["bad", "Venta anulada V015", "V015"],
    ["bad", "Venta inexistente V999", "V999"],
  ];
  function renderQ15(q) {
    const R = state.ref || { ventas: [] };
    const label = (v) => `${v.id} · ${v.estado} · ${v.origen || "csv"} · stock ${v.stock_aplicado ? "aplicado" : "SIN aplicar"} · ${v.id_cliente}`;
    $("#main").innerHTML = head(q) + `<div class="card"><h2>Casos de demostración</h2>
      <p class="muted">q15 sola trabaja sobre una venta ya registrada. Como <code>q14</code> siempre deja el stock aplicado, se usa un escenario técnico (venta <code>V900</code>) que se puede recrear.</p>
      <div class="chips"><button class="btn small" id="btn-fx">Preparar escenario V900 (normal)</button><button class="btn small" id="btn-fx0">Preparar V900 sin stock suficiente</button></div>${chipsHtml(Q15_PRESETS)}</div>
      <div class="card"><h2>Ejecutar</h2><form id="frm"><div class="form-grid"><label class="field">Venta<select name="id_venta">${R.ventas.map((v) => `<option value="${v.id}" ${v.id === "V900" ? "selected" : ""}>${esc(label(v))}</option>`).join("")}<option value="V999">V999 · (no existe)</option></select></label></div>
      <div class="actions"><button class="btn primary" type="submit">Ejecutar q15</button></div></form></div><div id="out"></div>`;
    const frm = $("#frm");
    $("#main").querySelectorAll(".chips")[1].addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) { frm.elements.id_venta.value = Q15_PRESETS[+b.dataset.i][2]; runQ15(q); } });
    const fx = async (caso) => { const r = await api(`/api/demo/fixture-q15?caso=${caso}`, { method: "POST" }); if (r.ok) { toast(caso === "sin_stock" ? "V900 recreada pidiendo 5000 unidades." : "V900 recreada (4 unidades, dos lotes)."); await loadRef(); renderQuery(); } else toast("No se pudo preparar el escenario."); };
    $("#btn-fx").onclick = () => fx("normal"); $("#btn-fx0").onclick = () => fx("sin_stock");
    frm.addEventListener("submit", (e) => { e.preventDefault(); runQ15(q); });
  }
  async function runQ15(q) {
    const id = $("#frm").elements.id_venta.value, out = $("#out"), token = state.token;
    out.innerHTML = '<div class="card"><div class="skeleton"></div><div class="skeleton" style="width:60%"></div></div>';
    const snap = (await api(`/api/demo/snapshot?id_venta=${encodeURIComponent(id)}`));
    const before = snap.ok ? snap.data : null;
    const r = await api(q.endpoint, { method: "POST", body: { id_venta: id } });
    if (token !== state.token) return;
    const after = snap.ok ? (await api(`/api/demo/snapshot?id_venta=${encodeURIComponent(id)}`)).data : null;
    const steps = [];
    if (r.ok) {
      const d = r.data;
      steps.push({ title: "Venta encontrada y elegible", body: `<strong>${esc(d.id_venta)}</strong> está <code>Completada</code>. Las ventas Pendientes o Anuladas se rechazan.` });
      if (d.aplicado_ahora) {
        steps.push({ title: "Reserva de la venta dentro de la transacción", body: "Actualización condicional <code>stock_aplicado: false → true</code>. Si dos pedidos llegan a la vez, solo uno la consigue; el otro ve el resultado ya aplicado." });
        const info = (idl) => (before?.lotes || []).find((l) => l.id_lote === idl);
        steps.push({ title: "Descuento FEFO en la sucursal del farmacéutico", body: `<div class="table-wrap"><table class="data"><thead><tr><th>Producto</th><th>Lote</th><th>Vence</th><th class="num">Unidades tomadas</th></tr></thead><tbody>${d.asignaciones.map((a) => `<tr><td>${esc(a.id_producto)}</td><td><code>${esc(a.id_lote)}</code></td><td>${fdate(info(a.id_lote)?.vencimiento)}</td><td class="num">${a.unidades}</td></tr>`).join("")}</tbody></table></div><div class="muted">Solo lotes con unidades &gt; 0 y vencimiento ≥ hoy, ordenados por vencimiento y <code>_id</code>.</div>` });
        steps.push({ title: "Se guardan las asignaciones y se confirma", body: "La marca y las asignaciones por lote quedan en la venta, y el descuento se confirma junto con ellas." });
        out.innerHTML = banner("ok", "✓", `Stock descontado para ${esc(d.id_venta)}`, `HTTP ${r.status} · ${r.ms} ms`) + '<div class="card"><h2>Proceso</h2><div id="proc"></div></div>';
      } else {
        steps.push({ title: "El stock ya estaba aplicado", kind: "info", body: d.asignaciones.length ? "Se devuelven las asignaciones registradas; no se descuenta otra vez." : esc(d.nota || "Venta histórica sin desglose por lote: no se descontó nada.") });
        out.innerHTML = banner("info", "↺", `Sin cambios: ${esc(d.id_venta)} ya tenía el stock aplicado`, `HTTP ${r.status} · ${r.ms} ms`) + '<div class="card"><h2>Proceso</h2><div id="proc"></div></div>';
      }
      return playSteps($("#proc"), steps, beforeAfter(before, after, !d.aplicado_ahora) + jsonBlock(d));
    }
    const er = errorOf(r), step = er.code === "STOCK_INSUFICIENTE" ? 3 : 1;
    steps.push(step === 1 ? { title: "Venta encontrada y elegible", kind: "fail", body: `<span class="badge-code">${esc(er.code)}</span> ${esc(er.message)}` } : { title: "Venta encontrada y elegible", body: `Completada y sin stock aplicado.` });
    if (step === 3) {
      steps.push({ title: "Reserva de la venta dentro de la transacción", body: "stock_aplicado: false → true (todavía sin confirmar)." });
      steps.push({ title: "Descuento FEFO en la sucursal del farmacéutico", kind: "fail", body: `<span class="badge-code">${esc(er.code)}</span> ${esc(er.message)}${er.details ? `<div class="muted"><code>${esc(JSON.stringify(er.details))}</code></div>` : ""}` });
      steps.push({ title: "Rollback", kind: "info", body: "Se revierte la marca y cualquier descuento parcial: ningún lote cambia y la venta sigue sin stock aplicado." });
    } else steps.push({ title: "Sin cambios", kind: "info", body: "No se escribió nada." });
    out.innerHTML = banner("bad", "✕", `Rechazado · ${esc(er.code)}`, `HTTP ${r.status} · ${r.ms} ms · ${esc(er.message)}`) + '<div class="card"><h2>Proceso</h2><div id="proc"></div></div>';
    playSteps($("#proc"), steps, (before ? beforeAfter(before, after, true) : "") + jsonBlock(r.data));
  }


  // ---------- datos en vivo (colecciones de MongoDB) ----------
  const LIVE_SETS = { q13: ["clientes", "contadores"], q14: ["ventas", "recetas", "stock_lotes", "contadores"], q15: ["stock_lotes", "ventas"] };
  const liveState = { timer: null };
  function liveCell(v) {
    if (v === null || v === undefined || v === "") return '<span class="muted">—</span>';
    if (Array.isArray(v)) return `<code title="${esc(JSON.stringify(v))}">[${v.length} ${v.length === 1 ? "ítem" : "ítems"}]</code>`;
    if (typeof v === "object") return `<code title="${esc(JSON.stringify(v))}">{…}</code>`;
    if (typeof v === "boolean") return v ? "sí" : "no";
    return esc(v);
  }
  function mountLive(host, names, { title = "Datos en vivo (MongoDB)" } = {}) {
    clearInterval(liveState.timer);
    const st = { names, cur: names ? names[0] : null, base: {}, prev: {}, auto: false, desc: !!names, filter: "", counts: {} };
    host.innerHTML = `<div class="card live"><div class="live-head"><h2>${esc(title)}</h2>
      <div class="live-ctrl"><input type="search" class="live-filter" placeholder="Filtrar filas…" aria-label="Filtrar filas" />
      <label class="toggle"><input type="checkbox" class="live-desc" ${names ? "checked" : ""} /> Más nuevos primero</label>
      <label class="toggle"><input type="checkbox" class="live-auto" /> Actualizar solo</label>
      <button class="btn" type="button" data-act="refresh">Actualizar</button>
      <button class="btn ghost" type="button" data-act="mark" title="Toma el estado actual como punto de partida para las diferencias">Marcar punto de partida</button></div></div>
      <div class="live-tabs"></div><div class="live-body"></div></div>`;
    const tabs = $(".live-tabs", host), body = $(".live-body", host);
    const renderTabs = () => {
      tabs.innerHTML = Object.keys(st.counts).map((n) => {
        const c = st.counts[n], b = st.base[n], d = b === undefined ? 0 : c - b;
        return `<button type="button" class="live-tab ${n === st.cur ? "on" : ""}" data-n="${esc(n)}"><span>${esc(n)}</span><b>${c}</b>${d ? `<span class="delta ${d > 0 ? "pos" : "neg"}">${d > 0 ? "+" : ""}${d}</span>` : ""}</button>`;
      }).join("");
    };
    async function refresh() {
      if (!document.body.contains(host)) { clearInterval(liveState.timer); return; }
      const cs = await api("/api/demo/collections");
      if (!cs.ok) { body.innerHTML = '<p class="muted">No se pudo leer MongoDB.</p>'; return; }
      const all = cs.data.collections, show = st.names || all.map((c) => c.name);
      st.counts = {}; all.filter((c) => show.includes(c.name)).forEach((c) => { st.counts[c.name] = c.count; if (st.base[c.name] === undefined) st.base[c.name] = c.count; });
      if (!st.counts[st.cur]) st.cur = Object.keys(st.counts)[0];
      renderTabs();
      const r = await api(`/api/demo/collection/${encodeURIComponent(st.cur)}?limit=300${st.desc ? "&desc=true" : ""}`);
      if (!r.ok) { body.innerHTML = '<p class="muted">No se pudo leer la colección.</p>'; return; }
      const { docs, count, shown } = r.data, prev = st.prev[st.cur] || null, now = {};
      const cols = ["_id", ...new Set(docs.flatMap((d) => Object.keys(d)).filter((k) => k !== "_id"))];
      const f = st.filter.trim().toLowerCase();
      const rows = docs.filter((d) => !f || JSON.stringify(d).toLowerCase().includes(f));
      const trs = rows.map((d) => {
        const sig = JSON.stringify(d); now[d._id] = sig;
        const cls = prev === null ? "" : prev[d._id] === undefined ? "new" : prev[d._id] !== sig ? "changed" : "";
        return `<tr class="${cls}">${cols.map((c) => `<td class="${typeof d[c] === "number" ? "num" : ""}">${liveCell(d[c])}</td>`).join("")}</tr>`;
      }).join("");
      docs.forEach((d) => { now[d._id] = JSON.stringify(d); });
      st.prev[st.cur] = now;
      const b = st.base[st.cur], dd = b === undefined ? 0 : count - b;
      body.innerHTML = `<p class="live-sum"><strong>${esc(st.cur)}</strong>: ${count} documentos${dd ? ` <span class="delta ${dd > 0 ? "pos" : "neg"}">${dd > 0 ? "+" : ""}${dd} desde el punto de partida (${b})</span>` : ` <span class="muted">(sin cambios desde el punto de partida: ${b})</span>`}${shown < count ? ` · mostrando ${shown}` : ""}${f ? ` · filtrados ${rows.length}` : ""}
        <span class="legend"><i class="lg new"></i>nuevo <i class="lg changed"></i>modificado</span></p>
        <div class="table-wrap live-wrap"><table class="data"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${trs}</tbody></table></div>`;
    }
    host.addEventListener("click", (e) => {
      const t = e.target.closest(".live-tab"); if (t) { st.cur = t.dataset.n; refresh(); return; }
      const a = e.target.closest("[data-act]"); if (!a) return;
      if (a.dataset.act === "refresh") refresh();
      if (a.dataset.act === "mark") { st.base = { ...st.counts }; st.prev = {}; refresh(); toast("Punto de partida marcado."); }
    });
    $(".live-filter", host).addEventListener("input", (e) => { st.filter = e.target.value; refresh(); });
    $(".live-desc", host).addEventListener("change", (e) => { st.desc = e.target.checked; st.prev = {}; refresh(); });
    $(".live-auto", host).addEventListener("change", (e) => { st.auto = e.target.checked; });
    liveState.timer = setInterval(() => { if (st.auto && !document.hidden) refresh(); }, 2000);
    refresh();
  }
  function renderDatos() {
    $("#main").innerHTML = `<div class="page-head"><div class="kicker">MONGODB · SOLO LECTURA</div><h1>Datos en vivo</h1>
      <p class="muted">Todas las colecciones con su cantidad de documentos. Con «Actualizar solo» se refresca cada 2 s (o con el botón Actualizar)</p></div><div id="live"></div>`;
    mountLive($("#live"), null, { title: "Colecciones" });
  }

  // ---------- render principal ----------
  function renderQuery() {
    const q = state.catalog.find((x) => x.id === state.selected);
    if (!q) return;
    clearInterval(liveState.timer);
    if (q.id === "q13") renderQ13(q);
    else if (q.id === "q14") renderQ14(q);
    else if (q.id === "q15") renderQ15(q);
    else return renderGeneric(q);
    $("#main").insertAdjacentHTML("beforeend", '<div id="live"></div>');
    mountLive($("#live"), LIVE_SETS[q.id]);
  }

  async function resetDemo() {
    const btn = $("#btn-reset");
    if (!state.resetArmed) { state.resetArmed = true; btn.textContent = "¿Seguro? Click de nuevo"; btn.classList.add("danger"); setTimeout(() => { state.resetArmed = false; btn.textContent = "Reiniciar datos"; btn.classList.remove("danger"); }, 4000); return; }
    state.resetArmed = false; btn.classList.remove("danger"); btn.textContent = "Recargando…"; btn.disabled = true;
    const r = await api("/api/demo/reset", { method: "POST" });
    btn.disabled = false; btn.textContent = "Reiniciar datos";
    if (r.ok && r.data.status === "ok") { toast("Datos recargados y escenario de q15 recreado."); state.last = null; await loadRef(); loadHealth(); renderQuery(); }
    else toast("No se pudo recargar: " + ((r.data && r.data.log) || "error"));
  }

  async function init() {
    $("#sidebar").addEventListener("click", (e) => { const b = e.target.closest(".nav-item"); if (b) select(b.dataset.id); });
    $("#btn-reset").addEventListener("click", resetDemo);
    const cat = await api("/api/queries");
    state.catalog = cat.ok ? cat.data.queries : [];
    await Promise.all([loadRef(), loadHealth()]);
    setInterval(loadHealth, 15000);
    const want = (location.hash || "").slice(1).toLowerCase();
    select(want === "datos" || state.catalog.some((q) => q.id === want) ? want : "q14");
  }
  document.addEventListener("DOMContentLoaded", init);
})();
