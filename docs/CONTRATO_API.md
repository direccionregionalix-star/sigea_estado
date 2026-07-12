# CONTRATO DE OPERACIONES SIGEA

**Documento de diseño — rama `claude/sigea-api-contract` — NO mergear sin revisión del Director.**

Fecha: 2026-07-10 · Fuente: código real del zip `sigea_panel.2.1.4.zip` (no `plugin_src/`, eliminada),
`dashboard/server.js`, `dashboard/index.html` y `.github/workflows/consolidador.yml`.

---

## 1. Para qué sirve este documento

Hoy SIGEA funciona, pero su lógica vive **repartida dentro del plugin QGIS**. El backend
en Railway solo hace tres cosas: servir el dashboard, entregar `estado.json` sin caché y
recibir `POST /mail`. Todo lo demás —asignar, entregar, QA, cerrar, devolver— son funciones
de Python dentro del plugin que escriben directo a GitHub.

Eso funciona, pero tiene un costo: **no hay una interfaz que se pueda explicar, probar o
reutilizar**. Cualquier software nuevo tendría que copiar el interior del plugin.

Este documento define el **contrato**: la lista completa de operaciones del sistema, qué
necesita cada una, qué produce, y —lo más importante— cuáles pueden vivir en un servidor
central y cuáles jamás podrán, porque tocan archivos en el disco de una máquina concreta.

## 2. La regla que manda: ESTADO vs ARCHIVOS

Un navegador o un servidor remoto **no puede tocar los archivos de OneDrive ni el
central.gpkg**. Solo un programa corriendo en la máquina que ve esos archivos puede
copiarlos, extraerlos o respaldarlos. De ahí las dos familias:

| Familia | Qué toca | Dónde puede vivir | Quién la hace hoy |
|---|---|---|---|
| **ESTADO** | Solo `estado.json` y `bitacora.json` (metadata y conteos; jamás RUTs, direcciones o coordenadas individuales) | Backend Railway — cualquier cliente puede llamarla: plugin, dashboard, software futuro | Plugin (vía API GitHub) + dashboard + Action consolidador |
| **ARCHIVOS** | `central.gpkg`, `funcionarios/{usuario}/R*.gpkg`, `QA_pendiente/`, `Devueltos/`, copias locales | **Siempre** un agente local (hoy: el plugin QGIS; mañana quizás un agente ligero) | Plugin QGIS |

El software nuevo podrá hacer **todo** lo de ESTADO. Lo de ARCHIVOS seguirá necesitando un
componente local, coordinado por el estado (ej.: la API registra una asignación; el agente
local ve la asignación nueva y extrae el gpkg).

## 3. Los datos del sistema

- **`estado.json`** (GitHub, público): quién tiene qué recinto. Una entrada por funcionario
  (o `null` si está libre) con `codigo`, `unidad`, `comuna`, `n_electores`, `fecha_estimada`,
  `dias_restantes`, `avance`, `herramienta`, lista `asignaciones`. Entradas `_cerrado_{codigo}`
  para cierres sin asignación. Metadata `_t` (token de escritura ofuscado), `_r` (repo destino),
  `_b` (rama), `_mail` (URL del servidor de correo). **Regla NO SE TOCA:** el destino sale
  siempre de `_r`, nunca hardcodeado.
- **`bitacora.json`** (GitHub, público): historial append-only. Eventos `asignacion`, `avance`,
  `entrega`, `qa`, `cierre`, `devolucion`, `mail`, `alerta_tipo`, cada uno con `ts`, `recinto`,
  `funcionario` y `detalle` (solo conteos y metadata).
- **`qgis/{usuario}.json` y `sige/{usuario}.json`** (GitHub): último reporte de avance por
  funcionario (conteos por tipo geo, totales, pct).
- **`central.gpkg`** (OneDrive `dev_007/`): la fuente de verdad geográfica, 282 recintos.
  Columna de geometría `"geometry"` (origen ArcGIS Enterprise) — **nunca asumir "geom"**.
- **Carpetas OneDrive**: `funcionarios/{usuario}/R{codigo}.gpkg` (copia de trabajo),
  `QA_pendiente/`, `QA_cerrado/`, `Devueltos/`, `_historico_central/`.

