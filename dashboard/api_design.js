/**
 * SIGEA — ESQUELETO de la API de operaciones de ESTADO.
 *
 * ⚠ ESTO NO ES PRODUCCIÓN. No está conectado a server.js, no se despliega,
 *   no toca estado.json ni bitacora.json reales. Es el PLANO de cómo se
 *   vería la API si existiera, para revisión del Director antes de
 *   construirla de verdad. Ver docs/CONTRATO_API.md (mismo numeral entre
 *   paréntesis en cada endpoint).
 *
 * Alcance: SOLO la familia ESTADO. Las operaciones de ARCHIVOS (extraer
 * gpkg, QA_pendiente/, sesión local, reimporte al central) NO tienen
 * endpoint: siempre las ejecuta un agente local — hoy el plugin QGIS.
 * El patrón es: la API registra el estado; el agente local reacciona
 * (ej. ve una asignación nueva → extrae el gpkg del central).
 *
 * Convenciones del contrato:
 *  - Todas las respuestas: { ok: true, ...datos } o { ok: false, error }.
 *  - Toda mutación registra su evento en bitacora.json (append-only) en la
 *    misma operación — si no se puede escribir la bitácora, la mutación
 *    falla completa (nada de estados a medias).
 *  - REGLA NO SE TOCA: los cuerpos solo llevan metadata de proceso y
 *    conteos agregados. Jamás RUTs, direcciones ni coordenadas
 *    individuales. El backend VALIDA y rechaza payloads que las traigan.
 *  - El backend es el ÚNICO escritor de estado.json/bitacora.json: se
 *    acaban el token público "_t" y las carreras de la Action consolidador.
 */

"use strict";

// Dominio SERVEL (docs/CONTRATO_API.md §3). 8 y 9 no cuentan como avance.
const TIPOS_GEO_DOMINIO = {
  1: "LOCALIDAD", 2: "EXACTO", 3: "CALLE", 4: "NO_GEO",
  5: "PROXIMIDAD", 6: "FUERA_COMUNA", 7: "AUTOGEO",
  8: "RECINTO_NO_GEO", 9: "SIN_TIPO", 10: "MASIVO",
};

/**
 * Definición declarativa de los endpoints de ESTADO.
 * Cada entrada documenta: qué hace, qué recibe, qué devuelve, qué evento
 * de bitácora genera, y qué función del plugin hace lo mismo HOY
 * (trazabilidad hacia el zip sigea_panel.2.1.4.zip).
 */
