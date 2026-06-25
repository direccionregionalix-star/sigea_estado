"""
Cliente HTTP para la API de SIGEA.
Todas las llamadas van aquí — el resto del plugin no sabe nada de HTTP.
"""
import json
from urllib import request, error as urllib_error

from . import settings


class SigeaError(Exception):
    pass


def _get(endpoint):
    url = f"{settings.sigea_url()}{endpoint}"
    try:
        with request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode())
    except urllib_error.URLError as e:
        raise SigeaError(f"No se pudo conectar a SIGEA: {e.reason}")
    except Exception as e:
        raise SigeaError(str(e))


def _post(endpoint, data=None):
    url = f"{settings.sigea_url()}{endpoint}"
    payload = json.dumps(data or {}).encode()
    req = request.Request(url, data=payload,
                          headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib_error.URLError as e:
        raise SigeaError(f"No se pudo conectar a SIGEA: {e.reason}")
    except Exception as e:
        raise SigeaError(str(e))


def ping():
    """Verifica conexión con SIGEA."""
    return _get("/api/ping")


def asignacion_activa(usuario):
    """Devuelve la asignación activa del funcionario o None."""
    try:
        return _get(f"/api/asignacion_activa/{usuario}")
    except SigeaError:
        return None


def registrar_avance(asignacion_id, n_revisados, usuario):
    """Registra un avance en la bitácora de SIGEA."""
    return _post("/api/avance", {
        "asignacion_id": asignacion_id,
        "n_revisados": n_revisados,
        "usuario": usuario,
        "fuente": "qgis_plugin"
    })


def entregar(asignacion_id, usuario, observaciones=""):
    """Registra la entrega de un recinto."""
    return _post("/api/entregar", {
        "asignacion_id": asignacion_id,
        "usuario": usuario,
        "observaciones": observaciones,
        "fuente": "qgis_plugin"
    })


def cargar_gpkg(asignacion_id):
    """Devuelve la ruta del gpkg y el código del recinto."""
    return _get(f"/api/gpkg_path/{asignacion_id}")


def estado_online():
    """Lee el estado.json de Netlify y devuelve la asignación del usuario
    actual: (asig_dict_o_None, generado). Lanza SigeaError si no hay URL o
    no se puede leer."""
    url = settings.estado_url()
    if not url:
        raise SigeaError("Sin URL de estado online configurada.")
    if not url.endswith(".json"):
        url = url + "/estado.json"
    try:
        with request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        raise SigeaError(f"No se pudo leer el estado online: {e}")
    asig = (data.get("funcionarios") or {}).get(settings.usuario())
    if asig is not None:
        # Normalizar al formato que espera el panel
        asig.setdefault("id", asig.get("asignacion_id"))
        asig.setdefault("unidad_nombre", asig.get("unidad"))
        asig.setdefault("avance", asig.get("avance", 0))
        # Normalizar cada asignación de la lista (si viene)
        for a in asig.get("asignaciones", []):
            a.setdefault("id", a.get("asignacion_id"))
            a.setdefault("unidad_nombre", a.get("unidad"))
    return asig, data.get("generado", "")
