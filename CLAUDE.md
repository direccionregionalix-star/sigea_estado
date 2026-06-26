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
- Plugin QGIS sigea_panel (actual v1.5.0): edición de gpkg + copia de
  trabajo + estado online sin LAN.
- SIGEC (externo, Supabase): geocodificador de predios SII. Solo se consume.

Trabajamos sobre SIGEA. No modifiques SIGE ni el cliente SIGEC sin
instrucción explícita.

═══════════════════════════════════════════════════════════════
ARQUITECTURA DE REPOS — ESTADO REAL Y DEUDA
═══════════════════════════════════════════════════════════════
REALIDAD ACTUAL (no aspiracional):
  Hoy existe UN SOLO estado.json de producción, y vive en el repo PERSONAL
  SebaGeoZ92/sigea_estado (público). Es el que el plugin sirve a los
  funcionarios. Su campo "_r" apunta a SebaGeoZ92/sigea_estado. Esto es
  correcto HOY: producción = personal. No es un error a corregir en el código.

  Razón: el conector de Claude Code solo llega al repo personal, y la cuenta
  institucional DRIX (direccionregionalix@gmail.com) está separada. Railway
  deploya desde donde Seba lo configure; hoy el estado vive en personal.

DEUDA EXPLÍCITA (pendiente, no urgente):
  Migrar producción al repo institucional DRIX cuando sea viable. Mientras
  estado.json NO contenga datos sensibles, el riesgo es BAJO. El día que la
  bitácora crezca con más detalle, revisar esta deuda antes de seguir.

REGLA NO SE TOCA — datos sensibles:
  estado.json / bitacora.json llevan SOLO metadata de proceso y CONTEOS
  AGREGADOS. Jamás RUTs, direcciones ni coordenadas individuales. Si una
  tarea requiere meter algo sensible al estado, DETENERSE y avisar.

REGLA NO SE TOCA — destino configurable:
  El owner/repo de destino del estado se toma SIEMPRE de configuración
  (mecanismo "_r" en estado.json), NUNCA hardcodeado en el código. El token
  de escritura ("_t") va en config/estado, jamás en el código fuente.

═══════════════════════════════════════════════════════════════
FORMATO REAL DE LOS REPORTES (confirmado leyendo el repo)
═══════════════════════════════════════════════════════════════
Esto MANDA sobre cualquier esquema propuesto en encargos.

Reportes en qgis/{usuario}.json y sige/{usuario}.json:
  usuario, recinto_cod, timestamp, y un bloque de avance con:
  total_registros, confirmados (dict por tipo geo), confirmados_total,
  pendientes, pct.
  SIGE agrega: archivo, total_clusters, por_revisar (el plugin QGIS NO los
  genera).

estado.json (raíz): asignaciones por funcionario (puede ser null), "avance"
  entero, metadata "_t" (token), "_r" (repo destino), "_b" (rama, "main").

TIPOS GEO válidos: LOCALIDAD/RURAL=1, EXACTO=2, CALLE=3, NO GEO=4.
  revisado_id=2 = confirmado. Cualquier tipo fuera de ese dominio es outlier.
  El QA debe alertar — no propagarlo en silencio.

═══════════════════════════════════════════════════════════════
REGLAS DE NEGOCIO QUE NO SE TOCAN
═══════════════════════════════════════════════════════════════
1. RESPALDO ANTES DE LIMPIAR (sesion.py): nunca borrar la copia de trabajo
   sin dejar respaldo en sigea_work/_historico/ (últimos 5). Caso jmedina:
   perdió un día cuando limpiar_local() borraba antes de que OneDrive
   terminara de subir. Prueba de fuego: sincronizar deja copia en _historico/
   ANTES de cualquier limpieza.

2. NOMBRE DE GEOMETRÍA DINÁMICO (gpkg_engine.py): detectar columna de
   geometría desde gpkg_geometry_columns vía _col_geom(). NUNCA hardcodear
   "geom". El central usa "geometry" (origen ArcGIS Enterprise).

3. ESCRITURA ATÓMICA + SHA-256 al sincronizar gpkg. No degradar a copia
   directa sin verificación de integridad.

4. DATOS SENSIBLES NUNCA SALEN A LA WEB. Validar en CUALQUIER cambio al
   estado, bitácora, dashboard o mails.

5. DOMINIOS SERVEL: LOCALIDAD/RURAL=1, EXACTO=2, CALLE=3, NO GEO=4.

═══════════════════════════════════════════════════════════════
RESTRICCIONES DEL ENTORNO
═══════════════════════════════════════════════════════════════
- PowerShell BLOQUEADO por Trellix en máquinas SERVEL. Sin LAN, sin Flask.
  Sprint 1 ya eliminó la dependencia LAN del plugin.
- Flujo de Seba: GitHub web + QGIS. No asumir terminal local libre.
- SIGEC cubre SOLO Araucanía. Vacío fuera de región es esperado, no bug.

═══════════════════════════════════════════════════════════════
CÓMO TRABAJAR EN ESTE REPO
═══════════════════════════════════════════════════════════════
- EXTENDER el plugin que funciona. No reescribir. SIGEB descartado.
- Ramas + PR para revisión antes de mergear.
- Si instrucción choca con regla NO SE TOCA: detenerse y avisarlo en el PR.
- Reportar honestamente lo no probado en QGIS real.

═══════════════════════════════════════════════════════════════
ESTADO DE SPRINTS
═══════════════════════════════════════════════════════════════
SPRINT 1 (CERRADO 2026-06-25) — Cortar dependencia Flask/LAN:
  Plugin v1.5.0: elimina fallback LAN, arranca en estado_online(), entrega
  publica a GitHub vía github_report. URL estado configurable (no hardcodeada).
  Probado en QGIS real: carga asignación + publica avance sin LAN. ✅

SPRINT 2 (ACTIVO) — Evidencia completa + modo admin:
  Ver ENCARGO_SIGEA_v2_sprint2.md