const API_ESTADO = [

  // ── Lecturas ───────────────────────────────────────────────────────────

  {
    ruta: "GET /api/estado",                                    // (4.1)
    hace: "Estado completo de asignaciones por funcionario, SIN los campos " +
          "internos _t/_r/_b (el token deja de viajar al cliente).",
    recibe: null,
    devuelve: "{ ok, generado, funcionarios: { usuario: asignacion|null } }",
    bitacora: null,
    hoy: "api.estado_online() del plugin + GET /estado.json de server.js",
  },

  {
    ruta: "GET /api/estado/:usuario",                           // (4.1)
    hace: "Asignación activa de UN funcionario, ya normalizada (id, " +
          "unidad_nombre, avance) — lo que hoy normaliza el plugin a mano.",
    recibe: null,
    devuelve: "{ ok, asignacion: {...}|null, generado }",
    bitacora: null,
    hoy: "api.estado_online() — bloque de normalización",
  },

  {
    ruta: "GET /api/historial/:recinto",                        // (4.2)
    hace: "Timeline del recinto: eventos ordenados + resumen (funcionarios, " +
          "n° de avances, duración primer avance → cierre, último QA, mails).",
    recibe: "query opcional: ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD",
    devuelve: "{ ok, recinto, eventos: [...], resumen: {...} }",
    bitacora: null,
    hoy: "pestaña Historial de dashboard/index.html (_renderHistRecintos)",
  },

  {
    ruta: "GET /api/historial/funcionario/:usuario",            // (4.2)
    hace: "Recintos trabajados por el funcionario: tiempo por recinto, " +
          "entregas, observaciones QA recibidas, estado de cada uno.",
    recibe: "query opcional: ?desde&hasta",
    devuelve: "{ ok, usuario, recintos: [{codigo, duracion, avances, ...}] }",
    bitacora: null,
    hoy: "pestaña Historial de dashboard/index.html (_renderHistFuncionarios)",
  },

  {
    ruta: "GET /api/bitacora",                                  // (4.2)
    hace: "Eventos crudos con filtros (lo que hoy hace la pestaña Bitácora " +
          "descargando el archivo completo).",
    recibe: "query: ?tipo&recinto&funcionario&desde&hasta&pagina",
    devuelve: "{ ok, eventos: [...], total }",
    bitacora: null,
    hoy: "dashboard/index.html cargarBitacora() sobre bitacora.json raw",
  },

  // ── Mutaciones ─────────────────────────────────────────────────────────

  {
    ruta: "POST /api/asignar",                                  // (4.3)
    hace: "Registra la asignación de un recinto a un funcionario. NO extrae " +
          "el gpkg: eso lo hace el agente local (plugin) al ver la " +
          "asignación nueva — o el admin desde QGIS como hoy.",
    recibe: "{ usuario, codigo, unidad, comuna, n_electores, " +
            "fecha_estimada?, asignado_por }",
    devuelve: "{ ok, asignacion: {...}, advertencia? } — advertencia si el " +
              "funcionario ya tenía asignación activa (doble asignación " +
              "requiere confirmar=true en el payload, como el doble clic hoy)",
    bitacora: "asignacion { asignado_por }",
    hoy: "admin_dialog._asignar() — incluida la regla de fecha estimada " +
         "(techo(n_electores/100) días hábiles, _calcular_fecha_estimada) " +
         "y la advertencia de doble asignación",
    reglas: [
      "fecha_estimada ausente → la calcula el backend con la regla de hoy",
      "asignacion_id generado por el backend (hoy: timestamp)",
      "avance inicial = 0",
      "si el recinto está 'devuelto_con_avance', responde con " +
      "origen_gpkg:'devuelto' para que el agente local continúe desde " +
      "Devueltos/ (preparar_gpkg_asignacion)",
    ],
  },

  {
    ruta: "POST /api/avance",                                   // (4.6, 4.17)
    hace: "Registra el avance de un recinto y actualiza estado.json EN LA " +
          "MISMA operación — reemplaza el par publicar_avance + Action " +
          "consolidador (adiós carreras de Actions encoladas).",
    recibe: "{ usuario, recinto, conteos: {tipo_geo_id: n}, total }",
    devuelve: "{ ok, confirmados_total, pendientes, pct }",
    bitacora: "avance { <tipo>: n..., total, pct }",
    hoy: "github_report.publicar_avance() + bitacora.evento_avance() + " +
         "consolidador.yml (que esta operación vuelve innecesario)",
    reglas: [
      "tipos 8 y 9 NO cuentan como confirmados (regla de publicar_avance)",
      "tipo fuera del dominio 1-10 → evento alerta_tipo, no se propaga en silencio",
      "payload solo conteos agregados — el backend rechaza cualquier campo " +
      "que parezca dato individual (regla datos sensibles)",
    ],
  },

  {
    ruta: "POST /api/entrega",                                  // (4.7)
    hace: "Registra la entrega final: avance al 100% de lo trabajado, evento " +
          "de bitácora y LIBERACIÓN INMEDIATA del funcionario (ranura a " +
          "null — decisión del Director, Hallazgo 3). La copia física del " +
          "gpkg a QA_pendiente/ la hace el agente local (4.8).",
    recibe: "{ usuario, recinto, conteos, total, origen: 'qgis'|'sige', " +
            "observaciones? }",
    devuelve: "{ ok, liberado: true, pct }",
    bitacora: "entrega { <tipo>: n..., total, pct, origen }",
    hoy: "panel.entregar() + consolidador.yml línea 70 " +
         "(estado['funcionarios'][usuario] = None). El importador SIGE " +
         "(procesar_entrega_sige) usaría este mismo endpoint con origen:'sige'",
    reglas: [
      "libera con null — NO reintroducir estado_flujo/'en_qa' (flag huérfano " +
      "que admin_dialog e importador_sige aún escriben; ver contrato 4.7)",
      "el seguimiento QA es por archivo en QA_pendiente/ + evento entrega",
      "dispara notificación de mail tipo 'entrega' (4.16) con copia al supervisor",
    ],
  },

  {
    ruta: "POST /api/qa",                                       // (4.9)
    hace: "Registra el veredicto de QA de un recinto (la revisión visual del " +
          "gpkg sigue siendo local, en QGIS; aquí solo entra el resultado).",
    recibe: "{ recinto, resultado: 'aprobado'|'observado', comentario?, " +
            "revisor }",
    devuelve: "{ ok }",
    bitacora: "qa { resultado, comentario }",
    hoy: "admin_dialog._marcar_qa() → bitacora.evento_qa(). El reimporte al " +
         "central que hoy cuelga del 'aprobar' NO entra aquí: es ARCHIVOS y " +
         "está NEUTRALIZADO (PIEZA4_HABILITADA=False)",
    reglas: [
      "resultado 'observado' exige comentario no vacío (hoy la UI lo pide)",
      "si el último reporte del funcionario trae tipos fuera de dominio, " +
      "responder con advertencia + evento alerta_tipo (hoy: " +
      "_detectar_tipos_invalidos + evento_alerta_tipo)",
    ],
  },

  {
    ruta: "POST /api/cierre",                                   // (4.12)
    hace: "Cierre formal de un recinto. Dos variantes: con asignación (solo " +
          "evento) o sin asignar (agrega _cerrado_{codigo} a estado.json, " +
          "ej. recintos ya corregidos en Enterprise).",
    recibe: "{ recinto, cerrado_por, sin_asignar?: bool, motivo?, unidad? }",
    devuelve: "{ ok }",
    bitacora: "cierre { cerrado_por }",
    hoy: "admin_dialog._cerrar_recinto() / _cerrar_sin_asignar() y " +
         "cerrarRecinto() de la pestaña Admin del dashboard (que ya escribe " +
         "a GitHub directo — sería el primer cliente en migrar)",
  },

  {
    ruta: "POST /api/devolucion",                               // (4.13)
    hace: "Registra la devolución de una asignación. Con avance: recinto " +
          "queda 'devuelto_con_avance' (reasignable, se continúa desde " +
          "Devueltos/). Sin avance: ranura a null (vuelve a pendiente). El " +
          "movimiento de archivos (Devueltos/, _historico/) es del agente local.",
    recibe: "{ usuario, recinto, conservar_avance: bool, motivo? }",
    devuelve: "{ ok, estado_recinto: 'pendiente'|'devuelto' }",
    bitacora: "devolucion { motivo, conservo_avance }",
    hoy: "devolver_dialog.ejecutar_devolucion() + " +
         "_actualizar_estado_devolucion(). NOTA: 'devuelto_con_avance' es el " +
         "único flag de flujo que SÍ se lee hoy (listar_recintos_central) — " +
         "se conserva en el contrato",
  },

  {
    ruta: "POST /api/mail",                                     // (4.16)
    hace: "Notificación por correo. ÚNICO endpoint que ya existe hoy " +
          "(POST /mail en server.js, migrando a Resend). Se renombra bajo " +
          "/api/ por consistencia, manteniendo el actual como alias.",
    recibe: "{ destinatario, tipo: 'asignacion'|'entrega'|'qa_ok'|'qa_obs'|" +
            "'cierre', recinto, funcionario? }",
    devuelve: "{ ok, enviado, simulado, nota }",
    bitacora: "mail { destinatario, asunto, enviado, nota }",
    hoy: "dashboard/server.js POST /mail + mailer.enviar_mail() del plugin",
    reglas: [
      "sin RESEND_API_KEY → simulación (enviado:false), nunca error duro",
      "todo fallo registra su causa en 'nota' — cero fallos silenciosos",
      "cuerpo del mail: solo metadata de proceso",
    ],
  },

  // ── Futuro habilitante (requiere que el agente local publique catálogo) ─

  {
    ruta: "GET /api/recintos",                                  // (4.14)
    hace: "Catálogo de recintos con estado (pendiente/asignado/devuelto/" +
          "cerrado), electores y sin-revisar. HOY es imposible como endpoint " +
          "puro: la lista vive en central.gpkg (ARCHIVOS). Entra al contrato " +
          "condicionado a que el agente local publique recintos.json " +
          "(conteos agregados, sin datos sensibles) tras cada cambio.",
    recibe: "query: ?comuna&estado&orden",
    devuelve: "{ ok, recintos: [{codigo, nombre, comuna, n_electores, " +
              "n_sin_revisar, estado_recinto, asignado_a}] }",
    bitacora: null,
    hoy: "admin_archivos.listar_recintos_central() — SOLO dentro de QGIS",
  },
];

/**
 * Esqueleto del router. NO se registra en server.js — es ilustrativo.
 * Si el Director aprueba el contrato, la construcción real reemplaza cada
 * 501 por su implementación, endpoint por endpoint, empezando por el que
 * se decida (recomendación en el reporte: POST /api/avance).
 */
function routerEsqueleto(req, res) {
  const spec = API_ESTADO.find(e => {
    const [metodo, patron] = e.ruta.split(" ");
    return req.method === metodo &&
           new RegExp("^" + patron.replace(/:[^/]+/g, "[^/]+") + "$")
             .test((req.url || "").split("?")[0]);
  });
  res.writeHead(spec ? 501 : 404, { "Content-Type": "application/json" });
  res.end(JSON.stringify(spec
    ? { ok: false, error: "No implementado — esqueleto de diseño", ruta: spec.ruta }
    : { ok: false, error: "Ruta fuera del contrato" }));
}

module.exports = { API_ESTADO, TIPOS_GEO_DOMINIO, routerEsqueleto };
