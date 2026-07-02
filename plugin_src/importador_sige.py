"""
importador_sige.py — Importador de entregas SIGE (xlsx) al flujo SIGEA.

Funcionarios que trabajan en SIGE web (ej. pfigueroa) entregan
{recinto}_ENTREGA.xlsx (hoja "Entrega_QA") + _ENTREGA.geojson en su
carpeta OneDrive. Este módulo escanea, valida e integra esas entregas al
mismo flujo QA_pendiente / estado.json / bitácora del plugin QGIS.

DECISIÓN ARQUITECTURAL (no cambiar sin autorización del Director):
  Mail en SIMULACIÓN. server.js existe pero Railway no está montado en
  este sprint. Se llama evento_mail() con enviado=False. El servidor real
  se monta en un sprint aparte.

REGLA: detalle de bitácora = solo conteos numéricos y metadata de proceso.
  run, coordenadas y direcciones NUNCA salen a GitHub.

LECTOR XLSX: stdlib pura (zipfile + xml.etree). Sin openpyxl ni deps
  externas. Maneja inlineStr y sharedStrings.
"""
import os
import re
import glob
import json
import shutil
import base64
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from . import bitacora, github_report
from .admin_archivos import _carpeta_dev007, _asegurar_dir
from .sesion import copia_atomica_verificada

_SS_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_TIPOS_VALIDOS = {1, 2, 3, 4}   # LOCALIDAD, EXACTO, CALLE, NO_GEO


# ─── Lector XLSX ─────────────────────────────────────────────────────────────

def _col_num(ref):
    """Convierte referencia de columna ('A', 'BC') a índice 0-based."""
    letters = ''.join(c for c in ref if c.isalpha())
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def leer_entrega_xlsx(ruta):
    """Lee la hoja 'Entrega_QA' de un xlsx con stdlib pura.
    Maneja inlineStr y sharedStrings. Mapea la hoja por nombre real.
    Devuelve (headers: list[str], filas: list[dict]).
    Lanza ValueError si no encuentra la hoja."""
    with zipfile.ZipFile(ruta) as zf:
        names = set(zf.namelist())

        # 1. Shared strings (la mayoría de xlsx reales los usan)
        shared = []
        if 'xl/sharedStrings.xml' in names:
            root = ET.parse(zf.open('xl/sharedStrings.xml')).getroot()
            for si in root.findall(f'{{{_SS_NS}}}si'):
                parts = si.findall(f'.//{{{_SS_NS}}}t')
                shared.append(''.join(p.text or '' for p in parts))

        # 2. Mapear hoja "Entrega_QA" → path en el zip
        wb_root = ET.parse(zf.open('xl/workbook.xml')).getroot()
        rid_target = {}
        rels_path = 'xl/_rels/workbook.xml.rels'
        if rels_path in names:
            for rel in ET.parse(zf.open(rels_path)).getroot():
                rid_target[rel.get('Id', '')] = rel.get('Target', '')

        sheet_path = None
        for sh in wb_root.findall(f'.//{{{_SS_NS}}}sheet'):
            if sh.get('name', '').strip().lower() == 'entrega_qa':
                rid = sh.get(f'{{{_REL_NS}}}id', '')
                target = rid_target.get(rid, '')
                if target and not target.startswith('xl/'):
                    target = 'xl/' + target
                if target in names:
                    sheet_path = target
                break

        if not sheet_path:
            raise ValueError("No se encontró la hoja 'Entrega_QA' en el archivo.")

        # 3. Extraer valores de celdas
        def cell_val(c):
            t = c.get('t', '')
            v = c.find(f'{{{_SS_NS}}}v')
            is_el = c.find(f'{{{_SS_NS}}}is')
            if t == 'inlineStr' and is_el is not None:
                return ''.join(x.text or ''
                               for x in is_el.findall(f'.//{{{_SS_NS}}}t'))
            if t == 's':
                idx = int(v.text) if v is not None and v.text else 0
                return shared[idx] if idx < len(shared) else ''
            return v.text if v is not None else None

        raw_rows = []
        ws_root = ET.parse(zf.open(sheet_path)).getroot()
        for row in ws_root.findall(f'.//{{{_SS_NS}}}row'):
            rd = {}
            for c in row.findall(f'{{{_SS_NS}}}c'):
                ref = c.get('r', '')
                if ref:
                    rd[_col_num(ref)] = cell_val(c)
            raw_rows.append(rd)

    if not raw_rows:
        return [], []

    max_col = max((max(rd.keys(), default=0) for rd in raw_rows), default=0)
    header_rd = raw_rows[0]
    headers = [(header_rd.get(i) or '').strip() for i in range(max_col + 1)]

    filas = []
    for rd in raw_rows[1:]:
        if not any(v is not None for v in rd.values()):
            continue
        fila = {headers[i]: rd.get(i)
                for i in range(len(headers)) if headers[i]}
        filas.append(fila)

    return headers, filas


