# CLAUDE.md — SIGEA / sigea_estado

Contexto permanente para cualquier sesión de Claude Code sobre este repo.
Léelo antes de tocar código. Las reglas marcadas NO SE TOCA son invariantes:
romperlas corrompe datos en producción sin error visible.

═══════════════════════════════════════════════════════════════
QUÉ ES ESTE ECOSISTEMA
═══════════════════════════════════════════════════════════════
SERVEL, Dirección Regional La Araucanía. Herramientas para rectificar la
geolocalización de los 282 recintos electorales de la región. Responsable:
Seba (smardones). Funcionarios que operan en terreno: igarrido, jmedina,
pfigueroa, mespinozaN.

Componentes (este repo aloja varios):
- SIGE web v4.2 "Dratini": geocodificador SPA vanilla JS, deploy estático.
- SIGEA: gestión del proceso de rectificación + plugin QGIS de edición.
- Plugin QGIS `sigea_panel` v1.4.7: edición de gpkg + copia de trabajo.
- SIGEC (externo, Supabase): geocodificador de predios SII. Solo se consume.

Este encargo trabaja sobre SIGEA. No modifiques SIGE ni el cliente SIGEC sin
instrucción explícita.

═══════════════════════════════════════════════════════════════
ARQUITECTURA DE DOS REPOS — REGLA CRÍTICA DE PRODUCCIÓN
═══════════════════════════════════════════════════════════════
Hay DOS GitHub en juego:
- PERSONAL `SebaGeoZ92/sigea_estado` — ESTE repo. El taller. Aquí construyes.
  Es el único al que el conector de Claude Code llega.
- INSTITUCIONAL (cuenta DRIX, direccionregionalix@gmail.com) — la fábrica.
  Railway deploya desde aquí. Seba replica el código a mano desde personal.

REGLA NO SE TOCA — destino de estado.json:
  El código se construye en PERSONAL y Seba lo replica a DRIX.
  PERO el archivo de estado de producción (estado.json / bitacora.json) SIEMPRE
  se lee y se escribe contra el repo DRIX, NUNCA contra personal.
  - El plugin escribe estado.json a DRIX vía su propio token (no vía el
    conector; el plugin corre local y no tiene la limitación del conector).
  - El dashboard en Railway lee estado.json desde DRIX.
  - Personal contiene SOLO código. Jamás estado.json de producción.
  No asumas que estado.json va a personal solo porque construyes aquí. No va.
  Cualquier ruta/owner de GitHub para estado.json se toma de configuración
  (variable/constante claramente marcada), nunca hardcodeada al repo personal.

═══════════════════════════════════════════════════════════════
REGLAS DE NEGOCIO QUE NO SE TOCAN
═══════════════════════════════════════════════════════════════
1. RESPALDO ANTES DE LIMPIAR (plugin, sesion.py): nunca borrar la copia de
   trabajo local sin dejar antes un respaldo en sigea_work/_historico/
   (se conservan los últimos 5). Origen de la regla: jmedina perdió un día de
   trabajo cuando el viejo limpiar_local() borraba la copia justo tras
   sincronizar, antes de que OneDrive terminara de subir. Prueba de fuego:
   sincronizar debe dejar copia en _historico/ ANTES de cualquier limpieza.

2. NOMBRE DE GEOMETRÍA DINÁMICO (gpkg_engine.py): la columna de geometría se
   detecta desde la metadata gpkg_geometry_columns vía _col_geom(). NUNCA
   hardcodear "geom". El central de producción usa "geometry" (origen ArcGIS
   Enterprise). Hardcodear rompe la entrega con `no such column`.

3. ESCRITURA ATÓMICA + SHA-256 al sincronizar gpkg. No degradar a copia
   directa sin verificación de integridad.

4. DATOS SENSIBLES NUNCA SALEN A LA WEB. estado.json/bitacora.json llevan solo
   metadata del proceso y CONTEOS AGREGADOS (cuántos exacto/calle/localidad/
   NO GEO). Jamás RUTs, direcciones ni coordenadas individuales. Los datos
   sensibles viven en los gpkg, que nunca tocan Railway ni GitHub público.
   Validar esto en CUALQUIER cambio al dashboard, a estado.json o a los mails.

5. DOMINIOS SERVEL (no reasignar IDs): LOCALIDAD/RURAL=1, EXACTO=2, CALLE=3,
   NO GEO=4. revisado_id=2 = confirmado.

═══════════════════════════════════════════════════════════════
RESTRICCIONES DEL ENTORNO
═══════════════════════════════════════════════════════════════
- PowerShell está BLOQUEADO por Trellix en las máquinas SERVEL. No propongas
  soluciones que dependan de PowerShell ni de levantar un servidor Flask local
  permanente. El rumbo es: sin LAN, sin Flask de fondo.
- El flujo de trabajo de Seba es GitHub web + plugin en QGIS. No asumas
  terminal local libre.
- SIGEC cubre SOLO Araucanía (~576k predios, 32 comunas). Vacío fuera de la
  región es esperado, no es bug.

═══════════════════════════════════════════════════════════════
CÓMO TRABAJAR EN ESTE REPO
═══════════════════════════════════════════════════════════════
- Cambios incrementales sobre el plugin v1.4.7 que ya funciona. EXTENDER, no
  reescribir desde cero. SIGEB (otra rama/experimento) está descartado; no lo
  tomes como base.
- Entrega en ramas + PR para que Seba revise en GitHub web antes de mergear.
- Archivos completos cuando crees módulos nuevos; diffs claros al editar.
- Si una instrucción choca con una regla NO SE TOCA, deténte y avísalo en el
  PR en vez de "arreglarlo" silenciosamente.
- Tras construir en personal, recuerda a Seba el paso de replicar a DRIX.