**Dominio tipo geo (SERVEL):** LOCALIDAD/RURAL=1, EXACTO=2, CALLE=3, NO GEO=4. El plugin
maneja además 5–10 (PROXIMIDAD, FUERA_COMUNA, AUTOGEO, RECINTO_NO_GEO, SIN_TIPO, MASIVO);
8 y 9 **no cuentan como avance**. En entregas SIGE solo 1–4 son válidos. Todo tipo fuera de
dominio se **alerta** (evento `alerta_tipo`), nunca se propaga en silencio.

---

## 4. Las operaciones, una por una

### 4.1 Consultar estado
- **Familia:** ESTADO (solo lectura)
- **Hoy:** `api.estado_online()` en el plugin; `GET /estado.json` del server.js (proxy
  anti-caché sobre GitHub raw); el dashboard lo lee al cargar.
- **Lee:** `estado.json`. **Escribe:** nada.
- **Entrada:** ninguna (el plugin filtra por su usuario). **Salida:** asignaciones por
  funcionario + `generado`.
- **Reglas:** el plugin normaliza campos (`id`, `unidad_nombre`); si hay varias asignaciones
  el funcionario elige una.

### 4.2 Consultar historial
- **Familia:** ESTADO (solo lectura)
- **Hoy:** el dashboard lee `bitacora.json` completo desde GitHub raw (pestañas Bitácora,
  Correos y la nueva Historial, que agrupa por recinto/funcionario y calcula duración
  primer avance → cierre).
- **Lee:** `bitacora.json`. **Escribe:** nada.
- **Entrada:** filtros (tipo, recinto, funcionario, rango de fechas). **Salida:** eventos o
  resúmenes agrupados.

### 4.3 Asignar recinto a funcionario
- **Familia:** **MIXTA** — se separa en dos:
  - Registrar la asignación (ESTADO).
  - Extraer/preparar el gpkg del funcionario (ARCHIVOS, ver 4.4).
- **Hoy:** `admin_dialog._asignar()` (Modo Admin del plugin) hace ambas cosas seguidas.
- **Lee:** `estado.json`, lista de recintos del central (ver 4.14). **Escribe:** `estado.json`
  (entrada del funcionario) + evento `asignacion` en bitácora.
- **Entrada:** usuario, código de recinto, unidad, comuna, n_electores, fecha estimada.
  **Salida:** asignación creada con `asignacion_id` (timestamp) y `avance: 0`.
- **Reglas:**
  - Fecha estimada propuesta: `techo(n_electores / 100)` días **hábiles** (lun–vie).
  - Si el funcionario ya tiene asignación activa no liberada, se advierte y se exige
    confirmación explícita (doble asignación permitida pero consciente).
  - Si el recinto fue devuelto **con avance**, la preparación del gpkg continúa desde
    `Devueltos/` en vez de extraer de nuevo (`preparar_gpkg_asignacion`).
  - Evento bitácora: `asignacion` con `asignado_por`.

### 4.4 Extraer gpkg del central
- **Familia:** ARCHIVOS
- **Hoy:** `admin_archivos.extraer_recinto_para_funcionario()` + `_gpkg_vacio()`
  (desde 2.1.4 con GDAL/OGR: RTree, `gpkg_extensions`, SRS estándar → legible en ArcGIS Pro).
- **Lee:** `central.gpkg`. **Escribe:** `funcionarios/{usuario}/R{codigo}.gpkg` (OneDrive).
- **Entrada:** código de recinto, usuario. **Salida:** gpkg con los electores del recinto.
- **Reglas NO SE TOCA:**
  - `fid_central` (INTEGER) como primer campo — el reimporte depende de él.
  - Columna de geometría resuelta dinámicamente (`_col_geom_central`), nunca "geom".
  - Mismos nombres y tipos de columna que el central.
  - Verificación de conteo 1:1 y copia atómica con SHA-256 antes de dejar el archivo.