# ─── Validación ──────────────────────────────────────────────────────────────

def _num(val, tipo=float):
    """Convierte val a número. Devuelve None si no es convertible."""
    if val is None or str(val).strip() == '':
        return None
    try:
        return tipo(str(val).strip().replace(',', '.'))
    except (ValueError, TypeError):
        return None


def validar_entrega_sige(filas):
    """Valida las filas de la entrega SIGE.
    Agrega campos '_estado_fila' y '_nota' a cada fila (no van a GitHub).
    Estados: 'ok' | 'excepcion' | 'pendiente'.
    Reglas:
      - run vacío → 'excepcion' (NUNCA descartar la fila)
      - lat/lon nulo → 'pendiente'
      - tipo_geo_id=4 → coordenadas originales conservadas tal cual
      - tipo_geo_id fuera de 1-4 → alertar (no bloquea)
    Devuelve (filas_anotadas, resumen_dict)."""
    validadas = []
    n_exc = n_pend = n_ok = 0
    tipos_invalidos = set()

    for raw in filas:
        f = dict(raw)
        run = _num(f.get('run'), int)
        tipo_id = _num(f.get('tipo_geo_id'), int)
        lat = _num(f.get('latitud'))
        lon = _num(f.get('longitud'))

        if run is None:
            f['_estado_fila'] = 'excepcion'
            f['_nota'] = 'run vacío'
            n_exc += 1
        elif lat is None or lon is None:
            f['_estado_fila'] = 'pendiente'
            f['_nota'] = 'lat/lon nulo'
            n_pend += 1
        else:
            f['_estado_fila'] = 'ok'
            f['_nota'] = ''
            n_ok += 1

        if tipo_id is not None and tipo_id not in _TIPOS_VALIDOS:
            tipos_invalidos.add(tipo_id)

        validadas.append(f)

    return validadas, {
        'total':          len(filas),
        'ok':             n_ok,
        'pendiente':      n_pend,
        'excepcion':      n_exc,
        'tipos_invalidos': sorted(tipos_invalidos),
    }


def _conteos_bitacora(filas):
    """Conteos por tipo_geo_id para bitácora: solo metadata numérica, sin datos sensibles."""
    c = {1: 0, 2: 0, 3: 0, 4: 0}
    for f in filas:
        tid = _num(f.get('tipo_geo_id'), int)
        if tid in c:
            c[tid] += 1
    return {'localidad': c[1], 'exacto': c[2], 'calle': c[3], 'no_geo': c[4]}


# ─── Escaneo ─────────────────────────────────────────────────────────────────

