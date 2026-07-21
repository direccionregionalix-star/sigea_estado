# GUÍA — Levantar SIGEA en una región nueva (ej. Los Ríos)

Procedimiento seguible paso a paso para poner en marcha una **instancia
independiente** de SIGEA en otra región. Cada instancia tiene su propio repo,
su propio Railway, su propia config y sus propios datos. **No** se comparte
estado entre regiones ni existe un selector de región: son deployments separados.

Base conceptual: `docs/PORTABILIDAD_REGIONAL.md` (qué es DATO / IDENTIDAD /
UNIVERSAL). Aquí solo tocamos **DATO** e **IDENTIDAD**; lo **UNIVERSAL** jamás.

> Tiempo estimado: media jornada, la mayor parte esperando el `central.gpkg` y
> el proyecto SIGEC/Supabase de la región. Ninguno de estos pasos toca la lógica
> del software.

---

## Antes de empezar — qué necesitas de la región nueva

- [ ] **Cuenta/organización GitHub** donde vivirá el repo de la nueva región.
- [ ] **`central.gpkg`** de la región (capa de recintos desde ArcGIS Enterprise).
- [ ] **Tabla de comunas** de la región: código SII de 4 dígitos → nombre.
      (Los Ríos = región XIV, códigos `14xx`.)
- [ ] **Proyecto SIGEC/Supabase** de la región (geocodificador de predios) con su
      URL y su *anon key* (publishable, read-only por RLS). Opcional: si no hay,
      el buscador SIGEC queda inactivo y no rompe nada.
- [ ] **Cuenta Gmail** para el envío de correos (o reutilizar el flujo OAuth2 ya
      documentado en `docs/MAIL_GMAIL.md`).
- [ ] Nombre y firma institucional de la región (ej. `SIGEA DR Los Ríos`).

---

## Paso 1 — Crear el repo de la región

1. Crea un repo nuevo (ej. `<org-los-rios>/sigea_estado`).
2. Copia el contenido de este repo **sin** los datos de Araucanía:
   - Incluye: `sigea_panel.*.zip`, `plugins.xml`, `dashboard/`, `docs/`.
   - Reemplaza / vacía los **DATO**: `recintos_catalogo.json` (se regenera, paso 6),
     `estado.json` y `bitacora.json` (arranca en limpio, paso 5).
3. Deja `estado.json` inicial mínimo (sin asignaciones), con su bloque de
   metadata `_r` / `_b` / `_t` apuntando a **este** repo nuevo (ver paso 4 y 5).

---

## Paso 2 — Config del PLUGIN: `sigea_panel/region_config.py`

Único archivo del plugin a editar. Descomprime el `.zip`, edita, re-empaqueta.

```python
REGION_NOMBRE = "Los Ríos"                     # IDENTIDAD
REGION_FIRMA  = "SIGEA DR Los Ríos"            # IDENTIDAD

COMUNAS = {                                     # DATO — TABLA COMPLETA DE LA REGIÓN
    "1401": "Valdivia", "1402": "Corral", "1403": "Lanco",
    "1404": "Los Lagos", "1405": "Máfil", "1406": "Mariquina",
    "1407": "Paillaco", "1408": "Panguipulli", "1409": "La Unión",
    "1410": "Futrono", "1411": "Lago Ranco", "1412": "Río Bueno",
    # … completar con TODAS las comunas de la región …
}

SIGEC_BASE = "https://<proyecto-los-rios>.supabase.co"   # IDENTIDAD (vacío = SIGEC off)
SIGEC_ANON = "sb_publishable_…"                          # IDENTIDAD (anon key RLS)

OFUSCACION_KEY = b"SIGEA2026losrios"           # IDENTIDAD/SECRETO (ver Paso 4)
```

**No toques** nada más del plugin: los dominios de tipo geo, los nombres de
campos y las reglas de negocio son UNIVERSALES.

Re-empaqueta:

```bash
zip -rq sigea_panel.<version>.zip sigea_panel -x "*/__pycache__/*"
```

Actualiza `sigea_panel/metadata.txt` (`author`, `description`, `about`) y
`plugins.xml` (`author_name`, `description`, `file_name`, `download_url`
apuntando al **raw** del repo de la región).

---

## Paso 3 — Config del DASHBOARD: `dashboard/region_config.json`

Único archivo del dashboard a editar:

```json
{
  "region": "Los Ríos",
  "titulo": "SIGEA — Estado Rectificación Los Ríos",
  "encabezado": "— Rectificación Electoral Los Ríos",
  "firma_correo": "SIGEA DR Los Ríos",
  "railway_url": "https://<app-los-rios>.up.railway.app",
  "sigec_url": "https://<proyecto-los-rios>.supabase.co"
}
```

`server.js` lo lee al arrancar e inyecta título/encabezado/firma en el HTML. Los
mismos valores pueden sobreescribirse por variable de entorno en Railway
(`SIGEA_REGION_TITULO`, `SIGEA_REGION_ENCABEZADO`, `SIGEA_FIRMA_CORREO`) si
prefieres no comitear el archivo.

---

## Paso 4 — Clave de ofuscación (secreto compartido)

La clave protege el token de escritura `_t`. **Conviene una clave propia por
región.** Debe coincidir **exactamente** en 5 lugares (ver
`PORTABILIDAD_REGIONAL.md §5`):

