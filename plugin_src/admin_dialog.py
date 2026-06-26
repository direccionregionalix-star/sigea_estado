"""
Diálogo de administración SIGEA — solo visible si el token tiene push access.

Permite:
  - Ver estado global de todos los funcionarios.
  - Asignar un recinto a un funcionario (actualiza estado.json + bitácora).
  - Marcar QA (aprobado / observado) con alerta si hay tipos geo fuera de dominio.
  - Cerrar un recinto (evento cierre en bitácora).

No toca sesion.py ni gpkg_engine.py. Gestiona ESTADO, no archivos.
"""
import json
import base64
from datetime import datetime, timezone

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialogButtonBox, QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QLineEdit, QTextEdit, QComboBox, QMessageBox, QGroupBox, QFormLayout
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from . import settings, bitacora
from .compat import BtnOk, BtnCancel, DialogAccepted

try:
    from urllib import request as urllib_request, error as urllib_error
except ImportError:
    import urllib2 as urllib_request
    urllib_error = urllib_request

# Tipos geo válidos según dominio SERVEL
_TIPOS_VALIDOS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
_NOMBRES_TIPO = {1: "LOCALIDAD", 2: "EXACTO", 3: "CALLE", 4: "NO_GEO",
                 5: "PROXIMIDAD", 6: "FUERA_COMUNA", 7: "AUTOGEO",
                 8: "RECINTO_NO_GEO", 9: "SIN_TIPO", 10: "MASIVO"}


def _obtener_creds():
    from . import github_report
    return github_report._obtener_credenciales()


def _github_get(repo, branch, path, token):
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    req = urllib_request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "SIGEA-Plugin")
    with urllib_request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
        return json.loads(base64.b64decode(data["content"]).decode()), data["sha"]


def _github_put(repo, branch, path, contenido, token, sha, mensaje):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    b64 = base64.b64encode(
        json.dumps(contenido, ensure_ascii=False, indent=1).encode()
    ).decode()
    payload = {"message": mensaje, "content": b64, "branch": branch}
    if sha:
        payload["sha"] = sha
    data_enc = json.dumps(payload).encode()
    req = urllib_request.Request(url, data=data_enc, method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "SIGEA-Plugin")
    with urllib_request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _leer_reporte_funcionario(repo, branch, token, usuario):
    """Lee qgis/{usuario}.json del repo. Devuelve dict o None."""
    for carpeta in ("qgis", "sige"):
        try:
            data, _ = _github_get(repo, branch, f"{carpeta}/{usuario}.json", token)
            return data
        except Exception:
            pass
    return None


def _detectar_tipos_invalidos(reporte):
    """Devuelve lista de nombres de tipos fuera del dominio conocido."""
    if not reporte:
        return []
    confirmados = reporte.get("avance", {}).get("confirmados", {})
    invalidos = []
    for nombre in confirmados:
        # Buscar si el nombre corresponde a un tipo válido
        if nombre not in _NOMBRES_TIPO.values():
            invalidos.append(nombre)
    return invalidos


class AdminDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SIGEA — Modo Admin")
        self.setMinimumWidth(600)
        self.setMinimumHeight(480)

        try:
            self._creds = _obtener_creds()
        except Exception as e:
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(f"Sin credenciales admin: {e}"))
            lay.addWidget(QDialogButtonBox(BtnOk).accepted.connect(self.accept))
            return

        self._estado = None
        self._estado_sha = None
        self._recargar_estado()

        lay = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(self._tab_estado(), "Estado global")
        tabs.addTab(self._tab_asignar(), "Asignar recinto")
        tabs.addTab(self._tab_qa(), "QA / Cierre")

        lay.addWidget(tabs)
        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.accept)
        lay.addWidget(cerrar)

    # ── Carga de estado ──────────────────────────────────────────────────

    def _recargar_estado(self):
        try:
            self._estado, self._estado_sha = _github_get(
                self._creds["repo"], self._creds["branch"],
                "estado.json", self._creds["token"])
        except Exception as e:
            self._estado = {"funcionarios": {}}
            self._estado_sha = None

    # ── Tab 1: Estado global ─────────────────────────────────────────────

    def _tab_estado(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Estado actual de todos los funcionarios</b>"))

        tabla = QTableWidget()
        tabla.setColumnCount(6)
        tabla.setHorizontalHeaderLabels(
            ["Funcionario", "Recinto", "Comuna", "Avance", "%", "Herramienta"])
        tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        tabla.horizontalHeader().setStretchLastSection(True)

        funcionarios = (self._estado or {}).get("funcionarios", {})
        tabla.setRowCount(len(funcionarios))
        for row, (usuario, asig) in enumerate(funcionarios.items()):
            tabla.setItem(row, 0, QTableWidgetItem(usuario))
            if asig is None:
                tabla.setItem(row, 1, QTableWidgetItem("—"))
                tabla.setItem(row, 2, QTableWidgetItem("Sin asignación"))
                tabla.setItem(row, 3, QTableWidgetItem("—"))
                tabla.setItem(row, 4, QTableWidgetItem("—"))
                tabla.setItem(row, 5, QTableWidgetItem("—"))
            else:
                avance = asig.get("avance", 0)
                total = asig.get("n_electores", 0)
                pct = round(100 * avance / total) if total else 0
                tabla.setItem(row, 1, QTableWidgetItem(asig.get("codigo", "—")))
                tabla.setItem(row, 2, QTableWidgetItem(asig.get("comuna", "—")))
                tabla.setItem(row, 3, QTableWidgetItem(f"{avance} / {total}"))
                pct_item = QTableWidgetItem(f"{pct}%")
                color = QColor("#c8e6c9") if pct >= 80 else (
                    QColor("#fff9c4") if pct >= 40 else QColor("#ffcdd2"))
                pct_item.setBackground(color)
                tabla.setItem(row, 4, pct_item)
                tabla.setItem(row, 5, QTableWidgetItem(asig.get("herramienta", "—")))

        lay.addWidget(tabla)
        gen = (self._estado or {}).get("generado", "—")
        lay.addWidget(QLabel(f'<span style="font-size:10px;color:#888">Estado al: {gen}</span>'))
        return w

    # ── Tab 2: Asignar recinto ───────────────────────────────────────────

    def _tab_asignar(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Asignar recinto a un funcionario</b>"))
        lay.addWidget(QLabel(
            '<span style="color:#666;font-size:10px">'
            'Actualiza estado.json y registra evento en bitácora. '
            'La entrega de archivos gpkg sigue siendo manual (OneDrive).</span>'))

        form = QFormLayout()

        self._cmb_funcionario = QComboBox()
        funcionarios = list((self._estado or {}).get("funcionarios", {}).keys())
        self._cmb_funcionario.addItems(funcionarios)
        form.addRow("Funcionario:", self._cmb_funcionario)

        self._txt_codigo = QLineEdit()
        self._txt_codigo.setPlaceholderText("01274")
        form.addRow("Código recinto:", self._txt_codigo)

        self._txt_unidad = QLineEdit()
        self._txt_unidad.setPlaceholderText("ESCUELA BASICA NAHUELBUTA")
        form.addRow("Nombre recinto:", self._txt_unidad)

        self._txt_comuna = QLineEdit()
        self._txt_comuna.setPlaceholderText("Angol")
        form.addRow("Comuna:", self._txt_comuna)

        self._txt_electores = QLineEdit()
        self._txt_electores.setPlaceholderText("1650")
        form.addRow("N° electores:", self._txt_electores)

        self._txt_fecha = QLineEdit()
        self._txt_fecha.setPlaceholderText("2026-07-15")
        form.addRow("Fecha estimada:", self._txt_fecha)

        lay.addLayout(form)

        self._lbl_asig_msg = QLabel("")
        self._lbl_asig_msg.setWordWrap(True)
        self._lbl_asig_msg.setStyleSheet("font-size:11px;")
        lay.addWidget(self._lbl_asig_msg)

        btn = QPushButton("Asignar recinto")
        btn.setStyleSheet(
            "QPushButton{background:#1565c0;color:white;border:none;"
            "border-radius:4px;padding:6px;font-weight:600;}"
            "QPushButton:hover{background:#1976d2;}")
        btn.clicked.connect(self._asignar)
        lay.addWidget(btn)
        lay.addStretch()
        return w

    def _asignar(self):
        usuario = self._cmb_funcionario.currentText().strip()
        codigo = self._txt_codigo.text().strip()
        unidad = self._txt_unidad.text().strip()
        comuna = self._txt_comuna.text().strip()
        fecha = self._txt_fecha.text().strip()
        try:
            electores = int(self._txt_electores.text().strip())
        except ValueError:
            self._lbl_asig_msg.setText("✗ N° electores debe ser un número.")
            self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        if not all([usuario, codigo, unidad, comuna, fecha]):
            self._lbl_asig_msg.setText("✗ Completa todos los campos.")
            self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        # Calcular días restantes
        try:
            dias = (datetime.strptime(fecha, "%Y-%m-%d").date()
                    - datetime.now().date()).days
        except ValueError:
            self._lbl_asig_msg.setText("✗ Fecha debe ser YYYY-MM-DD.")
            self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        # Construir asignación
        import random
        asig_id = int(datetime.now().timestamp())  # ID único por timestamp
        nueva_asig = {
            "asignacion_id": asig_id,
            "codigo": codigo,
            "unidad": unidad,
            "comuna": comuna,
            "n_electores": electores,
            "fecha_estimada": fecha,
            "dias_restantes": dias,
            "avance": 0,
            "herramienta": "qgis",
            "tipo_origen": "recinto",
            "asignaciones": [{
                "asignacion_id": asig_id,
                "codigo": codigo,
                "unidad": unidad,
                "comuna": comuna,
                "n_electores": electores,
                "fecha_estimada": fecha,
                "dias_restantes": dias,
                "avance": 0,
                "herramienta": "qgis",
                "tipo_origen": "recinto",
            }]
        }

        # Actualizar estado.json en GitHub
        try:
            self._recargar_estado()
            estado = self._estado.copy()
            estado["funcionarios"][usuario] = nueva_asig
            estado["generado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _github_put(
                self._creds["repo"], self._creds["branch"],
                "estado.json", estado, self._creds["token"],
                self._estado_sha,
                f"admin: asignacion {usuario} {codigo}")
        except Exception as e:
            self._lbl_asig_msg.setText(f"✗ Error actualizando estado.json: {e}")
            self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        # Bitácora
        asignado_por = settings.usuario() or "admin"
        ok, msg_bit = bitacora.evento_asignacion(codigo, usuario, asignado_por)

        resultado = f"✓ Recinto {codigo} asignado a {usuario}."
        if not ok:
            resultado += f" (bitácora: {msg_bit})"
        self._lbl_asig_msg.setText(resultado)
        self._lbl_asig_msg.setStyleSheet("color:#2e7d32;font-size:11px;")

    # ── Tab 3: QA / Cierre ───────────────────────────────────────────────

    def _tab_qa(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Control de calidad y cierre de recintos</b>"))

        form = QFormLayout()
        self._cmb_qa_func = QComboBox()
        funcionarios = list((self._estado or {}).get("funcionarios", {}).keys())
        self._cmb_qa_func.addItems(funcionarios)
        self._cmb_qa_func.currentTextChanged.connect(self._verificar_tipos_qa)
        form.addRow("Funcionario:", self._cmb_qa_func)
        lay.addLayout(form)

        # Alerta tipos geo inválidos
        self._lbl_alerta_tipo = QLabel("")
        self._lbl_alerta_tipo.setWordWrap(True)
        self._lbl_alerta_tipo.setStyleSheet(
            "background:#fff3cd;color:#856404;padding:6px;"
            "border-radius:4px;font-size:11px;")
        self._lbl_alerta_tipo.setVisible(False)
        lay.addWidget(self._lbl_alerta_tipo)

        # QA aprobado
        grp_aprobado = QGroupBox("Marcar QA aprobado")
        gl_a = QVBoxLayout(grp_aprobado)
        self._txt_comentario_ok = QLineEdit()
        self._txt_comentario_ok.setPlaceholderText("Comentario opcional...")
        gl_a.addWidget(self._txt_comentario_ok)
        btn_ok = QPushButton("✓ Aprobar")
        btn_ok.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;border:none;"
            "border-radius:4px;padding:5px;font-weight:600;}"
            "QPushButton:hover{background:#388e3c;}")
        btn_ok.clicked.connect(lambda: self._marcar_qa("aprobado"))
        gl_a.addWidget(btn_ok)
        lay.addWidget(grp_aprobado)

        # QA observado
        grp_obs = QGroupBox("Marcar QA observado")
        gl_o = QVBoxLayout(grp_obs)
        self._txt_comentario_obs = QTextEdit()
        self._txt_comentario_obs.setFixedHeight(55)
        self._txt_comentario_obs.setPlaceholderText("Describe la observación...")
        gl_o.addWidget(self._txt_comentario_obs)
        btn_obs = QPushButton("⚠ Observar")
        btn_obs.setStyleSheet(
            "QPushButton{background:#ef6c00;color:white;border:none;"
            "border-radius:4px;padding:5px;font-weight:600;}"
            "QPushButton:hover{background:#f57c00;}")
        btn_obs.clicked.connect(lambda: self._marcar_qa("observado"))
        gl_o.addWidget(btn_obs)
        lay.addWidget(grp_obs)

        # Cierre
        grp_cierre = QGroupBox("Cerrar recinto")
        gl_c = QVBoxLayout(grp_cierre)
        gl_c.addWidget(QLabel(
            '<span style="font-size:10px;color:#666">Registra el cierre '
            'formal del recinto en bitácora. No borra la asignación.</span>'))
        btn_cierre = QPushButton("⬛ Cerrar recinto")
        btn_cierre.setStyleSheet(
            "QPushButton{background:#37474f;color:white;border:none;"
            "border-radius:4px;padding:5px;font-weight:600;}"
            "QPushButton:hover{background:#455a64;}")
        btn_cierre.clicked.connect(self._cerrar_recinto)
        gl_c.addWidget(btn_cierre)
        lay.addWidget(grp_cierre)

        self._lbl_qa_msg = QLabel("")
        self._lbl_qa_msg.setWordWrap(True)
        self._lbl_qa_msg.setStyleSheet("font-size:11px;")
        lay.addWidget(self._lbl_qa_msg)
        lay.addStretch()

        # Verificar al abrir
        self._verificar_tipos_qa()
        return w

    def _verificar_tipos_qa(self):
        """Lee el reporte del funcionario y alerta si hay tipos fuera de dominio."""
        usuario = self._cmb_qa_func.currentText().strip()
        if not usuario:
            return
        try:
            reporte = _leer_reporte_funcionario(
                self._creds["repo"], self._creds["branch"],
                self._creds["token"], usuario)
            invalidos = _detectar_tipos_invalidos(reporte)
            if invalidos:
                recinto = ""
                asig = (self._estado or {}).get("funcionarios", {}).get(usuario)
                if asig:
                    recinto = asig.get("codigo", "")
                msg = (f"⚠ Tipos geo fuera de dominio: {', '.join(invalidos)}"
                       f" en recinto {recinto}. Verificar antes de aprobar.")
                self._lbl_alerta_tipo.setText(msg)
                self._lbl_alerta_tipo.setVisible(True)
                # Registrar alerta en bitácora (best-effort)
                for inv in invalidos:
                    bitacora.evento_alerta_tipo(recinto, usuario, inv)
            else:
                self._lbl_alerta_tipo.setVisible(False)
        except Exception:
            self._lbl_alerta_tipo.setVisible(False)

    def _marcar_qa(self, resultado):
        usuario = self._cmb_qa_func.currentText().strip()
        if resultado == "aprobado":
            comentario = self._txt_comentario_ok.text().strip()
        else:
            comentario = self._txt_comentario_obs.toPlainText().strip()

        asig = (self._estado or {}).get("funcionarios", {}).get(usuario)
        recinto = asig.get("codigo", "") if asig else ""

        ok, msg = bitacora.evento_qa(recinto, usuario, resultado, comentario)
        color = "#2e7d32" if ok else "#c62828"
        simbolo = "✓" if ok else "✗"
        self._lbl_qa_msg.setText(f"{simbolo} QA {resultado} registrado para {usuario}. {msg}")
        self._lbl_qa_msg.setStyleSheet(f"color:{color};font-size:11px;")

    def _cerrar_recinto(self):
        usuario = self._cmb_qa_func.currentText().strip()
        asig = (self._estado or {}).get("funcionarios", {}).get(usuario)
        recinto = asig.get("codigo", "") if asig else ""

        resp = QMessageBox.question(
            self, "Confirmar cierre",
            f"¿Cerrar formalmente el recinto {recinto} de {usuario}?\n"
            "Esto registra el evento en bitácora.",
            QMessageBox.Yes | QMessageBox.Cancel)
        if resp != QMessageBox.Yes:
            return

        cerrado_por = settings.usuario() or "admin"
        ok, msg = bitacora.evento_cierre(recinto, usuario, cerrado_por)
        color = "#2e7d32" if ok else "#c62828"
        simbolo = "✓" if ok else "✗"
        self._lbl_qa_msg.setText(f"{simbolo} Cierre de {recinto} registrado. {msg}")
        self._lbl_qa_msg.setStyleSheet(f"color:{color};font-size:11px;")
