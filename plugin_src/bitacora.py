"""
Escritura append-only a bitacora.json en el repo GitHub.

Nunca reescribe líneas pasadas: lee el array "eventos", agrega al final,
y sube con el SHA correcto. Reintenta en 409 (conflicto de SHA).

El repo destino se toma del mismo "_r" que usa el plugin para estado.json
(via github_report._obtener_credenciales). Mismo token "_t".

REGLA CRÍTICA: detalle nunca lleva RUTs, direcciones ni coordenadas.
Solo conteos y metadata de proceso. Validar antes de llamar.
"""
import json
import base64
from datetime import datetime, timezone

from . import github_report  # reutiliza _obtener_credenciales y _github_get


_RUTA = "bitacora.json"
_MAX_REINTENTOS = 3


def _github_get_raw(repo, branch, path, token):
    """Devuelve (contenido_dict, sha) del archivo en GitHub, o ({eventos:[]}, None) si no existe."""
    from urllib import request as urllib_request, error as urllib_error
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    req = urllib_request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "SIGEA-Plugin")
    try:
        with urllib_request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            contenido = json.loads(base64.b64decode(data["content"]).decode())
            return contenido, data["sha"]
    except urllib_error.HTTPError as e:
        if e.code == 404:
            return {"eventos": []}, None
        raise


def _github_put_raw(repo, branch, path, contenido_dict, token, sha, mensaje):
    """Sube el archivo. sha=None para creación. Lanza HTTPError en conflicto (409)."""
    from urllib import request as urllib_request
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    contenido_b64 = base64.b64encode(
        json.dumps(contenido_dict, ensure_ascii=False, indent=1).encode()
    ).decode()
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


def registrar(tipo, recinto, funcionario, detalle):
    """Agrega un evento a bitacora.json en el repo.
    Reintenta hasta _MAX_REINTENTOS veces en caso de conflicto de SHA (409).
    Devuelve (ok, mensaje)."""
    try:
        creds = github_report._obtener_credenciales()
    except RuntimeError as e:
        return False, f"Sin credenciales para bitácora: {e}"

    evento = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tipo": tipo,
        "recinto": recinto,
        "funcionario": funcionario,
        "detalle": detalle,
    }

    from urllib import error as urllib_error
    for intento in range(_MAX_REINTENTOS):
        try:
            bitacora, sha = _github_get_raw(
                creds["repo"], creds["branch"], _RUTA, creds["token"])
            bitacora.setdefault("eventos", []).append(evento)
            _github_put_raw(
                creds["repo"], creds["branch"], _RUTA, bitacora,
                creds["token"], sha,
                f"bitacora {tipo} {funcionario} {recinto}")
            return True, f"Evento '{tipo}' registrado en bitácora."
        except urllib_error.HTTPError as e:
            if e.code == 409 and intento < _MAX_REINTENTOS - 1:
                continue  # SHA desactualizado — reintentar
            return False, f"Error HTTP {e.code} escribiendo bitácora: {e}"
        except Exception as e:
            return False, f"Error escribiendo bitácora: {e}"

    return False, "No se pudo escribir a bitácora tras varios intentos."


# ── helpers por tipo de evento ──────────────────────────────────────────────

def evento_asignacion(recinto, funcionario, asignado_por):
    return registrar("asignacion", recinto, funcionario,
                     {"asignado_por": asignado_por})


def evento_avance(recinto, funcionario, confirmados, confirmados_total, total, pct):
    detalle = {k.lower(): v for k, v in confirmados.items()}
    detalle.update({"total": total, "pct": pct})
    return registrar("avance", recinto, funcionario, detalle)


def evento_entrega(recinto, funcionario, confirmados, confirmados_total, total, pct):
    detalle = {k.lower(): v for k, v in confirmados.items()}
    detalle.update({"total": total, "pct": pct})
    return registrar("entrega", recinto, funcionario, detalle)


def evento_qa(recinto, funcionario, resultado, comentario=""):
    return registrar("qa", recinto, funcionario,
                     {"resultado": resultado, "comentario": comentario})


def evento_cierre(recinto, funcionario, cerrado_por):
    return registrar("cierre", recinto, funcionario,
                     {"cerrado_por": cerrado_por})


def evento_mail(recinto, funcionario, destinatario, asunto, enviado):
    return registrar("mail", recinto, funcionario,
                     {"destinatario": destinatario, "asunto": asunto,
                      "enviado": enviado})


def evento_alerta_tipo(recinto, funcionario, tipo_detectado):
    return registrar("alerta_tipo", recinto, funcionario,
                     {"tipo_detectado": tipo_detectado, "recinto": recinto})
