"""
Reporte de avance a GitHub desde el plugin QGIS.

El plugin lee el token ofuscado desde el estado.json que SIGEA publica,
lo decodifica, y escribe qgis/{usuario}.json al mismo repo.
Así el funcionario reporta avance directo a GitHub sin necesitar conexión
a SIGEA ni configurar tokens manualmente.
"""
import os
import json
import base64
from datetime import datetime, timezone

from . import settings

try:
    from urllib import request as urllib_request
    from urllib import error as urllib_error
except ImportError:
    import urllib2 as urllib_request
    urllib_error = urllib_request

# Misma clave que usa SIGEA (estado_online.py)
_OBF_KEY = b"SIGEA2026araucania"

# Mapa de tipo_geo_id → nombre legible (exportado para uso en bitacora.py)
NOMBRES = {1: "LOCALIDAD", 2: "EXACTO", 3: "CALLE", 4: "NO_GEO",
           5: "PROXIMIDAD", 6: "FUERA_COMUNA", 7: "AUTOGEO",
           8: "RECINTO_NO_GEO", 9: "SIN_TIPO", 10: "MASIVO"}


def _deofuscar(b64):
    key = _OBF_KEY
    xored = base64.b64decode(b64)
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(xored)).decode()


# Cache del token extraído del estado.json
_token_cache = {"token": None, "repo": None, "branch": None, "ts": None}


def _obtener_credenciales():
    """Lee el token ofuscado del estado.json online. Cachea 10 minutos."""
    ahora = datetime.now()
    if (_token_cache["token"] and _token_cache["ts"] and
            (ahora - _token_cache["ts"]).total_seconds() < 600):
        return _token_cache

    url = settings.estado_url()
    if not url:
        raise RuntimeError("Sin URL de estado online configurada.")
    if not url.endswith(".json"):
        url = url + "/estado.json"

    try:
        req = urllib_request.Request(url)
        req.add_header("User-Agent", "SIGEA-Plugin")
        with urllib_request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        raise RuntimeError(f"No pude leer el estado online: {e}")

    t = data.get("_t")
    repo = data.get("_r")
    branch = data.get("_b", "main")
    if not t or not repo:
        raise RuntimeError("El estado.json no incluye credenciales de escritura. "
                           "Pide al administrador que actualice SIGEA.")
    token = _deofuscar(t)
    _token_cache.update(token=token, repo=repo, branch=branch, ts=ahora)
    return _token_cache


def _github_put(repo, branch, path, contenido_json, token, mensaje):
    """Escribe/actualiza un archivo en el repo vía API de GitHub."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"

    # Obtener SHA actual (si existe)
    sha = None
    try:
        req = urllib_request.Request(f"{url}?ref={branch}")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "SIGEA-Plugin")
        with urllib_request.urlopen(req, timeout=10) as r:
            sha = json.loads(r.read().decode()).get("sha")
    except urllib_error.HTTPError as e:
        if e.code != 404:
            raise
    except Exception:
        pass

    contenido_b64 = base64.b64encode(contenido_json.encode()).decode()
    payload = {"message": mensaje, "content": contenido_b64, "branch": branch}
    if sha:
        payload["sha"] = sha

    data = json.dumps(payload).encode()
    req = urllib_request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "SIGEA-Plugin")
    with urllib_request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def publicar_avance(codigo, conteos, total, metadata_version=""):
    """Publica qgis/{usuario}.json al repo con el avance actual.
    conteos: dict {tipo_geo_id: n} del recinto activo.
    Devuelve (ok, mensaje)."""
    usuario = settings.usuario()
    if not usuario:
        return False, "Sin usuario configurado."

    try:
        creds = _obtener_credenciales()
    except RuntimeError as e:
        return False, str(e)

    # Usar el mapa de módulo (exportado)
    confirmados = {}
    confirmados_total = 0
    for tid, n in conteos.items():
        try:
            tid = int(tid)
        except (ValueError, TypeError):
            continue
        if tid in (8, 9):
            continue  # no cuentan como avance
        nombre = NOMBRES.get(tid, f"TIPO_{tid}")
        confirmados[nombre] = n
        confirmados_total += n

    pendientes = total - confirmados_total
    pct = round(100 * confirmados_total / total, 1) if total else 0

    reporte = {
        "usuario": usuario,
        "recinto_cod": codigo,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "avance": {
            "total_registros": total,
            "confirmados": confirmados,
            "confirmados_total": confirmados_total,
            "pendientes": max(0, pendientes),
            "pct": pct,
        },
        "origen": f"Plugin QGIS{' ' + metadata_version if metadata_version else ''}",
    }

    try:
        contenido = json.dumps(reporte, ensure_ascii=False, indent=1)
        path = f"qgis/{usuario}.json"
        _github_put(creds["repo"], creds["branch"], path, contenido,
                    creds["token"],
                    f"avance {usuario} {codigo} {pct}%")
        return True, f"Avance publicado: {confirmados_total}/{total} ({pct}%)"
    except Exception as e:
        return False, f"Error publicando a GitHub: {e}"
