"""
admin_archivos.py — Operaciones sobre archivos locales para el modo admin.

Responsabilidades:
  - Leer central.gpkg: listar recintos con nombre, comuna y n° electores.
  - Asignar: extraer electores de un recinto del central al gpkg del funcionario.
  - Entregar a QA: copiar gpkg del funcionario a QA_pendiente/.
  - Abrir gpkg de QA en QGIS para revisión visual.
  - Reimportar al central tras aprobación de QA.
  - Cerrar recinto sin asignar (marca en estado, no toca central).

PRINCIPIO: reutiliza sesion.copia_atomica_verificada y sesion._hash_archivo
para toda escritura. NUNCA hardcodea "geom" — usa _col_geom() de gpkg_engine.

Rutas OneDrive (todas bajo dev_007/):
  central.gpkg                    → fuente de verdad
  funcionarios/{usuario}/R{cod}.gpkg  → copia del funcionario
  QA_pendiente/R{cod}.gpkg        → copia para revisión admin
  QA_cerrado/R{cod}_{ts}.gpkg     → archivo post-cierre
  _historico_central/central_{ts}.gpkg  → respaldo del central antes de reimporte
"""
import os
import glob
import sqlite3
import shutil
from datetime import datetime

from . import settings
from .sesion import copia_atomica_verificada, _hash_archivo, _asegurar_dir


# ─── Resolución de rutas ──────────────────────────────────────────────────────

def _carpeta_dev007():
    """Raíz de dev_007 en OneDrive. Se resuelve subiendo un nivel desde
    la carpeta 'funcionarios' configurada."""
    from . import rutas
    base = rutas.carpeta_base()        # …/dev_007/funcionarios
    if not base:
        return None
    parent = os.path.dirname(base)    # …/dev_007
    return parent if os.path.isdir(parent) else None


def ruta_central():
    """Ruta de central.gpkg."""
    dev = _carpeta_dev007()
    return os.path.join(dev, "central.gpkg") if dev else None


def ruta_funcionario(codigo, usuario):
    """Ruta del gpkg del funcionario para este recinto."""
    from . import rutas
    return rutas.ruta_gpkg(codigo, usuario)


def ruta_qa_pendiente(codigo):
    dev = _carpeta_dev007()
    if not dev:
        return None
    return os.path.join(_asegurar_dir(os.path.join(dev, "QA_pendiente")),
                        f"R{codigo}.gpkg")


def ruta_qa_cerrado(codigo):
    dev = _carpeta_dev007()
    if not dev:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(_asegurar_dir(os.path.join(dev, "QA_cerrado")),
                        f"R{codigo}_{ts}.gpkg")


def ruta_historico_central():
    """Carpeta para respaldos del central antes de reimportar."""
    dev = _carpeta_dev007()
    if not dev:
        return None
    return _asegurar_dir(os.path.join(dev, "_historico_central"))


def ruta_devuelto(codigo):
    """Ruta del gpkg conservado al devolver una asignación CON avance.
    Mismo nivel y patrón que QA_pendiente/ — carpeta Devueltos/. Un funcionario
    reasignado continúa desde aquí en vez de extraer uno nuevo del central."""
    dev = _carpeta_dev007()
    if not dev:
        return None
    return os.path.join(_asegurar_dir(os.path.join(dev, "Devueltos")),
                        f"R{codigo}.gpkg")


# ─── Lectura del central ──────────────────────────────────────────────────────

def _col_geom_central(con):
    """Nombre de la columna de geometría del central. NUNCA hardcodear 'geom'."""
    cur = con.execute(
        "SELECT column_name FROM gpkg_geometry_columns LIMIT 1")
    row = cur.fetchone()
    return row[0] if row else "geometry"


def _tabla_features_central(con):
    """Nombre de la tabla de features del central."""
    cur = con.execute(
        "SELECT table_name FROM gpkg_geometry_columns LIMIT 1")
    row = cur.fetchone()
    return row[0] if row else None