### 4.5 Sesión local de trabajo (cargar / pausar / respaldar)
- **Familia:** ARCHIVOS
- **Hoy:** `sesion.abrir_sesion()` (copia OneDrive → carpeta local, QGIS nunca abre el
  archivo en OneDrive), `sesion.sincronizar()` (local → OneDrive, atómico + SHA-256 +
  respaldo rotado), `sesion.respaldar_local()`, `sesion.limpiar_local()`.
- **Reglas NO SE TOCA (caso jmedina):** `limpiar_local()` **siempre** respalda en
  `_historico/` (últimos 5) **antes** de borrar la copia de trabajo. `sincronizar()` respalda
  el archivo previo de OneDrive en `_respaldos/` (últimos 3) antes de pisarlo. Verificación
  por manifest `.listo` (bytes + SHA-256) antes de confiar en un archivo de OneDrive.

### 4.6 Registrar avance
- **Familia:** ESTADO
- **Hoy:** `panel.registrar_avance()` → `github_report.publicar_avance()` escribe
  `qgis/{usuario}.json`; `bitacora.evento_avance()` agrega el evento; la **Action
  consolidador** (GitHub) copia `confirmados_total` al campo `avance` de `estado.json`.
- **Lee:** capa activa (conteos — eso es local, pero el dato que viaja son solo conteos).
  **Escribe:** `qgis/{usuario}.json`, evento `avance`, y (vía Action) `estado.json`.
- **Entrada:** usuario, recinto, conteos por tipo geo, total. **Salida:** pct calculado.
- **Reglas:**
  - Tipos 8 (RECINTO_NO_GEO) y 9 (SIN_TIPO) **no** cuentan como confirmados.
  - El reporte lleva solo conteos agregados — jamás datos por elector.
  - La consolidación actual es **frágil**: Actions encoladas pueden morir en rebase
    (deuda conocida; el siguiente avance reconsolida).

### 4.7 Entregar recinto (funcionario)
- **Familia:** **MIXTA**
  - Registrar la entrega y liberar al funcionario (ESTADO).
  - Copiar el gpkg a `QA_pendiente/` (ARCHIVOS, ver 4.8).
- **Hoy:** `panel.entregar()` publica el avance final con origen `"Plugin QGIS entrega"` +
  `bitacora.evento_entrega()`; la Action consolidador detecta `'entrega' in origen` y libera:
  `estado['funcionarios'][usuario] = None` (decisión del Director: entregar libera de
  inmediato; el seguimiento QA es por archivo físico + evento de bitácora, no por flag).
- **Entrada:** usuario, recinto, conteos finales. **Salida:** funcionario liberado, evento
  `entrega` con conteos por tipo y pct.
- **Nota de deuda:** el Modo Admin (`_entregar_a_qa`) y el importador SIGE todavía escriben
  `liberado: true` + `estado_flujo: "en_qa"` en `estado.json`. Desde 2.1.4 **nadie lee**
  `estado_flujo` (la rama muerta se eliminó de `api.py`). Al construir la API, la operación
  "entregar" debe liberar con `None` y **no** reintroducir flags pegados a la persona.

### 4.8 Mover entrega a QA_pendiente
- **Familia:** ARCHIVOS
- **Hoy:** `admin_archivos.entregar_a_qa()` (lo dispara el Modo Admin).
- **Lee:** `funcionarios/{usuario}/R{codigo}.gpkg`. **Escribe:** `QA_pendiente/R{codigo}.gpkg`.
- **Reglas:** si ya había un archivo en QA, se respalda antes de sobrescribir; copia
  atómica + SHA-256; si falla, el trabajo del funcionario queda intacto.

### 4.9 Registrar resultado de QA
- **Familia:** ESTADO
- **Hoy:** `admin_dialog._marcar_qa()` → `bitacora.evento_qa()`. La revisión visual del
  gpkg (abrirlo en QGIS) es ARCHIVOS, pero **registrar el veredicto** es puro estado.
- **Lee:** `bitacora.json`, reporte del funcionario. **Escribe:** evento `qa`
  `{resultado: aprobado|observado, comentario}`.
- **Entrada:** recinto, resultado, comentario, revisor. **Salida:** evento registrado.
- **Reglas:** antes de aprobar se comparan los tipos geo del reporte contra el dominio;
  cualquier tipo desconocido genera evento `alerta_tipo` y advertencia visible. Si el QA
  aprueba y el reimporte está habilitado, sigue 4.10 — hoy **neutralizado**.

