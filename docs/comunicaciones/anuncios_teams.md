# Textos para Teams — SIGEA Panel 2.1.4 + Dashboard

Listos para copiar y pegar. Tres piezas: anuncio corto, anuncio detallado y mini-FAQ.

---

## 1. Anuncio corto (canal general, lunes temprano)

> 📢 **SIGEA se actualiza: plugin 2.1.4 disponible**
>
> Al abrir QGIS hoy, acepta la actualización del plugin **SIGEA Panel 2.1.4**
> (Complementos → Administrar e instalar complementos → Actualizar).
>
> Lo que mejora para ti:
> - 🗺️ Los recintos nuevos ahora abren directo en **ArcGIS Pro** como capa de
>   puntos (se acabó el convertir a GDB).
> - 🏘️ Las comunas aparecen con su **nombre** (Cholchol, Renaico, Vilcún…),
>   no con el código.
> - 📊 El dashboard tiene una pestaña nueva: **Historial** — el recorrido
>   completo de cada recinto y de tu trabajo.
>
> Tu forma de trabajar **no cambia**: cargar recinto → rectificar →
> registrar avance → entregar. Cualquier cosa rara, avisa por este canal.

---

## 2. Anuncio detallado (para fijar en el canal o enviar por correo)

> **SIGEA — Actualización de plataforma (11 de julio)**
>
> Este fin de semana se actualizó la plataforma SIGEA. Resumen de cambios:
>
> **Plugin QGIS 2.1.4**
> - Los GeoPackage de asignación se generan ahora con el estándar completo
>   (índice espacial incluido). Efecto práctico: un `R{código}.gpkg` abre
>   como **capa de puntos en ArcGIS Pro**, sin el paso previo de conversión
>   en QGIS que hacíamos hasta ahora.
> - Resolución de comunas: donde antes veías "09121" ahora verás "Cholchol".
>   Aplica al listado de recintos del modo admin y a las asignaciones nuevas.
> - Limpieza interna de código de la época del servidor LAN (ya sin uso).
>
> **Dashboard** (misma URL de siempre)
> - Nueva pestaña **Historial**: por recinto (línea de tiempo completa:
>   asignación → avances → entrega → QA → cierre, con duración total) y por
>   funcionario (recintos trabajados, tiempos, entregas, observaciones de QA).
>   Con filtro por rango de fechas.
> - Notificaciones por correo: migradas a un servicio compatible con la
>   plataforma. *(Se activan cuando se configure la llave de envío; mientras
>   tanto siguen registrándose como simuladas en la bitácora.)*
>
> **Lo que NO cambia**
> - Tu flujo diario: Cargar recinto en mapa → rectificar con la botonera →
>   Registrar avance → Pausar y sincronizar → Entregar.
> - Tus archivos y tu trabajo actual: intactos. La actualización no toca los
>   recintos que ya tienes cargados.
> - Los respaldos automáticos (_historico, últimos 5) siguen igual.
>
> **Qué hacer hoy**: solo aceptar la actualización del plugin cuando QGIS la
> ofrezca. Si QGIS no la ofrece: Complementos → Administrar e instalar
> complementos → pestaña Actualizables → SIGEA Panel → Actualizar.

---

## 3. Mini-FAQ (respuestas rápidas para el canal)

**¿Tengo que hacer algo con mi recinto actual?**
No. La actualización no toca los gpkg ya asignados. Sigues donde ibas.

**QGIS no me ofrece la actualización.**
Complementos → Administrar e instalar complementos → Actualizables →
SIGEA Panel 2.1.4 → Actualizar. Si no aparece, cierra y abre QGIS.

**¿Por qué mi recinto anterior sigue sin abrir en ArcGIS Pro?**
El arreglo aplica a los gpkg que se generan **desde ahora** (asignaciones
nuevas). Los antiguos mantienen el formato anterior.

**¿Me van a llegar correos ahora?**
El sistema quedó listo; falta un paso de configuración del servicio de
correo. Mientras tanto, todas las notificaciones quedan registradas en la
pestaña Correos del dashboard.

**Veo algo raro / me falla la asignación.**
Escríbelo en este canal con pantallazo. Si urge: se puede volver a la
versión 2.1.3 en minutos, sin pérdida de trabajo.