def listar_recintos_central(estado=None):
    """Lee central.gpkg y devuelve lista de dicts con:
      {codigo, nombre, comuna, n_electores}
    Si se pasa estado (dict del estado.json), agrega campo 'asignado_a' y
    'estado_recinto' ('pendiente'/'asignado'/'cerrado').
    Devuelve (lista, error_msg). lista=[] si hay error."""
    ruta = ruta_central()
    if not ruta:
        return [], "No se encontró la carpeta dev_007. Configura la carpeta de funcionarios."
    if not os.path.exists(ruta):
        return [], f"No se encontró central.gpkg en {ruta}"

    try:
        con = sqlite3.connect(ruta)
        tabla = _tabla_features_central(con)
        if not tabla:
            con.close()
            return [], "No se encontró tabla de features en central.gpkg"

        # Columnas disponibles (para nombre y comuna puede variar)
        cols_info = con.execute(f"PRAGMA table_info({tabla})").fetchall()
        col_names = {r[1].lower(): r[1] for r in cols_info}

        # Resolver columnas de nombre/recinto y comuna
        col_nombre = (col_names.get("unidad") or col_names.get("nombre_rec")
                      or col_names.get("recinto") or col_names.get("nombre"))
        col_comuna = (col_names.get("comuna") or col_names.get("nombre_comuna"))
        col_codigo = (col_names.get("codigo_rec") or col_names.get("codigo")
                      or col_names.get("cod_rec"))
        # Columna de tipo geográfico para calcular electores sin revisar.
        # sin_revisar = tipo_geo_id IS NULL OR tipo_geo_id IN (8, 9)
        # (8=RECINTO_NO_GEO, 9=SIN_TIPO — tipos no rectificados ni confirmados).
        col_tipo_geo = col_names.get("tipo_geo_id") or col_names.get("revisado_id")

        if not col_codigo:
            con.close()
            return [], "No se encontró columna código de recinto en central.gpkg"

        select_parts = [f'"{col_codigo}"']
        if col_nombre:
            select_parts.append(f'"{col_nombre}"')
        if col_comuna:
            select_parts.append(f'"{col_comuna}"')
        select_parts.append('COUNT(*) as n_electores')
        if col_tipo_geo:
            select_parts.append(
                f'COUNT(CASE WHEN "{col_tipo_geo}" IS NULL '
                f'OR "{col_tipo_geo}" IN (8,9) THEN 1 END) as n_sin_revisar')

        sql = (f"SELECT {', '.join(select_parts)} FROM \"{tabla}\" "
               f"GROUP BY \"{col_codigo}\" ORDER BY \"{col_codigo}\"")
        rows = con.execute(sql).fetchall()
        con.close()

        # Construir mapa de asignaciones desde estado
        asig_map = {}      # codigo → usuario (asignado / en_qa)
        cerrado_set = set()
        devuelto_map = {}  # codigo → usuario que devolvió con avance (Pieza 7)
        if estado:
            for usuario, asig in estado.get("funcionarios", {}).items():
                if asig and asig.get("codigo"):
                    cod = str(asig["codigo"])
                    flujo = asig.get("estado_flujo")
                    if asig.get("estado") == "cerrado":
                        cerrado_set.add(cod)
                    elif flujo == "devuelto_con_avance":
                        # Recinto devuelto conservando avance: queda disponible
                        # para reasignación (continúa desde Devueltos/), no ocupa.
                        devuelto_map[cod] = usuario
                    else:
                        # Asignado normal o liberado en_qa (sigue ocupando).
                        # Una devolución SIN avance deja la ranura en None, así
                        # que aquí no aparece y el recinto vuelve a pendiente.
                        asig_map[cod] = usuario

        resultado = []
        for row in rows:
            idx = 0
            codigo = str(row[idx]); idx += 1
            nombre = str(row[idx]) if col_nombre else "—"; idx += (1 if col_nombre else 0)
            comuna = str(row[idx]) if col_comuna else "—"; idx += (1 if col_comuna else 0)
            n_electores = row[idx]; idx += 1
            n_sin_revisar = row[idx] if col_tipo_geo else n_electores

            if codigo in cerrado_set:
                est = "cerrado"
                asig_a = None
            elif codigo in devuelto_map:
                est = "devuelto"
                asig_a = devuelto_map[codigo]
            elif codigo in asig_map:
                est = "asignado"
                asig_a = asig_map[codigo]
            else:
                est = "pendiente"
                asig_a = None

            resultado.append({
                "codigo": codigo,
                "nombre": nombre,
                "comuna": comuna,
                "n_electores": n_electores,
                "n_sin_revisar": n_sin_revisar,
                "estado_recinto": est,
                "asignado_a": asig_a,
            })
        return resultado, None

    except sqlite3.Error as e:
        return [], f"Error leyendo central.gpkg: {e}"


