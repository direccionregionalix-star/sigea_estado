# PORTABILIDAD REGIONAL — Auditoría de lo específico de La Araucanía

Objetivo: dejar por escrito **todo** lo que hoy está atado a La Araucanía en el
código (plugin + dashboard + backend), clasificado, para poder levantar una
instancia nueva (ej. **Los Ríos**) sin rehacer el sistema. Cada instancia es un
**deployment independiente** (su propio repo, su propio Railway, su propia
config). **No hay** —ni se busca— multi-tenencia ni un selector de región.

Fecha de la auditoría: 2026-07-20. Versión plugin auditada: 2.1.7 → refactor 2.1.8.

## Clasificación usada

| Clase | Significado | Qué se hace con ello |
|-------|-------------|----------------------|
| **DATO** | Cambia según la región (ej. la tabla de comunas). | Se movió a un punto único de config. |
| **IDENTIDAD** | Marca / cuenta / URL / servicio propio de la región (nombre, SIGEC, Railway, repo, clave). | Se movió a config o queda como variable de entorno; nunca hardcodeado disperso. |
| **UNIVERSAL** | Igual en todas las regiones (dominios de tipo geo de SERVEL, nombres de campos, reglas de negocio). | **NO SE TOCA.** Se deja donde está. |

---

## 1. PLUGIN QGIS (`sigea_panel/`)

### 1.1 Movido a `region_config.py` (punto único) — DATO / IDENTIDAD

| Qué | Antes (archivo:línea) | Ahora | Clase |
|-----|----------------------|-------|-------|
| Tabla de 32 comunas (código SII 4 díg. → nombre) | `comunas.py` (dict `COMUNAS` inline) | `region_config.COMUNAS` | **DATO** |
| Base URL del servicio SIGEC (Supabase) | `sigec.py` (`_BASE = "https://…supabase.co"`) | `region_config.SIGEC_BASE` | **IDENTIDAD** |
| Anon key de SIGEC (RLS, embebible) | `sigec.py` (`_ANON = "sb_publishable_…"`) | `region_config.SIGEC_ANON` | **IDENTIDAD** |
| Clave de ofuscación del token `_t` | `github_report.py` (`_OBF_KEY = b"SIGEA2026araucania"`) | `region_config.OFUSCACION_KEY` | **IDENTIDAD / SECRETO** |
| Nombre de la región (UI/firmas) | *(no existía como constante)* | `region_config.REGION_NOMBRE` | **IDENTIDAD** |
| Firma institucional | *(implícita)* | `region_config.REGION_FIRMA` | **IDENTIDAD** |

`comunas.py`, `sigec.py` y `github_report.py` ahora **importan** de
`region_config`. Su API pública y su comportamiento son idénticos (verificado,
ver §4).

### 1.2 NO hardcodeado — ya estaba bien diseñado (no requiere cambio)

| Qué | Archivo:línea | Nota |
|-----|---------------|------|
| URL del estado online (`estado.json`) | `settings.py:99` (`estado_url()` lee de QGIS settings) | Configurable por el usuario en el diálogo de config. Cada región pone la suya. **No hay URL de región hardcodeada.** |
| Repo/rama destino del avance | Se leen de `_r` / `_b` dentro del `estado.json` | Regla NO SE TOCA de CLAUDE.md: destino siempre desde config, nunca en código. |
| URL de Railway para correo | Deriva de `estado_url()` | Sin literal de Railway en el plugin. |
| Lista de funcionarios | *(no existe en código)* | Los funcionarios salen **siempre** de `estado.json` en runtime. No hay código que asuma un conjunto fijo. Las apariciones de `igarrido`/`jmedina`/`mespinozan` en el plugin son **placeholders de UI** (`config_dialog.py:28`) y **comentarios/casos históricos** (reglas jmedina, etc.), no lógica. |

### 1.3 UNIVERSAL — NO SE TOCA (queda en su sitio)

| Qué | Archivo:línea | Por qué es universal |
|-----|---------------|----------------------|
| Dominio de tipo geo `{1,2,3,4}` = LOCALIDAD/EXACTO/CALLE/NO_GEO | `importador_sige.py:35` (`_TIPOS_VALIDOS`) | Dominio SERVEL nacional. Regla NO SE TOCA. |
| Conteos por `tipo_geo_id` (localidad/exacto/calle/no_geo) | `importador_sige.py:189-195` | Mismo dominio nacional. |
| Botonera de tipos (EXACTO, LOCALIDAD, CALLE, PROXIMIDAD…) | `config_dialog.py:109` | Tipos SERVEL. |
| `NOMBRES` tipo_geo_id → etiqueta legible | `github_report.py:26-29` | Diccionario de dominio nacional. |
| Detección dinámica de columna geométrica / `tipo_geo_id` vs `revisado_id` | `admin_archivos.py:143` | Regla NO SE TOCA (nombre de geometría dinámico). |
| `revisado_id=2` = confirmado | (varios) | Regla de negocio nacional. |