### 4.10 Reimportar al central — **NEUTRALIZADA**
- **Familia:** ARCHIVOS
- **Hoy:** `admin_archivos.reimportar_al_central()`, bloqueada por
  `settings.PIEZA4_HABILITADA = False`. Solo el Director la habilita, después de la prueba
  de 6 pasos.
- **Lee:** `QA_pendiente/R{codigo}.gpkg`. **Escribe:** `central.gpkg` (UPDATE por
  `fid_central`), respaldo previo en `_historico_central/`.
- **Reglas:** respaldo del central obligatorio antes de escribir; **rechaza** gpkg sin
  `fid_central`; si el conteo actualizado no cuadra 1:1, rollback total; timeout 30 s por
  bloqueos. Tras reimporte exitoso, el gpkg se mueve a `QA_cerrado/` (4.11).

### 4.11 Mover QA a cerrado
- **Familia:** ARCHIVOS
- **Hoy:** `admin_archivos.mover_qa_a_cerrado()` — mueve `QA_pendiente/R{codigo}.gpkg`
  a `QA_cerrado/R{codigo}_{timestamp}.gpkg`.

### 4.12 Cerrar recinto
- **Familia:** ESTADO
- **Hoy, dos variantes:**
  - **Con asignación** (`_cerrar_recinto`): solo registra evento `cierre` en bitácora.
  - **Sin asignar** (`_cerrar_sin_asignar`, y también la pestaña Admin del dashboard):
    agrega `_cerrado_{codigo}` a `estado.json` (con motivo, ej. `enterprise_previo`)
    + evento `cierre`. No toca `central.gpkg`.
- **Entrada:** recinto, quién cierra, motivo (variante sin asignar). **Salida:** evento
  `cierre` (+ entrada `_cerrado_` si aplica).

### 4.13 Devolver asignación
- **Familia:** **MIXTA**
  - Actualizar estado y bitácora (ESTADO).
  - Conservar o limpiar el gpkg (ARCHIVOS).
- **Hoy:** `devolver_dialog.ejecutar_devolucion()` orquesta:
  1. Archivos: con avance → gpkg a `Devueltos/R{codigo}.gpkg` (respaldo previo + SHA-256);
     sin avance → `sesion.limpiar_local()` (respaldo a `_historico/` antes de borrar).
  2. Estado: con avance → `liberado: true` + `estado_flujo: "devuelto_con_avance"`
     (este flag **sí** se lee: `listar_recintos_central` muestra el recinto como
     "devuelto" reasignable); sin avance → ranura a `None` (vuelve a pendiente).
  3. Bitácora: evento `devolucion` `{motivo, conservo_avance}`.
- **Entrada:** usuario, recinto, conservar_avance (bool), motivo. **Salida:** recinto
  pendiente o devuelto-con-avance; funcionario liberado.

### 4.14 Listar recintos del central
- **Familia:** ARCHIVOS (hoy) — **candidata a catálogo publicado**
- **Hoy:** `admin_archivos.listar_recintos_central()` lee `central.gpkg` directamente:
  código, nombre, comuna (resuelta a nombre desde 2.1.4), n_electores, n_sin_revisar,
  y estado del recinto cruzando con `estado.json` (pendiente/asignado/devuelto/cerrado).
- **Nota de diseño:** la lista en sí son **conteos agregados** — no hay datos sensibles.
  Si el agente local publicara un `recintos.json` (catálogo) a GitHub tras cada cambio,
  esta consulta pasaría a la familia ESTADO y el software nuevo podría asignar sin ver
  el central. Es la pieza que le falta al contrato para que "asignar" sea 100 % remoto.

### 4.15 Importar entrega SIGE
- **Familia:** **MIXTA**
- **Hoy:** `importador_sige.py`: `escanear_entregas_sige()` (ARCHIVOS: busca
  `*_ENTREGA.xlsx` en OneDrive y filtra contra bitácora), `validar_entrega_sige()` (pura:
  run vacío → excepción, lat/lon nulo → pendiente, tipo fuera de 1–4 → alerta),
  `procesar_entrega_sige()` (ARCHIVOS: copia xlsx+geojson a `QA_pendiente/`; ESTADO:
  libera al funcionario, evento `entrega` con `origen: "sige"` + conteos, mail).