# ─── Asignar: extraer recinto del central al gpkg del funcionario ─────────────

def _gpkg_vacio(ruta, tabla, col_geom, col_names_tipos):
    """Crea un gpkg vacío con el mismo esquema que central pero solo para
    un recinto. col_names_tipos: lista de (nombre_col, tipo_sqlite)."""
    if os.path.exists(ruta):
        os.remove(ruta)
    con = sqlite3.connect(ruta)
    # FIRMA GEOPACKAGE: sin esto QGIS rechaza el archivo con
    # "bad application_id=0x00000000". Debe ir ANTES de crear tablas.
    # 1196444487 = 0x47504B47 = "GPKG" en ASCII. user_version = GPKG 1.2.1.
    con.execute("PRAGMA application_id = 1196444487")
    con.execute("PRAGMA user_version = 10201")
    # Tablas mínimas requeridas por GeoPackage
    con.executescript("""
        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL, description TEXT);
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys VALUES
            ('WGS 84 geodetic',4326,'EPSG',4326,
             'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],
              PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]','WGS84');
        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL, identifier TEXT,
            description TEXT DEFAULT '', last_change DATETIME,
            min_x REAL, min_y REAL, max_x REAL, max_y REAL,
            srs_id INTEGER);
        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name TEXT NOT NULL, column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL, m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));
    """)
    # Tabla de features
    col_defs = [f'"{n}" {t}' for n, t in col_names_tipos]
    con.execute(f'CREATE TABLE "{tabla}" (fid INTEGER PRIMARY KEY AUTOINCREMENT, '
                f'"{col_geom}" BLOB, {", ".join(col_defs)})')
    con.execute(f'INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)',
                (tabla, col_geom, "POINT", 4326, 0, 0))
    con.execute('INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)',
                (tabla, "features", tabla, "", datetime.now().isoformat(), None, None, None, None, 4326))
    con.commit()
    con.close()


def extraer_recinto_para_funcionario(codigo, usuario):
    """Extrae los electores del recinto {codigo} del central.gpkg y crea
    (o sobreescribe) funcionarios/{usuario}/R{codigo}.gpkg.
    Devuelve (ok, msg)."""
    ruta_c = ruta_central()
    if not ruta_c or not os.path.exists(ruta_c):
        return False, "No se encontró central.gpkg"

    ruta_dest = ruta_funcionario(codigo, usuario)
    if not ruta_dest:
        return False, "No se pudo resolver la ruta de destino del funcionario."

    _asegurar_dir(os.path.dirname(ruta_dest))

    try:
        con_c = sqlite3.connect(ruta_c)
        col_geom = _col_geom_central(con_c)
        tabla = _tabla_features_central(con_c)
        if not tabla:
            con_c.close()
            return False, "No se encontró tabla de features en central.gpkg"

        # Columnas no-geometría (excluye fid propio — se preserva como fid_central)
        cols_info = con_c.execute(f"PRAGMA table_info(\"{tabla}\")").fetchall()
        col_names_tipos = [(r[1], r[2]) for r in cols_info
                           if r[1].lower() not in (col_geom.lower(), "fid",
                                                   "fid_central")]

        col_codigo = next(
            (n for n, _ in col_names_tipos
             if n.lower() in ("codigo_rec", "codigo", "cod_rec")), None)
        if not col_codigo:
            con_c.close()
            return False, "No se encontró columna código en central.gpkg"

        # Seleccionar electores del recinto; incluye fid del central para el reimporte
        all_cols = ['"fid"'] + [f'"{col_geom}"'] + [f'"{n}"' for n, _ in col_names_tipos]
        rows = con_c.execute(
            f'SELECT {", ".join(all_cols)} FROM "{tabla}" '
            f'WHERE "{col_codigo}" = ?', (codigo,)
        ).fetchall()
        con_c.close()

        if not rows:
            return False, f"No se encontraron electores para recinto {codigo} en el central."

        # El esquema destino incluye fid_central (INTEGER) para poder reimportar
        # actualizando el registro correcto por fid en el central.gpkg.
        col_names_tipos_dest = [("fid_central", "INTEGER")] + col_names_tipos

        # Crear gpkg destino vacío con el mismo esquema
        tmp_dest = ruta_dest + ".tmp_asig"
        _gpkg_vacio(tmp_dest, tabla, col_geom, col_names_tipos_dest)

        con_d = sqlite3.connect(tmp_dest)
        # INSERT: fid_central, geom, resto de columnas (fid del src va a fid_central)
        insert_cols = ['"fid_central"', f'"{col_geom}"'] + [f'"{n}"' for n, _ in col_names_tipos]
        placeholders = ", ".join(["?"] * len(insert_cols))
        con_d.executemany(
            f'INSERT INTO "{tabla}" ({", ".join(insert_cols)}) VALUES ({placeholders})',
            rows)
        con_d.commit()
        con_d.close()

        # Copia atómica + verificación
        ok, msg = copia_atomica_verificada(tmp_dest, ruta_dest)
        try:
            os.remove(tmp_dest)
        except OSError:
            pass
        if not ok:
            return False, f"Fallo al escribir gpkg del funcionario: {msg}"

        return True, (f"R{codigo}.gpkg creado para {usuario} con {len(rows)} electores. "
                      f"Hash verificado.")

    except sqlite3.Error as e:
        return False, f"Error SQLite al extraer recinto: {e}"


