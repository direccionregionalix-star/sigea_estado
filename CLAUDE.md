# CLAUDE.md — SIGEA / sigea_estado

Contexto permanente para cualquier sesión de Claude Code sobre este repo.
Léelo antes de tocar código. Las reglas marcadas **NO SE TOCA** son invariantes:
romperlas corrompe datos en producción sin error visible.

---

## QUÉ ES ESTE ECOSISTEMA

SERVEL, Dirección Regional La Araucanía. Herramientas para rectificar la
geolocalización de los 282 recintos electorales de la región.
Responsable: Seba (smardones). Funcionarios en terreno: igarrido, jmedina,
pfigueroa, mespinozan.

Componentes (este repo aloja varios):

- **SIGE web v4.2 "Dratini"**: geocodificador SPA vanilla JS, deploy estático.
- **SIGEA**: gestión del proceso de rectificación + plugin QGIS de edición.
- **Plugin QGIS sigea_panel v1.4.7**: edición de gpkg + copia de trabajo.
- **SIGEC** (externo, Supabase): geocodificador de predios SII. Solo se consume.

Este encargo trabaja sobre SIGEA. No modifiques SIGE ni el cliente SIGEC
sin instrucción explícita.

---

## ARQUITECTURA DE DOS REPOS — REGLA CRÍTICA DE PRODUCCIÓN

Hay DOS GitHub en juego:

- **PERSONAL** `SebaGeoZ92/sigea_estado` — ESTE repo. El taller. Aquí construyes.
  Es el único al que el conector de Claude Code llega.
- **INSTITUCIONAL** (cuenta DRIX, direccionregionalix@gmail.com) — la fábrica.
  Railway deploya desde aquí. Seba replica el código a mano desde personal.

**NO SE TOCA — destino de estado.json:**
El código se construye en PERSONAL y Seba lo replica a DRIX. PERO el archivo
de estado de producción (`estado.json` / `bitacora.json`) SIEMPRE se lee y
se escribe contra el repo DRIX, NUNCA contra personal.

- El plugin escribe `estado.json` a DRIX vía su propio token (no vía el
  conector; el plugin corre local y no tiene la limitación del conector).
- El dashboard en Railway lee `estado.json` desde DRIX.
- Personal contiene SOLO código. Jamás `estado.json` de producción.
- No asumas que `estado.json` va a personal solo porque construyes aquí.
  No va. Cualquier ruta/owner de GitHub para `estado.json` se toma de
  configuración (variable/constante claramente marcada), **nunca hardcodeada**
  al repo personal.

**TOKEN DE ESCRITURA A DRIX — NO SE TOCA:**
Escribir al repo institucional (DRIX) requiere un token de escritura con
permisos de repositorio. Ese token va en configuración del plugin o en
variable de entorno del servidor — **nunca hardcodeado en el código**.
El mecanismo actual lo distribuye ofuscado en `_t` dentro del `estado.json`
publicado; el plugin lo decodifica en runtime. Ese mecanismo es el correcto;
no lo reemplaces por un token literal en código fuente.

---

## ESQUEMA DE DATOS — ADVERTENCIA CRÍTICA

**El esquema real vive en el repo. Lo que se documente abajo es solo referencia
de contraste: no es verdad si difiere de los archivos reales.**

Antes de construir cualquier feature que toque `estado.json`, `qgis/*.json` o
`sige/*.json`, leer los archivos reales del repo y confirmar campos y tipos.
El esquema del encargo es un borrador del director; el del repo manda.

### Estructura real verificada (2026-06-25)

**`estado.json`** (repo DRIX, generado por el servidor):
```
generado          ISO timestamp
funcionarios
  <usuario>
    asignacion_id   int
    codigo          str  "01485"
    unidad          str  nombre del recinto
    comuna          str
    n_electores     int
    fecha_estimada  str  "YYYY-MM-DD"
    dias_restantes  int
    avance          int  n confirmados
    herramienta     str  "qgis" | otros
    tipo_origen     str  "recinto"
    asignaciones    list  mismos campos
  <usuario_sin_asignacion>: null
_t    str  token ofuscado (XOR+base64, clave SIGEA2026araucania)
_r    str  repo destino escritura  ej: "DrixRepo/sigea_estado"
_b    str  branch  "main"
```