---

## 2. DASHBOARD (`dashboard/index.html`, cliente)

### 2.1 Movido a config (inyección por `server.js` + `region_config.json`) — IDENTIDAD

| Qué | Antes (línea) | Ahora | Clase |
|-----|---------------|-------|-------|
| `<title>` de la página | `index.html:6` (literal Araucanía) | `document.title = _REGION_TITULO` (placeholder `__REGION_TITULO__`); el literal queda como **fallback** si se abre sin servidor | **IDENTIDAD** |
| Encabezado `<h1>` visible | `index.html:355` | `<span id="app-encab">` → se setea con `_REGION_ENCAB` (placeholder `__REGION_ENCABEZADO__`) | **IDENTIDAD** |
| Firma al pie de los correos que arma el cliente | `index.html:1491-1495` (`_MAIL_CUERPOS`) | `${_REGION_FIRMA}` (placeholder `__REGION_FIRMA__`) | **IDENTIDAD** |

El servidor reemplaza los placeholders al servir el HTML con los valores de
`region_config.json`. Si el HTML se abre como archivo estático (sin servidor),
los `_REGION_*` caen a su **valor por defecto Araucanía** (fallback
`"__X__".indexOf("__")===0 ? default : "__X__"`), preservando el comportamiento
actual.

### 2.2 Constante compartida — IDENTIDAD / SECRETO (decisión consciente, ver §5)

| Qué | Archivo:línea | Clase |
|-----|---------------|-------|
| Clave de ofuscación / clave admin `"SIGEA2026araucania"` | `index.html:542` (placeholder del input), `index.html:699` (default de `deofuscar`), `index.html:1617` (default de la clave admin) | **IDENTIDAD / SECRETO** |

Es la **misma** clave que `region_config.OFUSCACION_KEY` (plugin) y que
`server.js` (§3). Es a la vez la clave de ofuscación del token `_t` **y** la
clave que el supervisor teclea para desbloquear acciones admin. Ver §5.

### 2.3 UNIVERSAL en el dashboard — NO SE TOCA

| Qué | Nota |
|-----|------|
| `ASUNTOS`/plantillas de evento (`asignacion`, `entrega`, `qa_ok`…) | Vocabulario del proceso, igual en toda región. |
| Etiquetas de tipo geo, estados operativos | Dominio nacional. |

---

## 3. BACKEND (`dashboard/server.js` + `mailer_gmail.js`, Railway)

### 3.1 Movido a config / variable de entorno — IDENTIDAD

| Qué | Antes | Ahora | Clase |
|-----|-------|-------|-------|
| Repo GitHub del estado | `server.js:31` `SIGEA_REPO` (env, default `direccionregionalix-star/sigea_estado`) | *(ya era env; se mantiene)* — cada región pone `SIGEA_REPO` en su Railway | **IDENTIDAD** |
| Título / encabezado / firma | dispersos | Bloque `REGION` (`server.js:42-54`): default Araucanía → `region_config.json` → override por env `SIGEA_REGION_TITULO` / `SIGEA_REGION_ENCABEZADO` / `SIGEA_FIRMA_CORREO` | **IDENTIDAD** |
| Firma en cuerpos de correo del servidor | `server.js` (`CUERPOS`, firma inline) | `${_FIRMA}` = `REGION.firma_correo` | **IDENTIDAD** |
| Nombre visible del remitente (`From:`) | `mailer_gmail.js:110` (literal `"SIGEA DR Araucanía"`) | `REMITENTE_NOMBRE = process.env.SIGEA_FIRMA_CORREO \|\| "SIGEA DR Araucanía"` (mismo env que la firma) | **IDENTIDAD** |
| URL de Railway / SIGEC de referencia | — | `region_config.json` (`railway_url`, `sigec_url`) — informativos/documentales | **IDENTIDAD** |

> **Gap cerrado en este encargo:** `mailer_gmail.js:110` armaba el `From:` con la
> firma **hardcodeada**, independiente del resto de la config. Ahora sigue la
> misma variable `SIGEA_FIRMA_CORREO`. Default Araucanía ⇒ comportamiento idéntico.

### 3.2 Constante compartida — IDENTIDAD / SECRETO

| Qué | Archivo:línea |
|-----|---------------|
| Clave de ofuscación `"SIGEA2026araucania"` | `server.js:115` (default de `deofuscar`) |

Misma clave que §1.1 (plugin) y §2.2 (cliente). Ver §5.

### 3.3 Credenciales — nunca en el repo (ya correcto)

`GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN/SENDER`, `SIGEA_SUPERVISOR_MAIL`,
`SIGEA_MAILS`: **todas** por variable de entorno en Railway. Ninguna vive en el
código. Regla NO SE TOCA respetada.

---