# ─── Entregar a QA_pendiente ──────────────────────────────────────────────────

def entregar_a_qa(codigo, usuario):
    """Copia el gpkg del funcionario a QA_pendiente/R{codigo}.gpkg.
    Respalda si ya existe uno en QA_pendiente (hereda regla jmedina).
    Devuelve (ok, msg)."""
    origen = ruta_funcionario(codigo, usuario)
    if not origen or not os.path.exists(origen):
        return False, f"No se encontró R{codigo}.gpkg del funcionario {usuario}."

    qa_dest = ruta_qa_pendiente(codigo)
    if not qa_dest:
        return False, "No se pudo resolver la ruta QA_pendiente."

    # Respaldar el que ya estuviera en QA antes de sobrescribir
    if os.path.exists(qa_dest):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bk_dir = _asegurar_dir(os.path.join(os.path.dirname(qa_dest), "_respaldos"))
        bk = os.path.join(bk_dir, f"R{codigo}_{ts}.gpkg")
        try:
            shutil.copy2(qa_dest, bk)
        except OSError:
            pass   # respaldo best-effort; la entrega sigue

    ok, msg = copia_atomica_verificada(origen, qa_dest)
    if not ok:
        return False, (f"Falló la copia a QA_pendiente: {msg}. "
                       "El trabajo del funcionario sigue intacto.")
    return True, f"R{codigo}.gpkg entregado a QA_pendiente. SHA-256 verificado."


# ─── Devolver asignación (Pieza 7) ───────────────────────────────────────────

def devolver_asignacion(codigo, usuario, conservar_avance):
    """Lado de ARCHIVOS de una devolución. NO toca estado.json ni bitácora —
    eso lo hace la capa de UI. Devuelve (ok, msg).

    conservar_avance=True:
        Conserva el gpkg del funcionario en Devueltos/R{codigo}.gpkg con el
        mismo patrón que entregar_a_qa (respaldo previo si existe + copia
        atómica verificada con SHA-256). Queda listo para reasignación.

    conservar_avance=False:
        Respalda y libera la copia LOCAL de trabajo reutilizando
        sesion.limpiar_local (_historico/). No duplica esa lógica. Es no-op
        seguro si no hay copia local en este PC (caso admin-en-nombre-de)."""
    if conservar_avance:
        origen = ruta_funcionario(codigo, usuario)
        if not origen or not os.path.exists(origen):
            return False, (f"No se encontró R{codigo}.gpkg de {usuario} para "
                           "conservar el avance.")
        destino = ruta_devuelto(codigo)
        if not destino:
            return False, "No se pudo resolver la carpeta Devueltos."
        # Respaldar el devuelto previo antes de sobrescribir (regla jmedina)
        if os.path.exists(destino):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bk_dir = _asegurar_dir(os.path.join(os.path.dirname(destino), "_respaldos"))
            try:
                shutil.copy2(destino, os.path.join(bk_dir, f"R{codigo}_{ts}.gpkg"))
            except OSError:
                pass
        ok, msg = copia_atomica_verificada(origen, destino)
        if not ok:
            return False, (f"Falló al conservar el avance en Devueltos: {msg}. "
                           "El gpkg del funcionario sigue intacto.")
        return True, f"Avance conservado en Devueltos/R{codigo}.gpkg. SHA-256 verificado."

    # Sin avance: respaldar a _historico/ y soltar la copia local activa.
    from . import sesion
    if sesion.limpiar_local(codigo):
        return True, ("Copia local respaldada en _historico/ y liberada "
                      "(sin conservar avance).")
    return False, "No se pudo respaldar/limpiar la copia local de trabajo."


