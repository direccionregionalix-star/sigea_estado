"""
Devolver asignación (Pieza 7) — diálogo y orquestación compartida.

Usado tanto por el panel del funcionario (devuelve su propia asignación) como
por el modo admin (devuelve en nombre de un funcionario, p.ej. limpieza de
estado contaminado).

Dos modos:
  - SIN guardar avance: el recinto vuelve a "pendiente" como si nunca se hubiera
    asignado. La copia local de trabajo se respalda en _historico/ vía sesion.py
    (no se duplica esa lógica) y se libera. Funcionario queda liberado=True.
  - CON avance guardado: el gpkg se conserva en Devueltos/ (mismo patrón que
    entregar_a_qa). El recinto queda "devuelto_con_avance" esperando reasignación
    a cualquier funcionario, que continúa desde ese gpkg. Funcionario liberado.

En ambos modos se registra un evento "devolucion" en bitácora.
REGLA: estado.json / bitácora solo metadata — el detalle nunca lleva RUTs,
direcciones ni coordenadas. El padrón no se agrega ni elimina: devolver con
avance conserva el gpkg tal cual, no lo recalcula.
"""
import json
import base64
from datetime import datetime, timezone

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QRadioButton, QButtonGroup,
    QLineEdit, QDialogButtonBox, QGroupBox
)

from . import bitacora, github_report, admin_archivos
from .compat import BtnOk, BtnCancel

try:
    from urllib import request as urllib_request
except ImportError:
    import urllib2 as urllib_request


def _actualizar_estado_devolucion(codigo, usuario, conservar_avance):
    """Lee estado.json y refleja la devolución: funcionario liberado=True y el
    estado del recinto (pendiente / devuelto_con_avance). Reutiliza el mismo
    token/repo (_t/_r/_b) que el resto del plugin vía github_report.
    Devuelve (ok, msg)."""
    try:
        creds = github_report._obtener_credenciales()
    except RuntimeError as e:
        return False, f"Sin credenciales para actualizar estado: {e}"

    repo, branch, token = creds["repo"], creds["branch"], creds["token"]
    url = f"https://api.github.com/repos/{repo}/contents/estado.json?ref={branch}"
    try:
        req = urllib_request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "SIGEA-Plugin")
        with urllib_request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            estado = json.loads(base64.b64decode(data["content"]).decode())
    except Exception as e:
        return False, f"No pude leer estado.json: {e}"

    funcionarios = estado.setdefault("funcionarios", {})
    if usuario not in funcionarios or not funcionarios.get(usuario):
        return False, f"{usuario} no tiene una asignación activa en estado.json."

    if conservar_avance:
        # Mantener el registro del funcionario marcando el flujo y liberándolo.
        f = funcionarios[usuario]
        f["liberado"] = True
        f["estado_flujo"] = "devuelto_con_avance"
        f["conservo_avance"] = True
    else:
        # Como si nunca se hubiera asignado: ranura del funcionario a None.
        funcionarios[usuario] = None

    estado["generado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    contenido = json.dumps(estado, ensure_ascii=False, indent=1)
    try:
        github_report._github_put(repo, branch, "estado.json", contenido, token,
                                  f"devolucion {usuario} {codigo} "
                                  f"({'con' if conservar_avance else 'sin'} avance)")
    except Exception as e:
        return False, f"No pude escribir estado.json: {e}"
    return True, "estado.json actualizado."


def ejecutar_devolucion(codigo, usuario, conservar_avance, motivo=""):
    """Orquesta la devolución completa: archivos → estado.json → bitácora.
    Devuelve (ok, mensaje_resumen). Best-effort en bitácora (no bloquea)."""
    # 1) Lado de archivos
    ok_f, msg_f = admin_archivos.devolver_asignacion(codigo, usuario, conservar_avance)
    if not ok_f:
        return False, f"Archivos: {msg_f}"

    # 2) estado.json
    ok_e, msg_e = _actualizar_estado_devolucion(codigo, usuario, conservar_avance)
    if not ok_e:
        return False, f"{msg_f} PERO estado no actualizado: {msg_e}"

    # 3) bitácora (best-effort)
    ok_b, msg_b = bitacora.evento_devolucion(codigo, usuario, conservar_avance, motivo)

    resumen = f"Recinto {codigo} devuelto. {msg_f}"
    if not ok_b:
        resumen += f" (bitácora: {msg_b})"
    return True, resumen


class DevolverDialog(QDialog):
    """Pide modo (con/sin avance) y motivo opcional. exec() → Accepted/Rejected.
    Tras Accepted, leer conservar_avance() y motivo()."""
    def __init__(self, codigo, usuario, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Devolver asignación")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel(
            f"<b>Devolver el recinto {codigo}</b> de <b>{usuario}</b>."))

        grp = QGroupBox("¿Conservar el avance?")
        gl = QVBoxLayout(grp)
        self._rb_sin = QRadioButton(
            "Sin guardar avance — el recinto vuelve a pendiente, como si nunca "
            "se hubiera asignado.")
        self._rb_con = QRadioButton(
            "Con avance guardado — conserva el gpkg para reasignar y continuar "
            "el trabajo.")
        self._rb_sin.setChecked(True)
        for rb in (self._rb_sin, self._rb_con):
            rb.setStyleSheet("font-size:11px;")
            gl.addWidget(rb)
        self._grupo = QButtonGroup(self)
        self._grupo.addButton(self._rb_sin)
        self._grupo.addButton(self._rb_con)
        lay.addWidget(grp)

        lay.addWidget(QLabel("Motivo (opcional):"))
        self._txt_motivo = QLineEdit()
        self._txt_motivo.setPlaceholderText("Ej: estado de prueba contaminado")
        lay.addWidget(self._txt_motivo)

        bb = QDialogButtonBox(BtnOk | BtnCancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def conservar_avance(self):
        return self._rb_con.isChecked()

    def motivo(self):
        return self._txt_motivo.text().strip()