1. `sigea_panel/region_config.py` → `OFUSCACION_KEY = b"SIGEA2026losrios"`
2. `dashboard/index.html:542` — placeholder del input `inp-clave`
3. `dashboard/index.html:699` — default de `deofuscar(b64, key = "…")`
4. `dashboard/index.html:1617` — default de la clave admin
5. `dashboard/server.js:115` — default de `deofuscar(b64, key = "…")`

Cambia la misma cadena en los 5. Si difieren, el token no se descifra y las
publicaciones fallan.

---

## Paso 5 — Token de escritura y metadata del estado (`estado.json`)

1. Genera un **PAT de GitHub** con permiso de escritura sobre el repo de la región.
2. Ofúscalo con la clave del paso 4 (XOR + base64; misma rutina `deofuscar`
   invertida). Guárdalo en `estado.json` como `_t`. **Nunca** en el código.
3. Setea en `estado.json`:
   - `_r`: `"<org-los-rios>/sigea_estado"` (repo destino)
   - `_b`: `"main"`
   - `_mail`: URL de Railway de la región (si aplica)
4. Arranca `estado.json` **sin asignaciones** (funcionarios en `null`), `avance` 0.
   Los funcionarios se agregan operativamente; el código **no** asume ninguno fijo.

> Regla NO SE TOCA: `estado.json` / `bitacora.json` llevan solo metadata de
> proceso y conteos agregados. Jamás RUTs, direcciones ni coordenadas.

---

## Paso 6 — Datos: catálogo de recintos

1. Carga el `central.gpkg` de la región en QGIS con el plugin instalado.
2. En modo admin, usa **Publicar catálogo** → genera y sube
   `recintos_catalogo.json` al repo de la región.
3. El dashboard lo consumirá automáticamente (vista Recintos).

No edites `recintos_catalogo.json` a mano: es un artefacto **generado**.

---

## Paso 7 — Backend en Railway

1. Crea un servicio Railway nuevo apuntando al repo de la región (carpeta `dashboard/`).
2. Configura variables de entorno (**ninguna credencial va al repo**):
   - `SIGEA_REPO=<org-los-rios>/sigea_estado`
   - `SIGEA_FIRMA_CORREO=SIGEA DR Los Ríos` (o deja que lo tome de `region_config.json`)
   - `SIGEA_SUPERVISOR_MAIL=<correo del supervisor>`
   - `SIGEA_MAILS={"usuario":"correo@…", …}` (mapa funcionario→email)
   - Gmail OAuth2: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`,
     `GMAIL_SENDER` — ver `docs/MAIL_GMAIL.md` para generarlos.
3. Deploy. Verifica en la home que el título/encabezado digan **Los Ríos**.

---

## Paso 8 — SIGEC (opcional, geocodificador de predios)

- Si la región tiene proyecto SIGEC/Supabase: pon `SIGEC_BASE`/`SIGEC_ANON` en
  `region_config.py` (paso 2) y `sigec_url` en `region_config.json` (paso 3).
- Si **no** tiene: deja `SIGEC_BASE = ""`. El buscador SIGEC queda inactivo sin
  romper nada (igual que "vacío fuera de región" en Araucanía — es esperado).

---

## Paso 9 — Verificación final (antes de operar)

- [ ] El plugin instala en QGIS y **Publicar catálogo** sube el `recintos_catalogo.json`.
- [ ] El dashboard (Railway) muestra el nombre de la región en título y encabezado.
- [ ] Una asignación de prueba se publica al `estado.json` de la región (token OK).
- [ ] Un correo de prueba llega firmado `SIGEA DR <Región>` con el `From:` correcto.
- [ ] El buscador de comuna resuelve un código/nombre de la región nueva.
- [ ] SIGEC responde (o queda inactivo a propósito si no hay proyecto).

---

## Lo que NUNCA se cambia (UNIVERSAL)

No toques —en ninguna región— los dominios de tipo geo (`{1,2,3,4}` =
LOCALIDAD/EXACTO/CALLE/NO_GEO), los nombres de campos, la detección dinámica de
la columna geométrica, el respaldo antes de limpiar, ni la escritura atómica con
SHA-256. Son reglas SERVEL nacionales e invariantes del sistema (ver `CLAUDE.md`).

---

## Checklist rápido de archivos a tocar por región

| Archivo | Qué cambiar |
|---------|-------------|
| `sigea_panel/region_config.py` | `REGION_NOMBRE`, `REGION_FIRMA`, `COMUNAS`, `SIGEC_*`, `OFUSCACION_KEY` |
| `sigea_panel/metadata.txt`, `plugins.xml` | textos de release, `download_url` |
| `dashboard/region_config.json` | `region`, `titulo`, `encabezado`, `firma_correo`, `railway_url`, `sigec_url` |
| `dashboard/index.html` (3 líneas) + `dashboard/server.js` (1 línea) | clave de ofuscación (paso 4) |
| `estado.json` | `_r`, `_b`, `_t` (token ofuscado), sin asignaciones |
| Variables de entorno Railway | `SIGEA_REPO`, `SIGEA_*`, credenciales Gmail |
| `recintos_catalogo.json` | **generado** por el plugin, no a mano |