def preparar_gpkg_asignacion(codigo, usuario):
    """Prepara el gpkg de trabajo al asignar. Si hay un gpkg devuelto con avance
    para este recinto, lo reutiliza (continúa el trabajo). Si no, lo extrae
    nuevo del central. Devuelve (ok, msg, origen) con origen='devuelto'|'central'."""
    devuelto = ruta_devuelto(codigo)
    if devuelto and os.path.exists(devuelto):
        ruta_dest = ruta_funcionario(codigo, usuario)
        if not ruta_dest:
            return False, "No se pudo resolver la ruta del funcionario.", "devuelto"
        _asegurar_dir(os.path.dirname(ruta_dest))
        ok, msg = copia_atomica_verificada(devuelto, ruta_dest)
        if not ok:
            return False, f"Falló al continuar desde el avance devuelto: {msg}", "devuelto"
        return True, (f"Continúa desde el avance devuelto (Devueltos/R{codigo}.gpkg). "
                      "SHA-256 verificado."), "devuelto"
    ok, msg = extraer_recinto_para_funcionario(codigo, usuario)
    return ok, msg, "central"


# ─── Listar gpkg en QA_pendiente ─────────────────────────────────────────────

def listar_qa_pendiente():
    """Devuelve lista de códigos de recinto disponibles en QA_pendiente."""
    dev = _carpeta_dev007()
    if not dev:
        return []
    qa_dir = os.path.join(dev, "QA_pendiente")
    if not os.path.isdir(qa_dir):
        return []
    return [os.path.basename(f)[1:-5]   # R{codigo}.gpkg → codigo
            for f in glob.glob(os.path.join(qa_dir, "R*.gpkg"))]


# ─── Reimporte al central ─────────────────────────────────────────────────────

def _respaldar_central():
    """Copia central.gpkg a _historico_central/ con timestamp.
    Devuelve (ok, ruta_respaldo_o_msg)."""
    ruta_c = ruta_central()
    if not ruta_c or not os.path.exists(ruta_c):
        return False, "No se encontró central.gpkg para respaldar."
    hist = ruta_historico_central()
    if not hist:
        return False, "No se pudo resolver la carpeta _historico_central."
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(hist, f"central_{ts}.gpkg")
    ok, msg = copia_atomica_verificada(ruta_c, dest)
    if not ok:
        return False, f"Fallo al respaldar central: {msg}"
    return True, dest