def escanear_entregas_sige(bitacora_cache=None):
    """Escanea dev_007/funcionarios/*/{recinto}_ENTREGA.xlsx.
    Compara contra bitacora.json: retorna solo entregas SIN evento
    tipo='entrega' con detalle.origen='sige' para ese (recinto, usuario).
    bitacora_cache: dict {'eventos': [...]} ya leído; si None lo lee de GitHub.
    Devuelve lista de dicts {recinto, usuario, ruta_xlsx, ts_archivo}."""
    dev = _carpeta_dev007()
    if not dev:
        return []
    func_dir = os.path.join(dev, 'funcionarios')
    if not os.path.isdir(func_dir):
        return []

    # Leer bitácora para filtrar lo ya procesado
    procesados = set()
    try:
        if bitacora_cache is None:
            creds = github_report._obtener_credenciales()
            from urllib import request as _req
            url = (f"https://api.github.com/repos/{creds['repo']}/contents/"
                   f"bitacora.json?ref={creds['branch']}")
            req = _req.Request(url)
            req.add_header("Authorization", f"Bearer {creds['token']}")
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "SIGEA-Plugin")
            with _req.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
                bitacora_cache = json.loads(
                    base64.b64decode(data['content']).decode())
        for ev in (bitacora_cache or {}).get('eventos', []):
            if (ev.get('tipo') == 'entrega'
                    and (ev.get('detalle') or {}).get('origen') == 'sige'):
                procesados.add((ev.get('recinto', ''), ev.get('funcionario', '')))
    except Exception:
        pass   # sin bitácora: mostramos todo (best-effort)

    pendientes = []
    for ruta in sorted(glob.glob(os.path.join(func_dir, '*', '*_ENTREGA.xlsx'))):
        usuario = os.path.basename(os.path.dirname(ruta))
        nombre = os.path.basename(ruta)
        m = re.search(r'\d+', nombre)
        if not m:
            continue
        recinto = m.group(0)
        if (recinto, usuario) not in procesados:
            ts = datetime.fromtimestamp(
                os.path.getmtime(ruta)).strftime('%Y-%m-%d %H:%M')
            pendientes.append({
                'recinto':    recinto,
                'usuario':    usuario,
                'ruta_xlsx':  ruta,
                'ts_archivo': ts,
            })
    return pendientes


# ─── Procesamiento ────────────────────────────────────────────────────────────

def _actualizar_estado_sige(recinto, usuario, con_excepciones):
    """Marca funcionario como liberado=True, estado_flujo='en_qa' en estado.json.
    Devuelve (ok, msg)."""
    try:
        creds = github_report._obtener_credenciales()
    except RuntimeError as e:
        return False, f"Sin credenciales: {e}"

    from urllib import request as _req
    repo, branch, token = creds['repo'], creds['branch'], creds['token']
    url = f"https://api.github.com/repos/{repo}/contents/estado.json?ref={branch}"
    try:
        req = _req.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "SIGEA-Plugin")
        with _req.urlopen(req, timeout=10) as r:
            raw = json.loads(r.read().decode())
            sha = raw['sha']
            estado = json.loads(base64.b64decode(raw['content']).decode())
    except Exception as e:
        return False, f"No pude leer estado.json: {e}"

    f_data = estado.get('funcionarios', {}).get(usuario)
    if f_data:
        f_data['liberado'] = True
        f_data['estado_flujo'] = 'en_qa'
        if con_excepciones:
            f_data['entrega_estado'] = 'con_excepciones'
    estado['generado'] = datetime.now(timezone.utc).isoformat(timespec='seconds')

    contenido_b64 = base64.b64encode(
        json.dumps(estado, ensure_ascii=False, indent=1).encode()).decode()
    payload = json.dumps({
        'message': f'sige: entrega {usuario} {recinto}',
        'content': contenido_b64, 'branch': branch, 'sha': sha,
    }).encode()
    try:
        put_req = _req.Request(
            f"https://api.github.com/repos/{repo}/contents/estado.json",
            data=payload, method='PUT')
        put_req.add_header("Authorization", f"Bearer {token}")
        put_req.add_header("Accept", "application/vnd.github+json")
        put_req.add_header("Content-Type", "application/json")
        put_req.add_header("User-Agent", "SIGEA-Plugin")
        with _req.urlopen(put_req, timeout=15):
            pass
        return True, "estado.json actualizado."
    except Exception as e:
        return False, f"No pude escribir estado.json: {e}"


