(() => {
  "use strict";

  const Q14_STORAGE_KEY = "farmared.q14.pending_operation.v1";

  const QUERY_SPECS = {
    q01: {
      code: "Q1",
      title: "Productos activos con datos completos de proveedor",
      type: "Lectura",
      engine: "MongoDB + Redis",
      method: "GET",
      endpoint: "/api/queries/q01",
      description:
        "Lista todos los productos con activo = true junto con el documento completo de su proveedor habitual, sin filtrar por la actividad del proveedor.",
      strategy:
        "MongoDB consulta los IDs de productos activos; la lectura y enriquecimiento de producto y proveedor utiliza cache-aside en Redis (farmared:producto:<id>, farmared:proveedor:<id>, TTL 300s) con fallback directo a MongoDB.",
      paramsHint: "Sin parámetros obligatorios",
      noParamsNote:
        "Esta consulta no requiere parámetros de entrada. Utiliza cache-aside en Redis con fallback transparente a MongoDB si Redis no está disponible.",
    },
    q02: {
      code: "Q2",
      title: "Ventas en estado 'Pendiente' con farmacéutico y sucursal",
      type: "Lectura",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q02",
      description:
        "Obtiene las ventas cuya cabecera tiene estado = 'Pendiente' junto con nombre y matrícula del farmacéutico, su sucursal y el total ARS.",
      strategy:
        "Filtrado en ventas por índice {estado: 1, fecha: 1} y cruce $lookup hacia farmaceuticos y sucursales en MongoDB.",
      paramsHint: "Sin parámetros obligatorios",
      noParamsNote:
        "Consulta de lectura pura sin parámetros. Las ventas Pendientes no descuentan stock ni computan ingresos.",
    },
    q03: {
      code: "Q3",
      title: "Historial cronológico completo de un cliente",
      type: "Lectura",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q03",
      description:
        "Devuelve la línea temporal unificada de ventas (fecha) y recetas (fecha_emision) de un cliente, ordenada cronológicamente con desempate por tipo e ID.",
      strategy:
        "Consulta indexada en ventas {id_cliente: 1, fecha: 1} y recetas {id_cliente: 1, fecha_emision: 1}, combinada y ordenada determinísticamente.",
      paramsHint: "Requiere id_cliente",
      fields: [
        {
          name: "id_cliente",
          label: "ID de cliente",
          placeholder: "Ej. C001",
          defaultValue: "C001",
          required: true,
          help: "Identificador de dominio en clientes._id (C001, C003, C006…).",
          samples: ["C001", "C003", "C006"],
        },
      ],
    },
    q04: {
      code: "Q4",
      title: "Clientes con más de una receta registrada",
      type: "Agregación",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q04",
      description:
        "Agrupa todas las recetas registradas por cliente (sin restringir por estado) y retorna quienes poseen más de una receta con su cantidad.",
      strategy:
        "Pipeline de agregación en recetas ($group por id_cliente, $match cantidad > 1, $lookup a clientes).",
      paramsHint: "Sin parámetros obligatorios",
      noParamsNote:
        "Agregación global sobre la colección recetas. Cuenta todas las recetas registradas por cada cliente.",
    },
    q05: {
      code: "Q5",
      title: "Farmacéuticos activos y ventas en últimos 60 días",
      type: "Agregación",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q05",
      description:
        "Muestra cada farmacéutico activo y su cantidad de ventas (Completada o Pendiente, excluyendo Anulada) en los últimos 60 días respecto a hoy(), incluyendo los que tienen 0 ventas.",
      strategy:
        "Parte desde farmaceuticos {activo: true} con $lookup filtrado a ventas en la ventana [hoy - 60 días, hoy] y estado != 'Anulada'.",
      paramsHint: "Sin parámetros · Usa hoy()",
      noParamsNote:
        "Ventana dinámica calculada con hoy() en America/Argentina/Buenos_Aires: desde hoy - 60 días hasta hoy inclusive.",
    },
    q06: {
      code: "Q6",
      title: "Recetas prolongadas vigentes con próxima dispensa vencida",
      type: "Lectura",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q06",
      description:
        "Lista recetas de tipo 'Tratamiento prolongado' en estado 'Vigente' cuya proxima_dispensa no sea nula y sea estrictamente anterior a hoy(), con los datos del cliente.",
      strategy:
        "Índice compuesto {tipo: 1, estado: 1, proxima_dispensa: 1} en recetas y $lookup hacia clientes.",
      paramsHint: "Sin parámetros · Usa hoy()",
      noParamsNote:
        "Compara proxima_dispensa < hoy() normalizado a fecha calendario en Buenos Aires.",
    },
    q07: {
      code: "Q7",
      title: "Top 5 productos más vendidos (unidades)",
      type: "Agregación",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q07",
      description:
        "Calcula los 5 productos con mayor suma de unidades vendidas considerando únicamente ventas en estado 'Completada', desempatando por ID de producto.",
      strategy:
        "Pipeline en ventas ($match estado = 'Completada', $unwind items, $group por id_producto, $sort unidades DESC / _id ASC, $limit 5, $lookup a productos).",
      paramsHint: "Sin parámetros obligatorios",
      noParamsNote:
        "Aprovecha los ítems embebidos en ventas sin requerir joins contra una colección separada de detalle.",
    },
    q08: {
      code: "Q8",
      title: "Lotes con menos de 50 unidades",
      type: "Lectura",
      engine: "MongoDB + Redis",
      method: "GET",
      endpoint: "/api/queries/q08",
      description:
        "Obtiene todos los lotes de stock_lotes con unidades < 50 (incluyendo 0 y lotes vencidos), enriquecidos con producto, sucursal y proveedor.",
      strategy:
        "Lee lotes en MongoDB por {unidades: {$lt: 50}}, resuelve sucursales en MongoDB y enriquece producto + proveedor mediante caché Redis con fallback.",
      paramsHint: "Sin parámetros obligatorios",
      noParamsNote:
        "Incluye lotes agotados (0 unidades) y lotes vencidos según criterio de Q8.",
    },
    q09: {
      code: "Q9",
      title: "Ventas 'Venta libre' con total menor a $5.000",
      type: "Lectura",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q09",
      description:
        "Lista las ventas de tipo 'Venta libre' con total estrictamente menor a $5.000 ARS, excluyendo ventas en estado 'Anulada'.",
      strategy:
        "Consulta indexada en ventas por {tipo: 'Venta libre', total: {$lt: 5000}, estado: {$ne: 'Anulada'}}.",
      paramsHint: "Sin parámetros obligatorios",
      noParamsNote:
        "Incluye ventas Completadas y Pendientes cuyo importe entero sea estrictamente menor a 5000 ARS.",
    },
    q10: {
      code: "Q10",
      title: "Clientes distintos atendidos en una sucursal",
      type: "Lectura",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q10",
      description:
        "Obtiene los clientes distintos atendidos en una sucursal dada a través de los farmacéuticos asignados a ella (estén activos o no).",
      strategy:
        "Busca farmacéuticos por {id_sucursal} en farmaceuticos, cruza sus ventas registradas sin filtrar estado de venta ni actividad del cliente, y devuelve clientes únicos.",
      paramsHint: "Requiere id_sucursal",
      fields: [
        {
          name: "id_sucursal",
          label: "ID de sucursal",
          placeholder: "Ej. S001",
          defaultValue: "S001",
          required: true,
          help: "Identificador en sucursales._id (S001..S004 Farmacias, S005 Droguería).",
          samples: ["S001", "S002", "S003"],
        },
      ],
    },
    q11: {
      code: "Q11",
      title: "Ingresos totales por farmacéutico en el mes actual",
      type: "Agregación",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q11",
      description:
        "Vista agregada de ingresos totales (ARS) facturados por cada farmacéutico durante el mes calendario actual, considerando solo ventas 'Completada'.",
      strategy:
        "Agregación en ventas dentro del rango [primer día del mes actual, primer día del mes siguiente) con estado = 'Completada', sin filtrar actividad actual del farmacéutico.",
      paramsHint: "Sin parámetros · Usa hoy()",
      noParamsNote:
        "Calcula automáticamente el rango del mes actual a partir de hoy() en America/Argentina/Buenos_Aires.",
    },
    q12: {
      code: "Q12",
      title: "Clientes sin ventas registradas en el último año",
      type: "Lectura",
      engine: "MongoDB",
      method: "GET",
      endpoint: "/api/queries/q12",
      description:
        "Detecta clientes que no poseen ninguna venta registrada (incluyendo Pendientes y Anuladas) dentro del último año hasta hoy() inclusive.",
      strategy:
        "Obtiene los id_cliente con ventas en [hoy - 1 año, hoy] y consulta en clientes los documentos excluidos de ese conjunto.",
      paramsHint: "Sin parámetros · Usa hoy()",
      noParamsNote:
        "Considera cualquier registro en ventas (Completada, Pendiente o Anulada) como actividad en el último año.",
    },
    q13: {
      code: "Q13",
      title: "ABM completo de clientes",
      type: "Servicio",
      engine: "MongoDB",
      method: "POST",
      endpoint: "/api/services/clientes",
      description:
        "Alta de cliente (generando ID con contadores y validando DNI único), modificación restringida a contacto/cobertura (email, telefono, obra_social, nro_afiliado) y baja lógica conservando DNI.",
      strategy:
        "Transacción MongoDB para secuencia en contadores + índice único {dni: 1}. Rechaza modificación de campos no permitidos como dni, ciudad o provincia y normaliza nro_afiliado a null si es 'Sin cobertura'.",
      paramsHint: "Seleccionar operación ABM",
      customKind: "q13",
    },
    q14: {
      code: "Q14",
      title: "Registro de nueva venta 'Completada' con transacción integral",
      type: "Servicio",
      engine: "MongoDB",
      method: "POST",
      endpoint: "/api/services/ventas",
      description:
        "Registra una venta Completada validando cliente activo, farmacéutico activo de sucursal 'Farmacia', productos activos, receta Vigente del cliente (si corresponde), calcula total en servidor, actualiza receta y descuenta stock FEFO en una sola transacción.",
      strategy:
        "Una única transacción ACID (session.with_transaction) en MongoDB rs0 + idempotencia mediante id_operacion UUID persistido en localStorage y huella_solicitud.",
      paramsHint: "Pedido con id_operacion UUID en localStorage + ítems",
      customKind: "q14",
    },
    q15: {
      code: "Q15",
      title: "Descuento masivo de stock FEFO para venta registrada",
      type: "Servicio",
      engine: "MongoDB",
      method: "POST",
      endpoint: "/api/services/stock/descontar",
      description:
        "Dada una venta registrada, decrementa las unidades de cada producto en stock_lotes de la sucursal del farmacéutico aplicando criterio FEFO y omitiendo lotes vencidos; rechaza todo si algún ítem no alcanza.",
      strategy:
        "Transacción ACID en MongoDB sobre stock_lotes ordenados por (vencimiento ASC, _id ASC) con actualización condicional unidades >= cantidad. Idempotente si stock_aplicado = true; para uso independiente requiere venta Completada de origen 'servicio' con stock_aplicado = false.",
      paramsHint: "Requiere id_venta",
      customKind: "q15",
    },
  };

  const state = {
    activeTab: "architecture",
    architectureLoaded: false,
    queries: [],
    activeFilter: "all",
    selectedQueryId: null,
    q13Mode: "alta",
    q14Op: loadQ14State(),
  };

  const els = {};

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function generateUuidV4() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function defaultQ14State() {
    return {
      id_operacion: generateUuidV4(),
      id_cliente: "C001",
      id_farmaceutico: "F001",
      id_receta: "",
      medio_pago: "Efectivo",
      items: [{ id_producto: "PRD001", cantidad: 1 }],
    };
  }

  function loadQ14State() {
    try {
      const raw = window.localStorage.getItem(Q14_STORAGE_KEY);
      if (!raw) {
        const fresh = defaultQ14State();
        window.localStorage.setItem(Q14_STORAGE_KEY, JSON.stringify(fresh));
        return fresh;
      }
      const parsed = JSON.parse(raw);
      if (!parsed || !parsed.id_operacion) {
        throw new Error("invalid q14 state");
      }
      if (!Array.isArray(parsed.items) || parsed.items.length === 0) {
        parsed.items = [{ id_producto: "PRD001", cantidad: 1 }];
      }
      return parsed;
    } catch (_err) {
      return defaultQ14State();
    }
  }

  function persistQ14State() {
    try {
      window.localStorage.setItem(Q14_STORAGE_KEY, JSON.stringify(state.q14Op));
    } catch (_err) {
      // Ignora restricciones de almacenamiento si el navegador bloquea localStorage.
    }
  }

  function normalizeQueryId(rawId) {
    const cleaned = String(rawId || "").trim().toLowerCase();
    const match = cleaned.match(/^q0*(\d+)$/);
    if (match) {
      return `q${String(Number(match[1])).padStart(2, "0")}`;
    }
    return cleaned;
  }

  function normalizeCatalogItem(raw, index) {
    const rawId = raw.id || raw.query_id || raw.code || `q${String(index + 1).padStart(2, "0")}`;
    const normId = normalizeQueryId(rawId);
    const spec = QUERY_SPECS[normId] || {};

    const engineRaw = raw.engines || raw.engine || raw.motor || raw.motors || spec.engine || "MongoDB";
    const engineLabel = Array.isArray(engineRaw) ? engineRaw.join(" + ") : String(engineRaw);

    return {
      ...raw,
      id: normId,
      rawId: String(rawId),
      code: spec.code || (raw.code ? String(raw.code).toUpperCase() : normId.toUpperCase()),
      title: raw.title || raw.name || raw.nombre || spec.title || `Consulta ${normId.toUpperCase()}`,
      type: raw.type || raw.tipo || raw.category || spec.type || "Lectura",
      engine: engineLabel,
      implemented: Boolean(raw.implemented),
      description: raw.description || raw.descripcion || spec.description || "",
      strategy:
        raw.relations_strategy ||
        raw.strategy ||
        raw.relation_strategy ||
        raw.consistency ||
        raw.estrategia ||
        spec.strategy ||
        "Resolución directa sobre colecciones MongoDB.",
      endpoint: raw.endpoint || raw.path || spec.endpoint || `/api/queries/${normId}`,
      method: raw.method || spec.method || "GET",
      spec,
    };
  }

  function cacheElements() {
    els.businessDate = document.getElementById("business-date-value");
    els.businessTz = document.getElementById("business-tz-value");
    els.mongoPill = document.getElementById("mongo-status-pill");
    els.mongoStatus = document.getElementById("mongo-status-value");
    els.redisPill = document.getElementById("redis-status-pill");
    els.redisStatus = document.getElementById("redis-status-value");
    els.btnRefreshHealth = document.getElementById("btn-refresh-health");
    els.healthBanner = document.getElementById("health-banner");

    els.tabBtns = Array.from(document.querySelectorAll(".tab-btn"));
    els.panelArch = document.getElementById("panel-architecture");
    els.panelQueries = document.getElementById("panel-queries");
    els.queriesCountBadge = document.getElementById("queries-count-badge");

    els.archDbBadge = document.getElementById("arch-db-badge");
    els.archLoading = document.getElementById("architecture-loading");
    els.archContent = document.getElementById("architecture-content");
    els.motorsGrid = document.getElementById("motors-grid");
    els.consistencyPanel = document.getElementById("consistency-panel");
    els.redisKeysGrid = document.getElementById("redis-keys-grid");
    els.collectionsGrid = document.getElementById("collections-grid");
    els.alternativesGrid = document.getElementById("alternatives-grid");

    els.sidebarTotalLabel = document.getElementById("sidebar-total-label");
    els.filterChips = Array.from(document.querySelectorAll(".filter-chip"));
    els.queriesList = document.getElementById("queries-list");
    els.queryEmptyState = document.getElementById("query-empty-state");
    els.queryDetailPanel = document.getElementById("query-detail-panel");

    els.detailCode = document.getElementById("detail-code");
    els.detailTitle = document.getElementById("detail-title");
    els.detailEndpointLine = document.getElementById("detail-endpoint-line");
    els.detailBadges = document.getElementById("detail-badges");
    els.detailDescription = document.getElementById("detail-description");
    els.detailStrategy = document.getElementById("detail-strategy");
    els.paramsHint = document.getElementById("params-hint");
    els.paramsForm = document.getElementById("query-params-form");

    els.btnTestEndpoint = document.getElementById("btn-test-endpoint");
    els.btnInspectCatalog = document.getElementById("btn-inspect-catalog");
    els.resultStatusBadge = document.getElementById("result-status-badge");
    els.resultArea = document.getElementById("query-result-area");
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_err) {
        data = { raw: text };
      }
    }
    return { status: response.status, ok: response.ok, data };
  }

  function setPillState(pillEl, valueEl, stateClass, text) {
    pillEl.classList.remove("status-pill--loading", "status-pill--ok", "status-pill--warn", "status-pill--error");
    pillEl.classList.add(stateClass);
    valueEl.textContent = text;
  }

  async function refreshHealth() {
    els.btnRefreshHealth.disabled = true;
    els.btnRefreshHealth.textContent = "Actualizando…";
    try {
      const { ok, data } = await fetchJson("/api/health");
      if (!ok || !data) {
        throw new Error("No se pudo obtener /api/health");
      }

      els.businessDate.textContent = data.business_date || "—";
      els.businessTz.textContent = data.timezone || "America/Argentina/Buenos_Aires";

      const mongoOk = data.mongodb && data.mongodb.status === "ok";
      const redisOk = data.redis && data.redis.status === "ok";

      if (mongoOk) {
        const rsName = data.mongodb.replica_set || "rs0";
        const colCount =
          typeof data.mongodb.collection_count === "number"
            ? ` · ${data.mongodb.collection_count} col.`
            : "";
        setPillState(els.mongoPill, els.mongoStatus, "status-pill--ok", `OK · ${rsName}${colCount}`);
      } else {
        const reason = (data.mongodb && (data.mongodb.detail || data.mongodb.error || data.mongodb.status)) || "No disponible";
        setPillState(els.mongoPill, els.mongoStatus, "status-pill--error", `Degradado (${reason})`);
      }

      if (redisOk) {
        const ttl = data.redis.ttl_seconds ?? 300;
        const keys =
          typeof data.redis.cached_keys_count === "number"
            ? ` · ${data.redis.cached_keys_count} claves`
            : "";
        setPillState(els.redisPill, els.redisStatus, "status-pill--ok", `OK · TTL ${ttl}s${keys}`);
      } else {
        setPillState(els.redisPill, els.redisStatus, "status-pill--warn", "Caído · Fallback MongoDB");
      }

      if (!mongoOk) {
        els.healthBanner.className = "alert-banner alert-banner--error";
        els.healthBanner.textContent =
          "MongoDB no está disponible en este momento. Verificá que el servicio Replica Set rs0 esté inicializado en Docker Compose.";
      } else if (!redisOk) {
        els.healthBanner.className = "alert-banner";
        els.healthBanner.textContent =
          (data.redis && data.redis.message) ||
          "Redis no está disponible: Q1 y Q8 operan en modo fallback directo a MongoDB sin afectar la integridad de las ventas.";
      } else {
        els.healthBanner.className = "alert-banner is-hidden";
        els.healthBanner.textContent = "";
      }
    } catch (_err) {
      setPillState(els.mongoPill, els.mongoStatus, "status-pill--error", "Error de conexión");
      setPillState(els.redisPill, els.redisStatus, "status-pill--error", "Error de conexión");
      els.healthBanner.className = "alert-banner alert-banner--error";
      els.healthBanner.textContent = "No se pudo consultar GET /api/health. Verificá que el servidor Uvicorn esté activo.";
    } finally {
      els.btnRefreshHealth.disabled = false;
      els.btnRefreshHealth.textContent = "Actualizar estado";
    }
  }

  async function loadArchitecture() {
    try {
      const { ok, data } = await fetchJson("/api/architecture");
      if (!ok || !data) {
        throw new Error("Respuesta inválida en /api/architecture");
      }
      renderArchitecture(data);
      state.architectureLoaded = true;
    } catch (err) {
      els.archLoading.textContent = `Error al cargar la arquitectura: ${err.message}`;
    }
  }

  function renderArchitecture(arch) {
    els.archDbBadge.innerHTML = `Base autoritativa: <strong class="mono">${escapeHtml(arch.database || "farmared")}</strong>`;

    const mongo = (arch.motors && arch.motors.mongodb) || {};
    const redis = (arch.motors && arch.motors.redis) || {};

    els.motorsGrid.innerHTML = `
      <article class="motor-card motor-card--mongo">
        <div class="motor-card-head">
          <div>
            <h4>${escapeHtml(mongo.name || "MongoDB")}</h4>
            <p class="motor-subtitle">${escapeHtml(mongo.paradigm || "Documental")} · ${escapeHtml(mongo.deployment || "Replica Set rs0")}</p>
          </div>
          <span class="badge badge--mongo">${escapeHtml(mongo.role || "Fuente de verdad")}</span>
        </div>
        <p>${escapeHtml(mongo.justification || "")}</p>
        <div class="motor-callout">
          <strong>¿Por qué <code>stock_lotes</code> en MongoDB?</strong><br />
          ${escapeHtml(mongo.why_stock_in_mongodb || "")}
        </div>
      </article>

      <article class="motor-card motor-card--redis">
        <div class="motor-card-head">
          <div>
            <h4>${escapeHtml(redis.name || "Redis")}</h4>
            <p class="motor-subtitle">${escapeHtml(redis.paradigm || "Clave-Valor")} · TTL ${escapeHtml(redis.ttl_seconds ?? 300)} s</p>
          </div>
          <span class="badge badge--redis">${escapeHtml(redis.role || "Cache-Aside")}</span>
        </div>
        <p>${escapeHtml(redis.justification || "")}</p>
        <div class="motor-callout">
          <strong>Tolerancia a fallos (fallback):</strong><br />
          ${escapeHtml(redis.fallback || "")}
        </div>
      </article>
    `;

    const consistency = arch.consistency_strategy || {};
    els.consistencyPanel.innerHTML = `
      <p class="consistency-summary">${escapeHtml(consistency.summary || "")}</p>
      <div class="consistency-grid">
        <div class="consistency-item">
          <h4>Transacción integrada Q14–Q15</h4>
          <p>${escapeHtml(consistency.q14_q15_integrated || "")}</p>
        </div>
        <div class="consistency-item">
          <h4>FEFO determinista en <code>stock_lotes</code></h4>
          <p>${escapeHtml(consistency.fefo_rule || "")}</p>
        </div>
        <div class="consistency-item">
          <h4>Idempotencia por <code>id_operacion</code></h4>
          <p>${escapeHtml(consistency.idempotency || "")}</p>
        </div>
        <div class="consistency-item">
          <h4>Sin saga distribuida &amp; Q15 independiente</h4>
          <p>${escapeHtml(consistency.no_distributed_saga || "")} ${escapeHtml(consistency.q15_standalone || "")}</p>
        </div>
      </div>
    `;

    const redisKeys = Array.isArray(arch.redis_keys) ? arch.redis_keys : [];
    els.redisKeysGrid.innerHTML = redisKeys
      .map(
        (k) => `
      <article class="redis-key-card">
        <div class="redis-key-pattern mono">${escapeHtml(k.pattern)}</div>
        <div class="redis-key-meta">
          <span class="badge badge--redis">${escapeHtml(k.type || "STRING JSON")}</span>
          <span class="badge badge--neutral">TTL ${escapeHtml(k.ttl_seconds ?? 300)} s</span>
          <span class="badge badge--lectura">${escapeHtml((k.used_in || []).join(", "))}</span>
        </div>
        <p><strong>Fuente autoritativa:</strong> ${escapeHtml(k.authoritative_source || "MongoDB")}</p>
        <p><strong>Invalidación:</strong> ${escapeHtml(k.invalidation || "seed.py + TTL")}</p>
      </article>
    `
      )
      .join("");

    const collections = Array.isArray(arch.collections) ? arch.collections : [];
    els.collectionsGrid.innerHTML = collections
      .map(
        (col) => `
      <article class="collection-card">
        <div class="collection-card-head">
          <span class="collection-name mono">${escapeHtml(col.name)}</span>
          <span class="badge badge--neutral">${escapeHtml(col.id_strategy || "_id")}</span>
        </div>
        <p class="collection-role">${escapeHtml(col.role || "")}</p>
        <div class="field-chips">
          ${(col.key_fields || [])
            .map((field) => `<span class="field-chip">${escapeHtml(field)}</span>`)
            .join("")}
        </div>
        <div class="collection-footer">
          <div><strong>Relaciones:</strong> ${escapeHtml((col.relations || []).join(" · "))}</div>
          <div><strong>Índices:</strong> <span class="mono">${escapeHtml((col.indexes || []).join(" | "))}</span></div>
        </div>
      </article>
    `
      )
      .join("");

    const alts = Array.isArray(arch.rejected_alternatives) ? arch.rejected_alternatives : [];
    els.alternativesGrid.innerHTML = alts
      .map(
        (alt) => `
      <article class="alt-card">
        <h4>${escapeHtml(alt.alternative)}</h4>
        <p>${escapeHtml(alt.reason)}</p>
      </article>
    `
      )
      .join("");

    els.archLoading.classList.add("is-hidden");
    els.archContent.classList.remove("is-hidden");
  }

  async function loadQueriesCatalog() {
    try {
      const { ok, data } = await fetchJson("/api/queries");
      if (!ok || !data) {
        throw new Error("No se pudo cargar /api/queries");
      }
      const rawList = Array.isArray(data.queries) ? data.queries : Object.values(data.queries || {});
      state.queries = rawList.map(normalizeCatalogItem);
      const total = data.total ?? state.queries.length;
      els.queriesCountBadge.textContent = String(total);
      els.sidebarTotalLabel.textContent = `${total} registradas`;

      renderQueriesList();
      if (state.queries.length > 0 && !state.selectedQueryId) {
        selectQuery(state.queries[0].id);
      }
    } catch (err) {
      els.queriesList.innerHTML = `<div class="alert-banner alert-banner--error">Error al cargar el catálogo: ${escapeHtml(err.message)}</div>`;
    }
  }

  function typeBadgeClass(type) {
    const lower = String(type || "").toLowerCase();
    if (lower.includes("agreg")) return "badge--agregacion";
    if (lower.includes("serv")) return "badge--servicio";
    return "badge--lectura";
  }

  function engineBadgesHtml(engine) {
    const str = String(engine || "MongoDB");
    const hasRedis = str.toLowerCase().includes("redis");
    return `
      <span class="badge badge--mongo">MongoDB</span>
      ${hasRedis ? '<span class="badge badge--redis">+ Redis</span>' : ""}
    `;
  }

  function statusBadgeHtml(implemented) {
    return implemented
      ? '<span class="badge badge--ready">Base lista</span>'
      : '<span class="badge badge--pending">Pendiente Fase 3</span>';
  }

  function renderQueriesList() {
    const filtered = state.queries.filter((q) => {
      if (state.activeFilter === "all") return true;
      return String(q.type).toLowerCase() === state.activeFilter.toLowerCase();
    });

    if (filtered.length === 0) {
      els.queriesList.innerHTML = `<div class="empty-workbench">No hay consultas para el filtro seleccionado.</div>`;
      return;
    }

    els.queriesList.innerHTML = filtered
      .map((q) => {
        const selectedClass = q.id === state.selectedQueryId ? "is-selected" : "";
        return `
        <button type="button" class="query-item-btn ${selectedClass}" data-query-id="${escapeHtml(q.id)}">
          <div class="query-item-top">
            <span class="query-code">${escapeHtml(q.code)}</span>
            <span class="query-item-title">${escapeHtml(q.title)}</span>
          </div>
          <div class="badge-group">
            <span class="badge ${typeBadgeClass(q.type)}">${escapeHtml(q.type)}</span>
            ${engineBadgesHtml(q.engine)}
            ${statusBadgeHtml(q.implemented)}
          </div>
        </button>
      `;
      })
      .join("");
  }

  function getSelectedQuery() {
    return state.queries.find((q) => q.id === state.selectedQueryId) || null;
  }

  function selectQuery(queryId) {
    state.selectedQueryId = queryId;
    renderQueriesList();

    const q = getSelectedQuery();
    if (!q) return;

    els.queryEmptyState.classList.add("is-hidden");
    els.queryDetailPanel.classList.remove("is-hidden");

    els.detailCode.textContent = q.code;
    els.detailTitle.textContent = q.title;
    els.detailEndpointLine.textContent = `${q.method} ${q.endpoint}`;
    els.detailBadges.innerHTML = `
      <span class="badge ${typeBadgeClass(q.type)}">${escapeHtml(q.type)}</span>
      ${engineBadgesHtml(q.engine)}
      ${statusBadgeHtml(q.implemented)}
    `;
    els.detailDescription.textContent = q.description;
    els.detailStrategy.textContent = q.strategy;
    els.paramsHint.textContent = q.spec.paramsHint || "Configuración de parámetros";

    renderQueryForm(q);
    resetResultArea();
  }

  function resetResultArea() {
    els.resultStatusBadge.className = "badge badge--neutral";
    els.resultStatusBadge.textContent = "Sin ejecutar";
    els.resultArea.innerHTML = `
      <p class="result-placeholder">
        Presioná <strong>Probar llamada al endpoint</strong> para probar la consulta o verificar su estado en Fase 3.
      </p>
    `;
  }

  function renderQueryForm(q) {
    const spec = q.spec || {};
    if (spec.customKind === "q13") {
      renderQ13Form();
      return;
    }
    if (spec.customKind === "q14") {
      renderQ14Form();
      return;
    }
    if (spec.customKind === "q15") {
      renderQ15Form();
      return;
    }

    const fields = Array.isArray(spec.fields) ? spec.fields : [];
    if (fields.length === 0) {
      els.paramsForm.innerHTML = `
        <div class="info-note">
          <strong>Consulta sin parámetros obligatorios.</strong><br />
          ${escapeHtml(spec.noParamsNote || "No requiere parámetros de entrada.")}
        </div>
      `;
      return;
    }

    els.paramsForm.innerHTML = `
      <div class="form-grid">
        ${fields
          .map(
            (f) => `
          <div class="form-field form-field--full">
            <label for="param-${escapeHtml(f.name)}">${escapeHtml(f.label)} (<code>${escapeHtml(f.name)}</code>)</label>
            <input
              id="param-${escapeHtml(f.name)}"
              name="${escapeHtml(f.name)}"
              type="text"
              value="${escapeHtml(f.defaultValue || "")}"
              placeholder="${escapeHtml(f.placeholder || "")}"
              ${f.required ? "required" : ""}
            />
            ${f.help ? `<span class="field-help">${escapeHtml(f.help)}</span>` : ""}
            ${
              Array.isArray(f.samples)
                ? `<div class="sample-chips">
                    ${f.samples
                      .map(
                        (s) =>
                          `<button type="button" class="sample-chip" data-fill-input="param-${escapeHtml(f.name)}" data-fill-value="${escapeHtml(s)}">${escapeHtml(s)}</button>`
                      )
                      .join("")}
                  </div>`
                : ""
            }
          </div>
        `
          )
          .join("")}
      </div>
    `;
  }

  function renderQ13Form() {
    const mode = state.q13Mode;
    const switcher = `
      <div class="subtabs" role="tablist" aria-label="Operaciones ABM de Q13">
        <button type="button" class="subtab-btn ${mode === "alta" ? "is-active" : ""}" data-q13-mode="alta">Alta (accion: alta)</button>
        <button type="button" class="subtab-btn ${mode === "modificacion" ? "is-active" : ""}" data-q13-mode="modificacion">Modificación (accion: modificacion)</button>
        <button type="button" class="subtab-btn ${mode === "baja" ? "is-active" : ""}" data-q13-mode="baja">Baja lógica (accion: baja)</button>
      </div>
    `;

    let fieldsHtml = "";
    if (mode === "alta") {
      fieldsHtml = `
        <div class="form-grid">
          <div class="form-field">
            <label for="q13-nombre">Nombre *</label>
            <input id="q13-nombre" name="nombre" type="text" placeholder="Ej. Valentina" value="Valentina" />
          </div>
          <div class="form-field">
            <label for="q13-apellido">Apellido *</label>
            <input id="q13-apellido" name="apellido" type="text" placeholder="Ej. Sosa" value="Sosa" />
          </div>
          <div class="form-field">
            <label for="q13-dni">DNI único *</label>
            <input id="q13-dni" name="dni" type="text" placeholder="Ej. 38456123" value="38456123" />
          </div>
          <div class="form-field">
            <label for="q13-email">Email</label>
            <input id="q13-email" name="email" type="email" placeholder="valentina@mail.com" value="valentina.sosa@mail.com" />
          </div>
          <div class="form-field">
            <label for="q13-telefono">Teléfono</label>
            <input id="q13-telefono" name="telefono" type="text" placeholder="1155001122" value="1155001122" />
          </div>
          <div class="form-field">
            <label for="q13-ciudad">Ciudad *</label>
            <input id="q13-ciudad" name="ciudad" type="text" placeholder="Buenos Aires" value="Buenos Aires" />
          </div>
          <div class="form-field">
            <label for="q13-provincia">Provincia *</label>
            <input id="q13-provincia" name="provincia" type="text" placeholder="Buenos Aires" value="Buenos Aires" />
          </div>
          <div class="form-field">
            <label for="q13-obra-social">Obra social *</label>
            <select id="q13-obra-social" name="obra_social">
              <option value="OSDE">OSDE</option>
              <option value="Swiss Medical">Swiss Medical</option>
              <option value="PAMI">PAMI</option>
              <option value="IOMA">IOMA</option>
              <option value="Galeno">Galeno</option>
              <option value="Sin cobertura">Sin cobertura</option>
            </select>
          </div>
          <div class="form-field form-field--full">
            <label for="q13-nro-afiliado">N° de afiliado</label>
            <input id="q13-nro-afiliado" name="nro_afiliado" type="text" placeholder="Ej. OS-998877 (null si Sin cobertura)" value="OS-998877" />
          </div>
        </div>
      `;
    } else if (mode === "modificacion") {
      fieldsHtml = `
        <div class="info-note">
          <strong>Regla Q13:</strong> Solo se permite modificar <code>email</code>, <code>telefono</code>,
          <code>obra_social</code> y <code>nro_afiliado</code>. El <code>dni</code>, <code>ciudad</code> y <code>provincia</code> no son modificables.
        </div>
        <div class="form-grid">
          <div class="form-field form-field--full">
            <label for="q13-id-cliente">ID de cliente *</label>
            <input id="q13-id-cliente" name="id_cliente" type="text" value="C001" placeholder="Ej. C001" />
          </div>
          <div class="form-field">
            <label for="q13-email">Email</label>
            <input id="q13-email" name="email" type="email" value="lucia.actualizado@gmail.com" />
          </div>
          <div class="form-field">
            <label for="q13-telefono">Teléfono</label>
            <input id="q13-telefono" name="telefono" type="text" value="1145119999" />
          </div>
          <div class="form-field">
            <label for="q13-obra-social">Obra social</label>
            <select id="q13-obra-social" name="obra_social">
              <option value="OSDE">OSDE</option>
              <option value="Swiss Medical">Swiss Medical</option>
              <option value="PAMI">PAMI</option>
              <option value="IOMA">IOMA</option>
              <option value="Galeno">Galeno</option>
              <option value="Sin cobertura">Sin cobertura</option>
            </select>
          </div>
          <div class="form-field">
            <label for="q13-nro-afiliado">N° de afiliado</label>
            <input id="q13-nro-afiliado" name="nro_afiliado" type="text" value="OS-310045" />
          </div>
        </div>
      `;
    } else {
      fieldsHtml = `
        <div class="info-note">
          <strong>Baja lógica:</strong> Actualiza <code>activo = false</code> sin eliminar el documento ni liberar su <code>dni</code> único.
        </div>
        <div class="form-grid">
          <div class="form-field form-field--full">
            <label for="q13-id-cliente">ID de cliente a dar de baja *</label>
            <input id="q13-id-cliente" name="id_cliente" type="text" value="C008" placeholder="Ej. C008" />
          </div>
        </div>
      `;
    }

    els.paramsForm.innerHTML = `${switcher}${fieldsHtml}`;
    syncObraSocialAffiliateField();
  }

  function syncObraSocialAffiliateField() {
    const osSelect = document.getElementById("q13-obra-social");
    const affInput = document.getElementById("q13-nro-afiliado");
    if (!osSelect || !affInput) return;

    const applyRule = () => {
      if (osSelect.value === "Sin cobertura") {
        affInput.value = "";
        affInput.disabled = true;
        affInput.placeholder = "null automático (Sin cobertura)";
      } else {
        affInput.disabled = false;
        affInput.placeholder = "Ej. OS-998877";
      }
    };
    osSelect.addEventListener("change", applyRule);
    applyRule();
  }

  function renderQ14Form() {
    const op = state.q14Op;
    const itemRowsHtml = op.items
      .map(
        (item, idx) => `
      <div class="item-row" data-item-index="${idx}">
        <input
          type="text"
          class="q14-item-prod"
          data-index="${idx}"
          value="${escapeHtml(item.id_producto)}"
          placeholder="ID Producto (ej. PRD001)"
          aria-label="ID de producto ítem ${idx + 1}"
        />
        <input
          type="number"
          min="1"
          step="1"
          class="q14-item-qty"
          data-index="${idx}"
          value="${escapeHtml(item.cantidad)}"
          aria-label="Cantidad ítem ${idx + 1}"
        />
        <button
          type="button"
          class="btn btn-danger-ghost"
          data-remove-item="${idx}"
          ${op.items.length <= 1 ? "disabled" : ""}
        >
          Quitar
        </button>
      </div>
    `
      )
      .join("");

    els.paramsForm.innerHTML = `
      <div class="op-uuid-box">
        <div class="op-uuid-info">
          <span class="op-uuid-label">id_operacion (UUID persistido en localStorage)</span>
          <span class="op-uuid-value mono">${escapeHtml(op.id_operacion)}</span>
        </div>
        <div class="header-actions">
          <button type="button" id="btn-q14-copy-uuid" class="btn btn-ghost">Copiar UUID</button>
          <button type="button" id="btn-q14-new-uuid" class="btn btn-secondary">Nuevo pedido (nuevo UUID)</button>
        </div>
      </div>

      <div class="form-grid">
        <div class="form-field">
          <label for="q14-id-cliente">ID de cliente *</label>
          <input id="q14-id-cliente" type="text" value="${escapeHtml(op.id_cliente)}" placeholder="Ej. C001" />
        </div>
        <div class="form-field">
          <label for="q14-id-farmaceutico">ID de farmacéutico *</label>
          <input id="q14-id-farmaceutico" type="text" value="${escapeHtml(op.id_farmaceutico)}" placeholder="Ej. F001 (sucursal Farmacia)" />
        </div>
        <div class="form-field">
          <label for="q14-id-receta">ID de receta (opcional)</label>
          <input id="q14-id-receta" type="text" value="${escapeHtml(op.id_receta)}" placeholder="Vacío => Venta libre" />
          <span class="field-help">Obligatoria si algún producto es 'Bajo receta' o 'Bajo receta archivada'.</span>
        </div>
        <div class="form-field">
          <label for="q14-medio-pago">Medio de pago *</label>
          <select id="q14-medio-pago">
            ${["Efectivo", "Débito", "Crédito", "Transferencia", "Obra social"]
              .map(
                (mp) =>
                  `<option value="${escapeHtml(mp)}" ${op.medio_pago === mp ? "selected" : ""}>${escapeHtml(mp)}</option>`
              )
              .join("")}
          </select>
        </div>
      </div>

      <div class="items-box">
        <div class="items-box-head">
          <h4>Ítems del pedido (precio unitario y total se calculan en MongoDB)</h4>
          <button type="button" id="btn-q14-add-item" class="btn btn-ghost">+ Agregar ítem</button>
        </div>
        ${itemRowsHtml}
      </div>

      <div class="info-note">
        <strong>Idempotencia web:</strong> Este UUID se conserva tras recargas de página o reintentos ante timeout.
        Solo generá un nuevo UUID cuando inicies una operación distinta.
      </div>
    `;
  }

  function renderQ15Form() {
    els.paramsForm.innerHTML = `
      <div class="form-grid">
        <div class="form-field form-field--full">
          <label for="param-id_venta">ID de venta (<code>id_venta</code>) *</label>
          <input id="param-id_venta" name="id_venta" type="text" value="V001" placeholder="Ej. V001 o fixture técnico" required />
          <div class="sample-chips">
            <button type="button" class="sample-chip" data-fill-input="param-id_venta" data-fill-value="V001">V001</button>
            <button type="button" class="sample-chip" data-fill-input="param-id_venta" data-fill-value="V900">V900 (fixture)</button>
          </div>
        </div>
      </div>
      <div class="info-note">
        <strong>Precondiciones de Q15 independiente:</strong>
        <ul style="margin: 0.4rem 0 0; padding-left: 1.2rem;">
          <li>Rechaza ventas en estado <code>Pendiente</code> o <code>Anulada</code>.</li>
          <li>Si la venta ya posee <code>stock_aplicado = true</code> (ej. históricas de CSV o ya procesadas por Q14), devuelve las asignaciones sin descontar otra vez.</li>
          <li>Para demostrar descuento independiente, utilizar el fixture técnico con <code>estado = 'Completada'</code>, <code>origen = 'servicio'</code> y <code>stock_aplicado = false</code>.</li>
        </ul>
      </div>
    `;
  }

  function buildRequestPreview(q) {
    const spec = q.spec || {};
    if (spec.customKind === "q13") {
      const mode = state.q13Mode;
      const val = (id) => {
        const el = document.getElementById(id);
        return el ? el.value.trim() : "";
      };
      if (mode === "alta") {
        const os = val("q13-obra-social") || "Sin cobertura";
        const body = {
          accion: "alta",
          nombre: val("q13-nombre"),
          apellido: val("q13-apellido"),
          dni: val("q13-dni"),
          email: val("q13-email") || null,
          telefono: val("q13-telefono") || null,
          ciudad: val("q13-ciudad"),
          provincia: val("q13-provincia"),
          obra_social: os,
          nro_afiliado: os === "Sin cobertura" ? null : val("q13-nro-afiliado") || null,
        };
        return { method: "POST", url: q.endpoint, body };
      }
      if (mode === "modificacion") {
        const idCliente = val("q13-id-cliente");
        const os = val("q13-obra-social");
        const body = {
          accion: "modificacion",
          id_cliente: idCliente,
          email: val("q13-email") || null,
          telefono: val("q13-telefono") || null,
          obra_social: os,
          nro_afiliado: os === "Sin cobertura" ? null : val("q13-nro-afiliado") || null,
        };
        return { method: "POST", url: q.endpoint, body };
      }
      const idCliente = val("q13-id-cliente");
      return {
        method: "POST",
        url: q.endpoint,
        body: { accion: "baja", id_cliente: idCliente },
      };
    }

    if (spec.customKind === "q14") {
      const op = state.q14Op;
      const body = {
        id_operacion: op.id_operacion,
        id_cliente: op.id_cliente.trim(),
        id_farmaceutico: op.id_farmaceutico.trim(),
        id_receta: op.id_receta.trim() || null,
        medio_pago: op.medio_pago,
        items: op.items.map((it) => ({
          id_producto: String(it.id_producto || "").trim(),
          cantidad: Math.max(1, parseInt(it.cantidad, 10) || 1),
        })),
      };
      return { method: "POST", url: q.endpoint, body };
    }

    if (spec.customKind === "q15") {
      const idVenta = (document.getElementById("param-id_venta")?.value || "").trim();
      return {
        method: "POST",
        url: q.endpoint,
        body: { id_venta: idVenta },
      };
    }

    const fields = Array.isArray(spec.fields) ? spec.fields : [];
    const params = new URLSearchParams();
    for (const f of fields) {
      const inputEl = document.getElementById(`param-${f.name}`);
      const val = inputEl ? inputEl.value.trim() : "";
      if (val) params.set(f.name, val);
    }
    const qs = params.toString();
    return {
      method: "GET",
      url: qs ? `${q.endpoint}?${qs}` : q.endpoint,
      body: null,
    };
  }

  async function executeSelectedQuery(forceCatalogInspect = false) {
    const q = getSelectedQuery();
    if (!q) return;

    const preview = buildRequestPreview(q);
    const shouldInspectCatalog = forceCatalogInspect || !q.implemented;
    const targetMethod = shouldInspectCatalog ? "GET" : preview.method;
    const targetUrl = shouldInspectCatalog ? `/api/queries/${encodeURIComponent(q.id)}?meta=true` : preview.url;

    els.btnTestEndpoint.disabled = true;
    els.btnInspectCatalog.disabled = true;
    els.resultStatusBadge.className = "badge badge--neutral";
    els.resultStatusBadge.textContent = "Ejecutando…";

    try {
      const fetchOpts = { method: targetMethod };
      if (!shouldInspectCatalog && preview.body !== null && targetMethod !== "GET") {
        fetchOpts.headers = { "Content-Type": "application/json" };
        fetchOpts.body = JSON.stringify(preview.body);
      }

      const { status, ok, data } = await fetchJson(targetUrl, fetchOpts);
      renderExecutionResult({
        status,
        ok,
        data,
        calledMethod: targetMethod,
        calledUrl: targetUrl,
        preview,
        wasPendingFallback: !forceCatalogInspect && !q.implemented,
      });
    } catch (err) {
      els.resultStatusBadge.className = "badge badge--error";
      els.resultStatusBadge.textContent = "Error de red";
      els.resultArea.innerHTML = `
        <div class="error-card">
          <span class="error-card-code">NETWORK_ERROR</span>
          <p>No se pudo contactar al backend: ${escapeHtml(err.message)}</p>
        </div>
      `;
    } finally {
      els.btnTestEndpoint.disabled = false;
      els.btnInspectCatalog.disabled = false;
    }
  }

  function renderSmartDataBlock(data) {
    const rows = Array.isArray(data)
      ? data
      : data && Array.isArray(data.results)
      ? data.results
      : data && Array.isArray(data.items)
      ? data.items
      : null;

    if (rows && rows.length > 0 && typeof rows[0] === "object" && rows[0] !== null) {
      const cols = Array.from(
        rows.reduce((set, row) => {
          Object.keys(row).forEach((k) => set.add(k));
          return set;
        }, new Set())
      );

      const headerHtml = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
      const bodyHtml = rows
        .map(
          (row) =>
            `<tr>${cols
              .map((c) => {
                const cell = row[c];
                const formatted =
                  cell !== null && typeof cell === "object" ? JSON.stringify(cell) : String(cell ?? "null");
                return `<td class="mono">${escapeHtml(formatted)}</td>`;
              })
              .join("")}</tr>`
        )
        .join("");

      return `
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr>${headerHtml}</tr></thead>
            <tbody>${bodyHtml}</tbody>
          </table>
        </div>
      `;
    }

    return "";
  }

  function renderExecutionResult({ status, ok, data, calledMethod, calledUrl, preview, wasPendingFallback }) {
    const callSummary = `<div class="result-call-line">${escapeHtml(calledMethod)} ${escapeHtml(calledUrl)}</div>`;
    const previewJsonHtml =
      preview.body !== null
        ? `<details class="json-details" open>
            <summary>Vista previa del payload preparado (${escapeHtml(preview.method)} ${escapeHtml(preview.url)})</summary>
            <pre class="json-pre">${escapeHtml(JSON.stringify(preview.body, null, 2))}</pre>
          </details>`
        : "";

    if (status === 501 || (data && data.status === "pending")) {
      els.resultStatusBadge.className = "badge badge--pending";
      els.resultStatusBadge.textContent = `HTTP ${status} · Pendiente Fase 3`;
      els.resultArea.innerHTML = `
        ${callSummary}
        <div class="pending-card">
          <h4>Consulta registrada · Implementación pendiente de Fase 3</h4>
          <p>${escapeHtml((data && data.message) || "Esta consulta aún no fue implementada en este hito inicial.")}</p>
        </div>
        ${wasPendingFallback ? previewJsonHtml : ""}
        <details class="json-details" ${wasPendingFallback && preview.body === null ? "open" : ""}>
          <summary>Respuesta estructurada del servidor (JSON)</summary>
          <pre class="json-pre">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
        </details>
      `;
      return;
    }

    if (data && data.error) {
      els.resultStatusBadge.className = "badge badge--error";
      els.resultStatusBadge.textContent = `HTTP ${status} · ${data.error.code || "DomainError"}`;
      els.resultArea.innerHTML = `
        ${callSummary}
        <div class="error-card">
          <span class="error-card-code">${escapeHtml(data.error.code || "ERROR")}</span>
          <p>${escapeHtml(data.error.message || "Error de validación de dominio.")}</p>
        </div>
        <details class="json-details" open>
          <summary>Detalle completo del error (JSON)</summary>
          <pre class="json-pre">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
        </details>
      `;
      return;
    }

    if (!ok) {
      els.resultStatusBadge.className = "badge badge--error";
      els.resultStatusBadge.textContent = `HTTP ${status}`;
      els.resultArea.innerHTML = `
        ${callSummary}
        <div class="error-card">
          <span class="error-card-code">HTTP_${escapeHtml(status)}</span>
          <p>${escapeHtml((data && data.detail) || "La solicitud devolvió un estado de error.")}</p>
        </div>
        <pre class="json-pre">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      `;
      return;
    }

    els.resultStatusBadge.className = "badge badge--ready";
    els.resultStatusBadge.textContent = `HTTP ${status} · OK`;
    const tableHtml = renderSmartDataBlock(data);
    els.resultArea.innerHTML = `
      ${callSummary}
      <div class="success-card">Respuesta recibida correctamente desde la API de FarmaRed.</div>
      ${tableHtml}
      <details class="json-details" ${tableHtml ? "" : "open"}>
        <summary>Respuesta JSON completa</summary>
        <pre class="json-pre">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </details>
    `;
  }

  function switchTab(tabName) {
    state.activeTab = tabName;
    els.tabBtns.forEach((btn) => {
      const isSelected = btn.dataset.tab === tabName;
      btn.classList.toggle("is-active", isSelected);
      btn.setAttribute("aria-selected", String(isSelected));
    });

    if (tabName === "architecture") {
      els.panelArch.classList.add("is-active");
      els.panelArch.hidden = false;
      els.panelQueries.classList.remove("is-active");
      els.panelQueries.hidden = true;
    } else {
      els.panelQueries.classList.add("is-active");
      els.panelQueries.hidden = false;
      els.panelArch.classList.remove("is-active");
      els.panelArch.hidden = true;
    }
  }

  function bindEvents() {
    els.btnRefreshHealth.addEventListener("click", refreshHealth);

    els.tabBtns.forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });

    els.filterChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        state.activeFilter = chip.dataset.filter || "all";
        els.filterChips.forEach((c) => c.classList.toggle("is-active", c === chip));
        renderQueriesList();
      });
    });

    els.queriesList.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-query-id]");
      if (!btn) return;
      selectQuery(btn.dataset.queryId);
    });

    els.paramsForm.addEventListener("click", (event) => {
      const sampleBtn = event.target.closest("[data-fill-input]");
      if (sampleBtn) {
        const input = document.getElementById(sampleBtn.dataset.fillInput);
        if (input) input.value = sampleBtn.dataset.fillValue || "";
        return;
      }

      const q13Btn = event.target.closest("[data-q13-mode]");
      if (q13Btn) {
        state.q13Mode = q13Btn.dataset.q13Mode;
        renderQ13Form();
        return;
      }

      if (event.target.id === "btn-q14-new-uuid") {
        state.q14Op.id_operacion = generateUuidV4();
        persistQ14State();
        renderQ14Form();
        return;
      }

      if (event.target.id === "btn-q14-copy-uuid") {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(state.q14Op.id_operacion).catch(() => {});
        }
        event.target.textContent = "¡Copiado!";
        window.setTimeout(() => {
          if (event.target) event.target.textContent = "Copiar UUID";
        }, 1200);
        return;
      }

      if (event.target.id === "btn-q14-add-item") {
        state.q14Op.items.push({ id_producto: "PRD002", cantidad: 1 });
        persistQ14State();
        renderQ14Form();
        return;
      }

      const removeBtn = event.target.closest("[data-remove-item]");
      if (removeBtn && state.q14Op.items.length > 1) {
        const idx = Number(removeBtn.dataset.removeItem);
        state.q14Op.items.splice(idx, 1);
        persistQ14State();
        renderQ14Form();
      }
    });

    els.paramsForm.addEventListener("input", (event) => {
      const target = event.target;
      const q = getSelectedQuery();
      if (!q || q.id !== "q14") return;

      if (target.id === "q14-id-cliente") state.q14Op.id_cliente = target.value;
      else if (target.id === "q14-id-farmaceutico") state.q14Op.id_farmaceutico = target.value;
      else if (target.id === "q14-id-receta") state.q14Op.id_receta = target.value;
      else if (target.id === "q14-medio-pago") state.q14Op.medio_pago = target.value;
      else if (target.classList.contains("q14-item-prod")) {
        const idx = Number(target.dataset.index);
        if (state.q14Op.items[idx]) state.q14Op.items[idx].id_producto = target.value;
      } else if (target.classList.contains("q14-item-qty")) {
        const idx = Number(target.dataset.index);
        if (state.q14Op.items[idx]) state.q14Op.items[idx].cantidad = target.value;
      }
      persistQ14State();
    });

    els.btnTestEndpoint.addEventListener("click", () => executeSelectedQuery(false));
    els.btnInspectCatalog.addEventListener("click", () => executeSelectedQuery(true));
  }

  async function init() {
    cacheElements();
    bindEvents();
    await Promise.all([refreshHealth(), loadArchitecture(), loadQueriesCatalog()]);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
