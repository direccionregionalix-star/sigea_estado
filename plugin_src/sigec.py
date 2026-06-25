"""
Cliente SIGEC — geocoding centralizado de Araucanía sobre Supabase.

Usa urllib (no requests) para no depender de paquetes que QGIS podría no
traer. Read-only vía anon key (RLS), segura de embeber.
"""
import json

try:
    from urllib import request as _rq
    from urllib import error as _err
except ImportError:  # py2 fallback (no debería ocurrir en QGIS 3.16+)
    import urllib2 as _rq
    _err = _rq


_BASE = "https://cbqpeusznwotoeftkegw.supabase.co"
_ANON = "sb_publishable_jp4zBRi9mDjZREBckfkyIA_kZ0dcHon"


class SigecError(Exception):
    pass


def _rpc(funcion, payload, timeout=12):
    """Llama a un RPC de Supabase. Devuelve el JSON decodificado."""
    url = f"{_BASE}/rest/v1/rpc/{funcion}"
    data = json.dumps(payload).encode("utf-8")
    req = _rq.Request(url, data=data, method="POST")
    req.add_header("apikey", _ANON)
    req.add_header("Authorization", f"Bearer {_ANON}")
    req.add_header("Content-Type", "application/json")
    try:
        with _rq.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except _err.HTTPError as e:
        raise SigecError(f"SIGEC respondió {e.code}.")
    except Exception as e:
        raise SigecError(f"No se pudo conectar a SIGEC: {e}")


def buscar(comuna, query, limite=20, umbral=0.15):
    """Busca predios por comuna (código SII 4 díg) + fragmento de dirección.
    Devuelve lista de dicts con rol, direccion, lat, lon, geom_geojson, score..."""
    if not comuna or not query or not str(query).strip():
        return []
    res = _rpc("sigec_buscar", {
        "p_comuna": str(comuna),
        "p_query": str(query).strip(),
        "p_limite": int(limite),
        "p_umbral": float(umbral),
    })
    return res if isinstance(res, list) else []


def registrar_seleccion(query, comuna, rol, cliente="sigea"):
    """Registra la selección para el aprendizaje del ranking. Best-effort:
    nunca lanza (no debe interrumpir el flujo si falla)."""
    try:
        _rpc("sigec_registrar_seleccion", {
            "p_query": str(query).strip(),
            "p_comuna": str(comuna),
            "p_rol": str(rol),
            "p_cliente": cliente,
        })
        return True
    except Exception:
        return False
