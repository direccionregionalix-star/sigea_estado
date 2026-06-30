"""
Diálogo de administración SIGEA — solo visible si el token tiene push access
Y el checkbox 'Habilitar modo admin' está activado en configuración.

Sprint 3: conectado a archivos locales (central.gpkg, QA_pendiente/) mediante
admin_archivos.py. La misma disciplina atómica + SHA-256 + respaldo de sesion.py.

Pestañas:
  1. Estado global  — tabla de funcionarios + lista de recintos desde central.gpkg.
  2. Asignar        — selecciona recinto de la lista + funcionario; extrae gpkg.
  3. Entregar a QA  — copia gpkg funcionario → QA_pendiente/ con SHA-256.
  4. QA / Cierre    — abre gpkg de QA en QGIS; aprobar → reimporte al central.

REGLA: estado.json y bitácora solo llevan metadata (conteos, eventos). Los gpkg
con datos reales viven solo en OneDrive. Nunca RUTs, coordenadas ni direcciones
en GitHub.
"""
import json
import base64
from datetime import datetime, timezone

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialogButtonBox, QTabWidget, QWidget, QTableWidget, QTableWidgetItem,
    QLineEdit, QTextEdit, QComboBox, QMessageBox, QGroupBox, QFormLayout,
    QHeaderView, QSplitter, QListWidget, QListWidgetItem, QCheckBox,
    QAbstractItemView
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from qgis.core import QgsProject, QgsVectorLayer

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
    for carpeta in ("qgis", "sige"):
        try:
            data, _ = _github_get(repo, branch, f"{carpeta}/{usuario}.json", token)
            return data
        except Exception:
            pass
    return None


def _detectar_tipos_invalidos(reporte):
    if not reporte:
        return []
    confirmados = reporte.get("avance", {}).get("confirmados", {})
    return [n for n in confirmados if n not in _NOMBRES_TIPO.values()]


def _btn_style(color, hover):
    return (f"QPushButton{{background:{color};color:white;border:none;"
            f"border-radius:4px;padding:6px;font-weight:600;}}"
            f"QPushButton:hover{{background:{hover};}}")


class AdminDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SIGEA — Modo Admin")
        self.setMinimumWidth(680)
        self.setMinimumHeight(540)

        try:
            self._creds = _obtener_creds()
        except Exception as e:
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel(f"Sin credenciales admin: {e}"))
            bb = QDialogButtonBox(BtnOk)
            bb.accepted.connect(self.accept)
            lay.addWidget(bb)
            return

        self._estado = None
        self._estado_sha = None
        self._recintos = []       # lista de dicts desde central.gpkg
        self._recargar_estado()
        self._recargar_recintos()

        lay = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(self._tab_estado(), "Estado global")
        tabs.addTab(self._tab_asignar(), "Asignar recinto")
        tabs.addTab(self._tab_entregar_qa(), "Entregar a QA")
        tabs.addTab(self._tab_qa(), "QA / Cierre")

        lay.addWidget(tabs)
        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.accept)
        lay.addWidget(cerrar)

    # ── Carga de datos ───────────────────────────────────────────────────

    def _recargar_estado(self):
        try:
            self._estado, self._estado_sha = _github_get(
                self._creds["repo"], self._creds["branch"],
                "estado.json", self._creds["token"])
        except Exception:
            self._estado = {"funcionarios": {}}
            self._estado_sha = None

    def _recargar_recintos(self):
        from . import admin_archivos
        self._recintos, _ = admin_archivos.listar_recintos_central(self._estado)

    def _funcionarios(self):
        return list((self._estado or {}).get("funcionarios", {}).keys())

    # ── Tab 1: Estado global ─────────────────────────────────────────────

    def _tab_estado(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        # Tabla funcionarios (como Sprint 2)
        lay.addWidget(QLabel("<b>Funcionarios</b>"))
        tabla = QTableWidget()
        tabla.setColumnCount(6)
        tabla.setHorizontalHeaderLabels(
            ["Funcionario", "Recinto", "Comuna", "Avance", "%", "Herramienta"])
        tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tabla.horizontalHeader().setStretchLastSection(True)

        funcionarios = (self._estado or {}).get("funcionarios", {})
        tabla.setRowCount(len(funcionarios))
        for row, (usuario, asig) in enumerate(funcionarios.items()):
            tabla.setItem(row, 0, QTableWidgetItem(usuario))
            if asig is None:
                for col, txt in enumerate(["—", "Sin asignación", "—", "—", "—"], 1):
                    tabla.setItem(row, col, QTableWidgetItem(txt))
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

        # Tabla recintos desde central.gpkg
        lay.addWidget(QLabel("<b>Recintos en central.gpkg</b>"))
        if self._recintos:
            t2 = QTableWidget()
            t2.setColumnCount(5)
            t2.setHorizontalHeaderLabels(
                ["Código", "Nombre", "Comuna", "Electores", "Estado"])
            t2.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t2.setRowCount(len(self._recintos))
            t2.horizontalHeader().setStretchLastSection(True)
            for row, r in enumerate(self._recintos):
                t2.setItem(row, 0, QTableWidgetItem(r["codigo"]))
                t2.setItem(row, 1, QTableWidgetItem(r["nombre"]))
                t2.setItem(row, 2, QTableWidgetItem(r["comuna"]))
                t2.setItem(row, 3, QTableWidgetItem(str(r["n_electores"])))
                est = r["estado_recinto"]
                est_item = QTableWidgetItem(
                    {"pendiente": "Pendiente",
                     "asignado": f"Asignado a {r['asignado_a']}",
                     "cerrado": "Cerrado"}.get(est, est))
                est_item.setBackground(
                    QColor("#ffcdd2") if est == "pendiente" else (
                        QColor("#fff9c4") if est == "asignado" else QColor("#c8e6c9")))
                t2.setItem(row, 4, est_item)
            lay.addWidget(t2)
        else:
            lay.addWidget(QLabel(
                '<span style="color:#888;font-size:10px">'
                'central.gpkg no accesible o sin datos. '
                'Configura la carpeta de funcionarios.</span>'))

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
            'Selecciona un recinto de la lista + un funcionario. '
            'Actualiza estado.json, extrae el gpkg del recinto en OneDrive '
            'y registra evento en bitácora.</span>'))

        # Lista seleccionable de recintos
        lay.addWidget(QLabel("Recintos disponibles (central.gpkg):"))
        self._lst_recintos = QListWidget()
        self._lst_recintos.setSelectionMode(QAbstractItemView.SingleSelection)
        self._lst_recintos.setFixedHeight(180)
        for r in self._recintos:
            est = r["estado_recinto"]
            label = (f"[{r['codigo']}] {r['nombre']} — {r['comuna']} "
                     f"({r['n_electores']} elect.)"
                     + (f" ← {r['asignado_a']}" if est == "asignado" else "")
                     + (" [CERRADO]" if est == "cerrado" else ""))
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r)
            if est == "cerrado":
                item.setForeground(QColor("#888"))
            elif est == "asignado":
                item.setForeground(QColor("#e65100"))
            lay.addItem = None  # evitar confusión
            self._lst_recintos.addItem(item)

        if not self._recintos:
            self._lst_recintos.addItem(
                "Sin datos — configura la carpeta de funcionarios en Config.")
        lay.addWidget(self._lst_recintos)

        form = QFormLayout()
        self._cmb_func_asig = QComboBox()
        self._cmb_func_asig.addItems(self._funcionarios())
        form.addRow("Funcionario:", self._cmb_func_asig)

        self._txt_fecha = QLineEdit()
        self._txt_fecha.setPlaceholderText("2026-07-15")
        form.addRow("Fecha estimada:", self._txt_fecha)
        lay.addLayout(form)

        self._chk_copiar_gpkg = QCheckBox(
            "Copiar electores del central → gpkg del funcionario (OneDrive)")
        self._chk_copiar_gpkg.setChecked(True)
        self._chk_copiar_gpkg.setToolTip(
            "Si está marcado: extrae el gpkg con los electores del recinto "
            "directamente desde central.gpkg. Requiere acceso a OneDrive.")
        lay.addWidget(self._chk_copiar_gpkg)

        self._lbl_asig_msg = QLabel("")
        self._lbl_asig_msg.setWordWrap(True)
        self._lbl_asig_msg.setStyleSheet("font-size:11px;")
        lay.addWidget(self._lbl_asig_msg)

        btn = QPushButton("Asignar recinto")
        btn.setStyleSheet(_btn_style("#1565c0", "#1976d2"))
        btn.clicked.connect(self._asignar)
        lay.addWidget(btn)
        lay.addStretch()
        return w

    def _asignar(self):
        item = self._lst_recintos.currentItem()
        if not item or not item.data(Qt.UserRole):
            self._lbl_asig_msg.setText("✗ Selecciona un recinto de la lista.")
            self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        r = item.data(Qt.UserRole)
        codigo = r["codigo"]
        unidad = r["nombre"]
        comuna = r["comuna"]
        electores = r["n_electores"]
        usuario = self._cmb_func_asig.currentText().strip()
        fecha = self._txt_fecha.text().strip()

        if not fecha:
            self._lbl_asig_msg.setText("✗ Completa la fecha estimada.")
            self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return
        try:
            dias = (datetime.strptime(fecha, "%Y-%m-%d").date()
                    - datetime.now().date()).days
        except ValueError:
            self._lbl_asig_msg.setText("✗ Fecha debe ser YYYY-MM-DD.")
            self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        # Copiar gpkg del recinto si está marcado
        if self._chk_copiar_gpkg.isChecked():
            from . import admin_archivos
            ok_gpkg, msg_gpkg = admin_archivos.extraer_recinto_para_funcionario(
                codigo, usuario)
            if not ok_gpkg:
                self._lbl_asig_msg.setText(f"✗ Error copiando gpkg: {msg_gpkg}")
                self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
                return

        # Actualizar estado.json
        asig_id = int(datetime.now().timestamp())
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
                "codigo": codigo, "unidad": unidad, "comuna": comuna,
                "n_electores": electores, "fecha_estimada": fecha,
                "dias_restantes": dias, "avance": 0,
                "herramienta": "qgis", "tipo_origen": "recinto",
            }]
        }

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

        asignado_por = settings.usuario() or "admin"
        ok_bit, msg_bit = bitacora.evento_asignacion(codigo, usuario, asignado_por)
        gpkg_nota = (f" gpkg extraído ({msg_gpkg})" if self._chk_copiar_gpkg.isChecked()
                     else " (gpkg no copiado)")
        resultado = f"✓ Recinto {codigo} asignado a {usuario}.{gpkg_nota}"
        if not ok_bit:
            resultado += f" (bitácora: {msg_bit})"
        self._lbl_asig_msg.setText(resultado)
        self._lbl_asig_msg.setStyleSheet("color:#2e7d32;font-size:11px;")

    # ── Tab 3: Entregar a QA ─────────────────────────────────────────────

    def _tab_entregar_qa(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Entregar gpkg a QA_pendiente</b>"))
        lay.addWidget(QLabel(
            '<span style="color:#666;font-size:10px">'
            'Copia el gpkg del funcionario a QA_pendiente/ con SHA-256 verificado. '
            'Si la verificación falla, el trabajo del funcionario queda intacto.</span>'))

        form = QFormLayout()
        self._cmb_func_qa_ent = QComboBox()
        self._cmb_func_qa_ent.addItems(self._funcionarios())
        self._cmb_func_qa_ent.currentTextChanged.connect(self._actualizar_codigo_entrega)
        form.addRow("Funcionario:", self._cmb_func_qa_ent)

        self._lbl_codigo_entrega = QLabel("—")
        form.addRow("Recinto asignado:", self._lbl_codigo_entrega)
        lay.addLayout(form)
        self._actualizar_codigo_entrega()

        self._lbl_ent_msg = QLabel("")
        self._lbl_ent_msg.setWordWrap(True)
        self._lbl_ent_msg.setStyleSheet("font-size:11px;")
        lay.addWidget(self._lbl_ent_msg)

        btn = QPushButton("Entregar a QA_pendiente")
        btn.setStyleSheet(_btn_style("#4527a0", "#512da8"))
        btn.clicked.connect(self._entregar_a_qa)
        lay.addWidget(btn)
        lay.addStretch()
        return w

    def _actualizar_codigo_entrega(self):
        usuario = self._cmb_func_qa_ent.currentText().strip()
        asig = (self._estado or {}).get("funcionarios", {}).get(usuario)
        codigo = asig.get("codigo", "—") if asig else "—"
        self._lbl_codigo_entrega.setText(codigo)

    def _entregar_a_qa(self):
        usuario = self._cmb_func_qa_ent.currentText().strip()
        asig = (self._estado or {}).get("funcionarios", {}).get(usuario)
        if not asig:
            self._lbl_ent_msg.setText("✗ El funcionario no tiene recinto asignado.")
            self._lbl_ent_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return
        codigo = asig.get("codigo", "")

        from . import admin_archivos
        ok, msg = admin_archivos.entregar_a_qa(codigo, usuario)
        if ok:
            # Evento bitácora con conteos del reporte GitHub
            try:
                reporte = _leer_reporte_funcionario(
                    self._creds["repo"], self._creds["branch"],
                    self._creds["token"], usuario)
                if reporte:
                    av = reporte.get("avance", {})
                    conteos = av.get("confirmados", {})
                    total = av.get("total_registros", 0)
                    bitacora.evento_entrega(codigo, usuario, conteos, total)
            except Exception:
                pass
            self._lbl_ent_msg.setText(f"✓ {msg}")
            self._lbl_ent_msg.setStyleSheet("color:#2e7d32;font-size:11px;")
        else:
            self._lbl_ent_msg.setText(f"✗ {msg}")
            self._lbl_ent_msg.setStyleSheet("color:#c62828;font-size:11px;")

    # ── Tab 4: QA / Cierre ───────────────────────────────────────────────

    def _tab_qa(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Control de calidad y cierre de recintos</b>"))

        form = QFormLayout()
        self._cmb_qa_func = QComboBox()
        self._cmb_qa_func.currentTextChanged.connect(self._verificar_tipos_qa)
        lay.addLayout(form)

        # Selector de gpkg en QA_pendiente
        lay.addWidget(QLabel("Recintos en QA_pendiente:"))
        self._cmb_qa_recinto = QComboBox()
        self._cmb_qa_recinto.currentTextChanged.connect(self._on_qa_recinto_changed)
        lay.addWidget(self._cmb_qa_recinto)
        self._refrescar_qa_pendiente()

        # Alerta tipos geo inválidos
        self._lbl_alerta_tipo = QLabel("")
        self._lbl_alerta_tipo.setWordWrap(True)
        self._lbl_alerta_tipo.setStyleSheet(
            "background:#fff3cd;color:#856404;padding:6px;"
            "border-radius:4px;font-size:11px;")
        self._lbl_alerta_tipo.setVisible(False)
        lay.addWidget(self._lbl_alerta_tipo)

        # Botón abrir en QGIS
        btn_abrir = QPushButton("Abrir gpkg de QA en QGIS")
        btn_abrir.setStyleSheet(_btn_style("#00695c", "#00796b"))
        btn_abrir.clicked.connect(self._abrir_qa_en_qgis)
        lay.addWidget(btn_abrir)

        # QA aprobado
        grp_aprobado = QGroupBox("Marcar QA aprobado")
        gl_a = QVBoxLayout(grp_aprobado)
        self._txt_comentario_ok = QLineEdit()
        self._txt_comentario_ok.setPlaceholderText("Comentario opcional...")
        gl_a.addWidget(self._txt_comentario_ok)
        self._chk_reimportar = QCheckBox("Reimportar registros corregidos al central.gpkg")
        self._chk_reimportar.setChecked(True)
        self._chk_reimportar.setToolTip(
            "Si está marcado: actualiza los registros del recinto en central.gpkg "
            "con los datos corregidos. Respalda el central antes de escribir. "
            "REQUIERE prueba real antes del primer uso en producción.")
        gl_a.addWidget(self._chk_reimportar)
        btn_ok = QPushButton("✓ Aprobar")
        btn_ok.setStyleSheet(_btn_style("#2e7d32", "#388e3c"))
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
        btn_obs.setStyleSheet(_btn_style("#ef6c00", "#f57c00"))
        btn_obs.clicked.connect(lambda: self._marcar_qa("observado"))
        gl_o.addWidget(btn_obs)
        lay.addWidget(grp_obs)

        # Cerrar sin asignar (Pieza 5)
        grp_cierre = QGroupBox("Cerrar recinto")
        gl_c = QVBoxLayout(grp_cierre)
        gl_c.addWidget(QLabel(
            '<span style="font-size:10px;color:#666">'
            'Cierre formal con registro en bitácora. No toca central.gpkg.<br>'
            'Usa "Cerrar sin asignar" para recintos ya corregidos en Enterprise.</span>'))
        hc = QHBoxLayout()
        btn_cierre = QPushButton("⬛ Cerrar recinto (con asignación)")
        btn_cierre.setStyleSheet(_btn_style("#37474f", "#455a64"))
        btn_cierre.clicked.connect(self._cerrar_recinto)
        hc.addWidget(btn_cierre)
        btn_cierre_sin = QPushButton("⬛ Cerrar sin asignar (Enterprise previo)")
        btn_cierre_sin.setStyleSheet(_btn_style("#546e7a", "#607d8b"))
        btn_cierre_sin.clicked.connect(self._cerrar_sin_asignar)
        hc.addWidget(btn_cierre_sin)
        gl_c.addLayout(hc)
        lay.addWidget(grp_cierre)

        self._lbl_qa_msg = QLabel("")
        self._lbl_qa_msg.setWordWrap(True)
        self._lbl_qa_msg.setStyleSheet("font-size:11px;")
        lay.addWidget(self._lbl_qa_msg)
        lay.addStretch()
        return w

    def _refrescar_qa_pendiente(self):
        from . import admin_archivos
        codigos = admin_archivos.listar_qa_pendiente()
        self._cmb_qa_recinto.clear()
        if codigos:
            self._cmb_qa_recinto.addItems(codigos)
        else:
            self._cmb_qa_recinto.addItem("(sin recintos en QA_pendiente)")

    def _on_qa_recinto_changed(self, codigo):
        self._verificar_tipos_qa_por_codigo(codigo)

    def _verificar_tipos_qa(self):
        self._verificar_tipos_qa_por_codigo(self._cmb_qa_recinto.currentText())

    def _verificar_tipos_qa_por_codigo(self, codigo):
        if not codigo or codigo.startswith("("):
            self._lbl_alerta_tipo.setVisible(False)
            return
        # Buscar funcionario asignado al recinto
        usuario = None
        for u, asig in (self._estado or {}).get("funcionarios", {}).items():
            if asig and asig.get("codigo") == codigo:
                usuario = u
                break
        if not usuario:
            self._lbl_alerta_tipo.setVisible(False)
            return
        try:
            reporte = _leer_reporte_funcionario(
                self._creds["repo"], self._creds["branch"],
                self._creds["token"], usuario)
            invalidos = _detectar_tipos_invalidos(reporte)
            if invalidos:
                msg = (f"⚠ Tipos geo fuera de dominio: {', '.join(invalidos)} "
                       f"(recinto {codigo}). Verificar antes de aprobar.")
                self._lbl_alerta_tipo.setText(msg)
                self._lbl_alerta_tipo.setVisible(True)
                for inv in invalidos:
                    bitacora.evento_alerta_tipo(codigo, usuario, inv)
            else:
                self._lbl_alerta_tipo.setVisible(False)
        except Exception:
            self._lbl_alerta_tipo.setVisible(False)

    def _abrir_qa_en_qgis(self):
        codigo = self._cmb_qa_recinto.currentText()
        if not codigo or codigo.startswith("("):
            QMessageBox.warning(self, "Sin recinto", "Selecciona un recinto en QA_pendiente.")
            return
        from . import admin_archivos
        ruta = admin_archivos.ruta_qa_pendiente(codigo)
        if not ruta or not __import__("os").path.exists(ruta):
            QMessageBox.warning(self, "Archivo no encontrado",
                                f"No se encontró QA_pendiente/R{codigo}.gpkg")
            return
        layer_name = f"QA_R{codigo}"
        layer = QgsVectorLayer(ruta, layer_name, "ogr")
        if not layer.isValid():
            QMessageBox.warning(self, "Capa inválida",
                                f"No se pudo cargar R{codigo}.gpkg como capa.")
            return
        QgsProject.instance().addMapLayer(layer)
        self._lbl_qa_msg.setText(
            f"✓ Capa '{layer_name}' abierta en QGIS. Revisa las geometrías y vuelve a aprobar.")
        self._lbl_qa_msg.setStyleSheet("color:#2e7d32;font-size:11px;")

    def _marcar_qa(self, resultado):
        codigo = self._cmb_qa_recinto.currentText()
        if codigo.startswith("("):
            self._lbl_qa_msg.setText("✗ Selecciona un recinto en QA_pendiente.")
            self._lbl_qa_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        # Encontrar funcionario asignado
        usuario = ""
        for u, asig in (self._estado or {}).get("funcionarios", {}).items():
            if asig and asig.get("codigo") == codigo:
                usuario = u
                break

        comentario = (self._txt_comentario_ok.text().strip()
                      if resultado == "aprobado"
                      else self._txt_comentario_obs.toPlainText().strip())

        ok_bit, msg_bit = bitacora.evento_qa(codigo, usuario, resultado, comentario)

        msgs = []
        if resultado == "aprobado" and self._chk_reimportar.isChecked():
            from . import admin_archivos

            resp = QMessageBox.question(
                self, "Confirmar reimporte",
                f"¿Reimportar los registros de R{codigo} al central.gpkg?\n"
                "Se guardará un respaldo del central antes de escribir.",
                QMessageBox.Yes | QMessageBox.Cancel)
            if resp == QMessageBox.Yes:
                ok_ri, msg_ri = admin_archivos.reimportar_al_central(codigo)
                msgs.append(f"Reimporte: {'✓' if ok_ri else '✗'} {msg_ri}")
                if ok_ri:
                    ok_mv, msg_mv = admin_archivos.mover_qa_a_cerrado(codigo)
                    msgs.append(f"Movido a QA_cerrado: {'✓' if ok_mv else '✗'} {msg_mv}")
                    self._refrescar_qa_pendiente()

        color = "#2e7d32" if ok_bit else "#c62828"
        self._lbl_qa_msg.setText(
            f"{'✓' if ok_bit else '✗'} QA {resultado}: {usuario}/{codigo}. "
            + " | ".join(msgs))
        self._lbl_qa_msg.setStyleSheet(f"color:{color};font-size:11px;")

    def _cerrar_recinto(self):
        codigo = self._cmb_qa_recinto.currentText()
        usuario = ""
        for u, asig in (self._estado or {}).get("funcionarios", {}).items():
            if asig and asig.get("codigo") == codigo:
                usuario = u
                break

        resp = QMessageBox.question(
            self, "Confirmar cierre",
            f"¿Cerrar formalmente el recinto {codigo} ({usuario})?\n"
            "Registra evento en bitácora.",
            QMessageBox.Yes | QMessageBox.Cancel)
        if resp != QMessageBox.Yes:
            return

        cerrado_por = settings.usuario() or "admin"
        ok, msg = bitacora.evento_cierre(codigo, usuario, cerrado_por)
        color = "#2e7d32" if ok else "#c62828"
        self._lbl_qa_msg.setText(f"{'✓' if ok else '✗'} Cierre {codigo}: {msg}")
        self._lbl_qa_msg.setStyleSheet(f"color:{color};font-size:11px;")

    def _cerrar_sin_asignar(self):
        """Pieza 5 — Cerrar recinto pendiente sin pasar por asignación.
        Para recintos ya corregidos en Enterprise durante la implementación."""
        from . import admin_archivos
        recintos_pendientes = [r for r in self._recintos
                               if r["estado_recinto"] == "pendiente"]
        if not recintos_pendientes:
            QMessageBox.information(self, "Sin pendientes",
                                    "No hay recintos pendientes de asignación.")
            return

        # Diálogo simple de selección
        dlg = _SeleccionarRecintoDlg(recintos_pendientes, self)
        if dlg.exec() != QDialog.Accepted:
            return
        r = dlg.recinto_seleccionado()
        if not r:
            return

        codigo = r["codigo"]
        resp = QMessageBox.question(
            self, "Confirmar cierre sin asignar",
            f"¿Marcar recinto {codigo} — {r['nombre']} como CERRADO?\n"
            f"Motivo: corregido en Enterprise previamente.\n"
            f"No toca central.gpkg.",
            QMessageBox.Yes | QMessageBox.Cancel)
        if resp != QMessageBox.Yes:
            return

        # Actualizar estado.json
        try:
            self._recargar_estado()
            estado = self._estado.copy()
            estado["funcionarios"][f"_cerrado_{codigo}"] = {
                "codigo": codigo, "unidad": r["nombre"], "comuna": r["comuna"],
                "n_electores": r["n_electores"], "estado": "cerrado",
                "motivo": "enterprise_previo",
                "cerrado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            estado["generado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _github_put(
                self._creds["repo"], self._creds["branch"],
                "estado.json", estado, self._creds["token"],
                self._estado_sha,
                f"admin: cierre_sin_asignar {codigo}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo actualizar estado.json: {e}")
            return

        cerrado_por = settings.usuario() or "admin"
        bitacora.evento_cierre(codigo, "", cerrado_por)
        self._lbl_qa_msg.setText(
            f"✓ Recinto {codigo} cerrado sin asignar (enterprise_previo).")
        self._lbl_qa_msg.setStyleSheet("color:#2e7d32;font-size:11px;")
        self._recargar_recintos()


class _SeleccionarRecintoDlg(QDialog):
    """Diálogo auxiliar para seleccionar un recinto pendiente."""
    def __init__(self, recintos, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar recinto")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Selecciona el recinto a cerrar:"))
        self._lst = QListWidget()
        for r in recintos:
            item = QListWidgetItem(
                f"[{r['codigo']}] {r['nombre']} — {r['comuna']} ({r['n_electores']} elect.)")
            item.setData(Qt.UserRole, r)
            self._lst.addItem(item)
        lay.addWidget(self._lst)
        bb = QDialogButtonBox(BtnOk | BtnCancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def recinto_seleccionado(self):
        item = self._lst.currentItem()
        return item.data(Qt.UserRole) if item else None