**`qgis/{usuario}.json`** (escrito por plugin QGIS):
```
usuario           str
recinto_cod       str
timestamp         ISO UTC
avance
  total_registros   int
  confirmados       dict  {tipo_geo: n}
  confirmados_total int
  pendientes        int
  pct               float
origen            str  "Plugin QGIS"
```

**`sige/{usuario}.json`** (escrito por SIGE — campos extra opcionales):
```
... mismos que qgis/ ...
archivo           str  nombre del archivo (solo SIGE)
avance
  ... mismos ...
  total_clusters  int  (solo SIGE)
  por_revisar     int  (solo SIGE)
origen            str  "SIGE 4.x"
```

**Tipos geo válidos en `confirmados`:**
`LOCALIDAD`, `EXACTO`, `CALLE`, `NO_GEO`, `PROXIMIDAD`, `FUERA_COMUNA`,
`AUTOGEO`, `MASIVO`
*(Los tipos `RECINTO_NO_GEO` y `SIN_TIPO` existen en el enum pero no cuentan
como avance — el plugin los excluye al sumar `confirmados_total`.)*

**Formato de commit de avance:** `avance {usuario} {codigo} {pct}%`

---

## REGLAS DE NEGOCIO QUE NO SE TOCAN

**RESPALDO ANTES DE LIMPIAR** (`plugin, sesion.py`): nunca borrar la copia de
trabajo local sin dejar antes un respaldo en `sigea_work/_historico/`
(se conservan los últimos 5). Origen: jmedina perdió un día de trabajo cuando
el viejo `limpiar_local()` borraba la copia justo tras sincronizar, antes de
que OneDrive terminara de subir. Prueba de fuego: `sincronizar` debe dejar
copia en `_historico/` ANTES de cualquier limpieza.

**NOMBRE DE GEOMETRÍA DINÁMICO** (`gpkg_engine.py`): la columna de geometría
se detecta desde la metadata `gpkg_geometry_columns` vía `_col_geom()`.
NUNCA hardcodear `"geom"`. El central de producción usa `"geometry"`
(origen ArcGIS Enterprise). Hardcodear rompe la entrega con `no such column`.

**ESCRITURA ATÓMICA + SHA-256** al sincronizar gpkg. No degradar a copia
directa sin verificación de integridad.

**DATOS SENSIBLES NUNCA SALEN A LA WEB.** `estado.json`/`bitacora.json`
llevan solo metadata del proceso y CONTEOS AGREGADOS (cuántos exacto/calle/
localidad/NO_GEO). Jamás RUTs, direcciones ni coordenadas individuales.
Los datos sensibles viven en los gpkg, que nunca tocan Railway ni GitHub
público. Validar esto en CUALQUIER cambio al dashboard, a `estado.json`
o a los mails.

**DOMINIOS SERVEL (no reasignar IDs):**
`LOCALIDAD/RURAL=1`, `EXACTO=2`, `CALLE=3`, `NO_GEO=4`. `revisado_id=2` = confirmado.

---

## RESTRICCIONES DEL ENTORNO

- PowerShell está BLOQUEADO por Trellix en las máquinas SERVEL. No propongas
  soluciones que dependan de PowerShell ni de levantar un servidor Flask local
  permanente. El rumbo es: sin LAN, sin Flask de fondo.
- El flujo de trabajo de Seba es GitHub web + plugin en QGIS. No asumas
  terminal local libre.
- SIGEC cubre SOLO Araucanía (~576k predios, 32 comunas). Vacío fuera de la
  región es esperado, no es bug.

---

## CÓMO TRABAJAR EN ESTE REPO

- Cambios incrementales sobre el plugin v1.4.7 que ya funciona. EXTENDER,
  no reescribir desde cero. SIGEB (otra rama/experimento) está descartado;
  no lo tomes como base.
- Entrega en ramas + PR para que Seba revise en GitHub web antes de mergear.
- Archivos completos cuando crees módulos nuevos; diffs claros al editar.
- Si una instrucción choca con una regla NO SE TOCA, deténte y avísalo en
  el PR en vez de "arreglarlo" silenciosamente.
- Tras construir en personal, recuerda a Seba el paso de replicar a DRIX.
