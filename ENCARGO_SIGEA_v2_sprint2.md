# ENCARGO SIGEA v2 — Sprint 2
# Evidencia completa + modo admin

Lee CLAUDE.md antes de actuar. Este encargo asume Sprint 1 mergeado a main.

═══════════════════════════════════════════════════════════════
OBJETIVO DEL SPRINT
═══════════════════════════════════════════════════════════════
Cerrar el ciclo de evidencia que SIGEA web tenía y que el Sprint 1 dejó
pendiente: bitácora completa, entrega formal, mail, dashboard funcional,
y la pieza que faltó en el Sprint 1 — el modo admin para que Seba asigne
recintos sin Flask.

═══════════════════════════════════════════════════════════════
ESTADO DE IMPLEMENTACIÓN
═══════════════════════════════════════════════════════════════
Rama: claude/sprint2-evidencia
Plugin: sigea_panel.1.6.0.zip

[ ] Pendiente validación Proto-Admin SIGEA en QGIS real
[ ] Pendiente merge a main tras validación

═══════════════════════════════════════════════════════════════
PIEZAS DEL SPRINT
═══════════════════════════════════════════════════════════════

## 1. BITÁCORA ✅
bitacora.py — módulo append-only. Escribe eventos a bitacora.json en el
repo vía GitHub Contents API. Maneja SHA y reintenta en 409.

Tipos de evento implementados:
- "asignacion"  { asignado_por }
- "avance"      { por tipo geo, total, pct }
- "entrega"     { por tipo geo, total, pct }
- "qa"          { resultado, comentario }
- "cierre"      { cerrado_por }
- "mail"        { destinatario, asunto, enviado }
- "alerta_tipo" { tipo_detectado, recinto }

REGLA: detalle nunca lleva RUTs, direcciones ni coordenadas.

## 2. MODO ADMIN EN EL PLUGIN ✅
admin_dialog.py — diálogo con tres pestañas:
- Estado global: tabla con avance de todos los funcionarios.
- Asignar recinto: actualiza estado.json + evento "asignacion" en bitácora.
- QA/Cierre: alerta tipos geo fuera de dominio + marcar QA + cierre formal.

Detección de permisos: GET a /repos/{repo} — no genera commits fantasma.
El botón Admin solo aparece si el token tiene push access.

## 3. ENTREGA FORMAL COMO EVENTO ✅
entregar() extendido (no reemplazado):
- Publica avance final en qgis/{usuario}.json (existía)
- Escribe evento "entrega" en bitacora.json con conteos por tipo geo (nuevo)

## 4. ALERTA QA TIPOS GEO ✅
En pestaña QA del admin: si el reporte del funcionario tiene tipos fuera
del dominio SERVEL, muestra alerta visible y registra evento "alerta_tipo".
No bloquea — alerta, Seba decide.

## 5. DASHBOARD FIXES ✅
Fix A: usuarios dinámicos desde estado.json (no hardcodeados).
Fix B: tipos geo desconocidos en gris con etiqueta "Tipo desconocido (X)".

## 6. MAIL SERVER-SIDE ✅
dashboard/server.js — Node sin deps externas (nodemailer opcional).
POST /mail { destinatario, tipo, recinto, funcionario }
Sin SMTP configurado: simula + "enviado": false en bitácora.

Variables de entorno requeridas en Railway:
  SIGEA_SMTP_HOST, SIGEA_SMTP_PORT, SIGEA_SMTP_USER, SIGEA_SMTP_PASS
  SIGEA_MAIL_FROM  (opcional, default: SMTP_USER)
  SIGEA_MAILS      (JSON: {"igarrido": "i.garrido@servel.cl", ...})
  SIGEA_ESTADO_URL (URL del estado.json para leer credenciales bitácora)

═══════════════════════════════════════════════════════════════
DECISIONES PENDIENTES DE VALIDACIÓN
═══════════════════════════════════════════════════════════════
1. asignacion_id generado por timestamp — si SIGEA necesita IDs correlativos,
   reemplazar.
2. Asignación desde admin sobreescribe asignación anterior del funcionario.
   Si se necesitan asignaciones múltiples simultáneas, extender.
3. Mail server sin autenticación en el endpoint — agregar header secreto
   si queda expuesto en Railway.
4. nodemailer como optionalDependency — ejecutar npm install en dashboard/
   antes del primer deploy con SMTP real.

═══════════════════════════════════════════════════════════════
ARCHIVOS NUEVOS/MODIFICADOS
═══════════════════════════════════════════════════════════════
bitacora.json              ← nuevo, raíz del repo (array vacío)
dashboard/index.html       ← fixes A y B
dashboard/server.js        ← nuevo servidor de mail
dashboard/package.json     ← nuevo
plugin_src/bitacora.py     ← nuevo módulo
plugin_src/admin_dialog.py ← nuevo diálogo admin
plugin_src/panel.py        ← extendido (admin btn + bitácora en avance/entrega)
plugin_src/github_report.py← NOMBRES promovido a módulo
plugin_src/metadata.txt    ← version 1.6.0
plugins.xml                ← apunta a 1.6.0
sigea_panel.1.6.0.zip      ← plugin empaquetado

INTACTOS (confirmado por git diff):
  sesion.py ✅   gpkg_engine.py ✅