def reimportar_al_central(codigo):
    """Toma QA_pendiente/R{codigo}.gpkg y actualiza los registros correspondientes
    en central.gpkg (UPDATE por fid/codigo_rec). Respalda el central ANTES.
    Devuelve (ok, msg)."""
    ruta_qa = ruta_qa_pendiente(codigo)
    if not ruta_qa or not os.path.exists(ruta_qa):
        return False, f"No se encontró QA_pendiente/R{codigo}.gpkg"

    ruta_c = ruta_central()
    if not ruta_c or not os.path.exists(ruta_c):
        return False, "No se encontró central.gpkg"

    # PASO 1: respaldar el central — obligatorio antes de cualquier escritura
    ok_bk, msg_bk = _respaldar_central()
    if not ok_bk:
        return False, f"No se pudo respaldar el central. Reimporte cancelado: {msg_bk}"

    try:
        con_qa = sqlite3.connect(ruta_qa)
        con_c = sqlite3.connect(ruta_c)

        col_geom_c = _col_geom_central(con_c)
        tabla_c = _tabla_features_central(con_c)

        col_geom_qa = _col_geom_central(con_qa)
        tabla_qa = _tabla_features_central(con_qa)

        if not tabla_c or not tabla_qa:
            con_qa.close(); con_c.close()
            return False, "No se encontró tabla de features."

        # Columnas editables (excluir fid propio y geometría)
        cols_qa = con_qa.execute(f'PRAGMA table_info("{tabla_qa}")').fetchall()
        col_names_qa = [r[1] for r in cols_qa
                        if r[1].lower() not in (col_geom_qa.lower(), "fid")]

        # fid_central es la clave de actualización (preservada durante la extracción).
        # Fallback: si el gpkg QA es antiguo (sin fid_central), usamos codigo_rec
        # con advertencia — actualizará todos los registros del recinto a la vez
        # (comportamiento incorrecto para geo por elector, pero no rompe el proceso).
        usa_fid_central = "fid_central" in col_names_qa
        if not usa_fid_central:
            col_codigo = next(
                (n for n in col_names_qa
                 if n.lower() in ("codigo_rec", "codigo", "cod_rec")), None)
            if not col_codigo:
                con_qa.close(); con_c.close()
                return False, "No se encontró fid_central ni columna código en QA gpkg."

        # Leer todos los registros del gpkg QA
        all_cols = [f'"{col_geom_qa}"'] + [f'"{n}"' for n in col_names_qa]
        rows_qa = con_qa.execute(
            f'SELECT {", ".join(all_cols)} FROM "{tabla_qa}"'
        ).fetchall()
        con_qa.close()

        # Mapear col_nombre → índice en row_qa (0=geom, 1..n = cols)
        col_idx = {n: i + 1 for i, n in enumerate(col_names_qa)}

        # Columnas actualizables en el central (las que existen en ambos lados,
        # excepto la clave de join y fid_central que es solo del gpkg de trabajo)
        cols_c_info = con_c.execute(f'PRAGMA table_info("{tabla_c}")').fetchall()
        col_names_c = {r[1] for r in cols_c_info}

        excluir = {"fid_central"}
        if not usa_fid_central:
            excluir.add(col_codigo)
        cols_update = [n for n in col_names_qa
                       if n in col_names_c and n.lower() not in excluir]

        actualizados = 0
        for row in rows_qa:
            geom_val = row[0]
            set_parts = [f'"{col_geom_c}" = ?'] + [f'"{c}" = ?' for c in cols_update]
            vals = [geom_val] + [row[col_idx[c]] for c in cols_update]

            if usa_fid_central:
                # Actualización precisa: 1 elector por fid
                fid_val = row[col_idx["fid_central"]]
                updated = con_c.execute(
                    f'UPDATE "{tabla_c}" SET {", ".join(set_parts)} '
                    f'WHERE fid = ?', vals + [fid_val]
                ).rowcount
            else:
                # Fallback: actualiza TODOS los registros del recinto (impreciso)
                codigo_val = row[col_idx[col_codigo]]
                updated = con_c.execute(
                    f'UPDATE "{tabla_c}" SET {", ".join(set_parts)} '
                    f'WHERE "{col_codigo}" = ?', vals + [codigo_val]
                ).rowcount
            actualizados += updated

        con_c.commit()
        con_c.close()

        return True, (f"Reimporte completado: {actualizados} registros actualizados "
                      f"en central.gpkg. Respaldo guardado en _historico_central/.")

    except sqlite3.Error as e:
        return False, f"Error SQLite en reimporte: {e}"


def mover_qa_a_cerrado(codigo):
    """Mueve QA_pendiente/R{codigo}.gpkg a QA_cerrado/ con timestamp."""
    qa = ruta_qa_pendiente(codigo)
    if not qa or not os.path.exists(qa):
        return True, "No había archivo en QA_pendiente."
    dest = ruta_qa_cerrado(codigo)
    if not dest:
        return False, "No se pudo resolver ruta QA_cerrado."
    try:
        shutil.move(qa, dest)
        return True, f"Movido a QA_cerrado: {os.path.basename(dest)}"
    except OSError as e:
        return False, f"No se pudo mover a QA_cerrado: {e}"