## 4. DATOS GENERADOS Y METADATA DE RELEASE (DATO / IDENTIDAD, fuera del código de lógica)

| Qué | Archivo | Clase | Nota |
|-----|---------|-------|------|
| Catálogo de recintos | `recintos_catalogo.json` | **DATO** | Se **genera** desde el `central.gpkg` de la región (botón Publicar catálogo). Otra región produce el suyo; no se edita a mano. |
| Estado / bitácora de proceso | `estado.json`, `bitacora.json` | **DATO** (runtime) | Producción viva. Cada región tiene los suyos en su repo. |
| Reporte de auditoría | `auditoria_sigea.html` | **DATO** | HTML generado con recintos/comunas de la región. |
| Metadata del plugin | `plugins.xml`, `sigea_panel/metadata.txt`, `package.json` (raíz y `dashboard/`) | **IDENTIDAD** | `description`, `author_name` (`SERVEL DR Araucanía`), `homepage`/`download_url` (repo). Cada región edita estos textos al publicar su release. Cosmético, sin efecto sobre la lógica. |
| Materiales de comunicación | `docs/comunicaciones/servelito.html`, `infografia.html` | **IDENTIDAD** | Cadenas "La Araucanía" en piezas gráficas. Cosmético; se adapta al comunicar una región nueva. |
| `CLAUDE.md` | raíz | contexto | Documento de contexto del ecosistema Araucanía; se adapta por región. |

---

## 5. DECISIÓN CONSCIENTE — la clave de ofuscación vive en 5 lugares

`"SIGEA2026araucania"` (bytes en el plugin) es un **secreto compartido** que
DEBE coincidir entre tres artefactos que se despliegan por separado:

1. `sigea_panel/region_config.py` → `OFUSCACION_KEY` (compilada en el `.zip`)
2. `dashboard/index.html:542` (placeholder del input de clave)
3. `dashboard/index.html:699` (default de `deofuscar`)
4. `dashboard/index.html:1617` (default de la clave admin)
5. `dashboard/server.js:115` (default de `deofuscar`)

**Por qué NO se centralizó en un único archivo:** el plugin y el dashboard son
artefactos distintos (zip QGIS vs sitio Railway) que jamás comparten un archivo
en runtime; "un único punto" físico es imposible entre ellos. Además, en el
cliente la misma cadena es a la vez **clave de ofuscación** y **contraseña que
el supervisor teclea**. Refactorizarla arriesgaría cambio de comportamiento sin
ganancia real de portabilidad. La decisión —dejarla enumerada y documentada— es
la opción segura. Para una región nueva **conviene una clave propia**: cámbiala
en **los 5 lugares** de arriba (ver `docs/GUIA_NUEVA_REGION.md`, paso "Clave").

---

## 6. VERIFICACIÓN DE COMPORTAMIENTO IDÉNTICO (Araucanía)

Requisito del encargo: cero cambio de comportamiento para Araucanía.

- **Plugin:** harness sin QGIS que carga `region_config` + `comunas` y comprueba:
  32 comunas exactas, todas las rutas de `codigo_sigec` (CUT `09115`, float
  `9115.0`, nombre `Pucón`/`pucon`, vacío, desconocido), `nombre_de`,
  `opciones_ordenadas` (32, primera "Angol"), y los valores de identidad
  (`SIGEC_BASE`, `SIGEC_ANON`, `OFUSCACION_KEY`, `REGION_NOMBRE`). **Todo pasa.**
- **Dashboard servido por `server.js` con defaults Araucanía:** `<title>` y
  encabezado renderizan `SIGEA — Estado Rectificación La Araucanía` /
  `— Rectificación Electoral La Araucanía`; `_REGION_FIRMA` = `SIGEA DR Araucanía`
  — **idéntico** a antes del refactor.
- **Override probado (Los Ríos vía env):** los tres valores cambian
  correctamente, confirmando que la portabilidad funciona sin tocar código.
- `node --check` OK en `server.js` y `mailer_gmail.js`.

## 7. RESUMEN — puntos únicos de config por componente

| Componente | Punto único de config regional |
|------------|-------------------------------|
| Plugin QGIS | `sigea_panel/region_config.py` |
| Dashboard (cliente) | `dashboard/region_config.json` (inyectado por `server.js`; fallback Araucanía embebido) |
| Backend (Railway) | `region_config.json` + variables de entorno (`SIGEA_REPO`, `SIGEA_REGION_*`, `SIGEA_FIRMA_CORREO`, credenciales Gmail) |
| Secreto compartido | Clave de ofuscación — 5 lugares enumerados en §5 (decisión consciente) |
| Datos | `central.gpkg` → `recintos_catalogo.json`, `estado.json`, `bitacora.json` (por región) |

Lo **UNIVERSAL** (dominios de tipo geo, nombres de campos, reglas de negocio
SERVEL) **no se movió**: es idéntico en toda región y se queda en su lugar.