def procesar_entrega_sige(recinto, usuario, ruta_xlsx, filas_validadas):
    """Las 4 acciones del cierre de entrega SIGE — un solo clic.

    1. Copiar xlsx + geojson a QA_pendiente/ (copia_atomica_verificada).
    2. Actualizar estado.json: liberado=True, estado_flujo='en_qa'.
    3. Evento bitácora tipo='entrega', detalle.origen='sige' + conteos.
    4. Evento mail SIMULADO (Railway no montado en este sprint).

    Devuelve (ok, resumen_msg).
    """
    dev = _carpeta_dev007()
    if not dev:
        return False, "No se encontró carpeta dev_007."

    qa_dir = _asegurar_dir(os.path.join(dev, 'QA_pendiente'))
    avisos = []

    # ── 1. Copiar xlsx ────────────────────────────────────────────────────
    dest_xlsx = os.path.join(qa_dir, f'R{recinto}_ENTREGA.xlsx')
    ok_x, msg_x = copia_atomica_verificada(ruta_xlsx, dest_xlsx)
    if not ok_x:
        return False, f"No se pudo copiar xlsx a QA_pendiente: {msg_x}"

    # geojson: best-effort para archivo visual (ArcGIS Pro), no bloquea
    ruta_gj = ruta_xlsx.replace('_ENTREGA.xlsx', '_ENTREGA.geojson')
    tiene_gj = False
    if os.path.exists(ruta_gj):
        try:
            shutil.copy2(ruta_gj, os.path.join(qa_dir, f'R{recinto}_ENTREGA.geojson'))
            tiene_gj = True
        except OSError as e:
            avisos.append(f"geojson no copiado: {e}")

    # ── 2. Estado.json ────────────────────────────────────────────────────
    _, resumen = validar_entrega_sige(filas_validadas)
    con_exc = resumen['excepcion'] > 0
    ok_e, msg_e = _actualizar_estado_sige(recinto, usuario, con_exc)
    if not ok_e:
        avisos.append(f"estado.json: {msg_e}")

    # ── 3. Bitácora (solo metadata numérica — sin run, coords, dir) ───────
    total = resumen['total']
    pct = round(100 * resumen['ok'] / total, 1) if total else 0
    detalle = {
        'origen':     'sige',
        'total':      total,
        'pct':        pct,
        'excepciones': resumen['excepcion'],
        'pendientes': resumen['pendiente'],
        **_conteos_bitacora(filas_validadas),
    }
    ok_b, msg_b = bitacora.registrar('entrega', recinto, usuario, detalle)
    if not ok_b:
        avisos.append(f"bitácora: {msg_b}")

    # ── 4. Mail simulado ──────────────────────────────────────────────────
    # Railway no montado en este sprint — enviado=False siempre.
    # Clave del destinatario = usuario exacto de estado.json (sin transformar).
    asunto = f"[SIGEA] Entrega SIGE recinto {recinto} — {usuario}"
    bitacora.evento_mail(recinto, usuario,
                         destinatario=usuario,
                         asunto=asunto,
                         enviado=False)

    estado_txt = 'con excepciones' if con_exc else 'ok'
    gj_txt = ' + geojson' if tiene_gj else ''
    resumen_txt = (f"Recinto {recinto} entregado ({estado_txt}): "
                   f"{total} filas, {resumen['ok']} ok, "
                   f"{resumen['excepcion']} excepciones. "
                   f"xlsx{gj_txt} copiados a QA_pendiente/.")
    if avisos:
        resumen_txt += f" Avisos: {'; '.join(avisos)}"
    return True, resumen_txt