- **Reglas:** las filas con excepción **nunca se descartan** (se importan marcadas);
  el detalle de bitácora lleva solo conteos.

### 4.16 Enviar notificación por mail
- **Familia:** ESTADO (es el único endpoint real que ya existe)
- **Hoy:** `mailer.enviar_mail()` en el plugin → `POST /mail` del server.js en Railway →
  Resend (rama `claude/sigea-backend-mail-historial`; antes SMTP, bloqueado). El servidor
  registra el evento `mail` en bitácora con `enviado` y `nota` (causa del fallo).
- **Entrada:** destinatario (usuario o email), tipo (`asignacion|entrega|qa_ok|qa_obs|cierre`),
  recinto, funcionario. **Salida:** `{ok, enviado, simulado, nota}`.
- **Reglas:** sin API key → simulación, nunca error duro; todo fallo con causa en `nota`;
  cuerpo del mail solo metadata de proceso.

### 4.17 Consolidación de avances (proceso automático)
- **Familia:** ESTADO
- **Hoy:** `.github/workflows/consolidador.yml` — al push de `qgis/*.json`, copia
  `confirmados_total` a `estado.json` y libera al funcionario si el origen es entrega.
- **Nota:** en una API real esta operación **desaparece**: `POST /api/avance` y
  `POST /api/entrega` actualizarían el estado en la misma transacción, eliminando las
  carreras de Actions encoladas (deuda conocida).

---

## 5. Tabla resumen — qué puede migrar y qué se queda local

| ESTADO — puede vivir en el backend | ARCHIVOS — siempre agente local |
|---|---|
| Consultar estado (4.1) | Extraer gpkg del central (4.4) |
| Consultar historial (4.2) | Sesión local: cargar/pausar/respaldar (4.5) |
| Asignar — registro de la asignación (4.3) | Asignar — preparación del gpkg (4.3→4.4) |
| Registrar avance (4.6) | Mover entrega a QA_pendiente (4.8) |
| Entregar — registro y liberación (4.7) | Entregar — copia física del gpkg (4.7→4.8) |
| Registrar resultado de QA (4.9) | Reimportar al central — NEUTRALIZADA (4.10) |
| Cerrar recinto (4.12) | Mover QA a cerrado (4.11) |
| Devolver — registro en estado/bitácora (4.13) | Devolver — conservar/limpiar gpkg (4.13) |
| Enviar mail (4.16) — ya existe como endpoint | Importar SIGE — escaneo y copia de archivos (4.15) |
| Importar SIGE — registro de la entrega (4.15) | Listar recintos del central (4.14, hoy) |
| Consolidación de avances (4.17 — la absorbe la API) | Revisión visual del gpkg en QGIS (parte de 4.9) |

**Lectura de la tabla:** todo lo de la columna izquierda puede ofrecerse como API REST en
Railway y ser usado por el plugin, el dashboard y el software futuro por igual. Todo lo de
la derecha necesita un proceso en la máquina que ve OneDrive — hoy el plugin QGIS; el
contrato solo exige que ese agente **reaccione al estado** (ej.: asignación nueva → extraer
gpkg) en vez de ser quien decide.

## 6. Cambios de fondo que la API haría posibles (para conversación, no para este encargo)

1. **Un solo escritor.** Hoy cuatro actores escriben a GitHub con el mismo token ofuscado
   (`_t` público en `estado.json`). Con API, solo el backend escribe; el token deja de ser
   público y los conflictos de SHA (reintentos 409) desaparecen.
2. **El consolidador muere de éxito.** Avance y entrega serían transaccionales (4.17).
3. **Catálogo de recintos** (4.14): la única pieza ARCHIVOS que se puede volver ESTADO
   publicando conteos agregados.
4. **Auth real:** hoy "admin" = token con push (detección `_detectar_admin`). La API puede
   dar permisos por rol sin repartir tokens de GitHub.
