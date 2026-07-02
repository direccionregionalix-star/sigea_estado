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
        tabs.addTab(self._tab_entregas_sige(), "Entregas SIGE")

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
                     "devuelto": f"Devuelto c/avance ({r['asignado_a']})",
                     "cerrado": "Cerrado"}.get(est, est))
                est_item.setBackground(
                    {"pendiente": QColor("#ffcdd2"),
                     "asignado": QColor("#fff9c4"),
                     "devuelto": QColor("#ffe0b2"),
                     "cerrado": QColor("#c8e6c9")}.get(est, QColor("#ffffff")))
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

    @staticmethod
    def _calcular_fecha_estimada(n_electores):
        """Propone fecha hábil: techo(n_electores/100) días hábiles desde hoy.
        Mínimo 1 día hábil. Solo salta sábados y domingos (feriados: mejora futura)."""
        import math
        from datetime import date, timedelta
        dias = max(1, math.ceil(n_electores / 100))
        d = date.today()
        contados = 0
        while contados < dias:
            d += timedelta(days=1)
            if d.weekday() < 5:   # lun–vie
                contados += 1
        return d.strftime("%Y-%m-%d")

    def _refrescar_lista_recintos(self):
        """Aplica filtro de comuna + orden seleccionados y reconstruye _lst_recintos."""
        filtro = getattr(self, "_cmb_filtro_comuna", None)
        orden_cmb = getattr(self, "_cmb_orden", None)
        comuna_sel = filtro.currentText() if filtro else "(todas)"
        orden_idx = orden_cmb.currentIndex() if orden_cmb else 0

        recintos = list(self._recintos)

        # Filtrar por comuna
        if comuna_sel and comuna_sel != "(todas)":
            recintos = [r for r in recintos if r["comuna"] == comuna_sel]

        # Ordenar
        if orden_idx == 0:   # electores sin revisar (desc)
            recintos.sort(key=lambda r: r.get("n_sin_revisar", r["n_electores"]),
                          reverse=True)
        elif orden_idx == 1:  # cantidad electores (desc)
            recintos.sort(key=lambda r: r["n_electores"], reverse=True)
        else:                 # alfabético
            recintos.sort(key=lambda r: r["nombre"])

        self._lst_recintos.clear()
        if not recintos:
            self._lst_recintos.addItem("Sin recintos para esta selección.")
            return

        for r in recintos:
            est = r["estado_recinto"]
            sin_rev = r.get("n_sin_revisar", r["n_electores"])
            label = (f"[{r['codigo']}] {r['nombre']} — {r['comuna']} "
                     f"({r['n_electores']} elect., {sin_rev} sin rev.)"
                     + (f" ← {r['asignado_a']}" if est == "asignado" else "")
                     + (f" ↩ devuelto c/avance ({r['asignado_a']})" if est == "devuelto" else "")
                     + (" [CERRADO]" if est == "cerrado" else ""))
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r)
            if est == "cerrado":
                item.setForeground(QColor("#888"))
            elif est == "asignado":
                item.setForeground(QColor("#e65100"))
            elif est == "devuelto":
                item.setForeground(QColor("#bf360c"))
            self._lst_recintos.addItem(item)

    def _proponer_fecha(self):
        """Al seleccionar recinto, calcula y propone la fecha estimada."""
        item = self._lst_recintos.currentItem()
        if not item:
            return
        r = item.data(Qt.UserRole)
        if not r:
            return
        self._txt_fecha.setText(self._calcular_fecha_estimada(r["n_electores"]))

    def _tab_asignar(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Asignar recinto a un funcionario</b>"))
        lay.addWidget(QLabel(
            '<span style="color:#666;font-size:10px">'
            'Selecciona un recinto de la lista + un funcionario. '
            'Actualiza estado.json, extrae el gpkg del recinto en OneDrive '
            'y registra evento en bitácora.</span>'))

        # ── Filtros ──────────────────────────────────────────────────────
        filtros_lay = QHBoxLayout()

        filtros_lay.addWidget(QLabel("Filtrar por comuna:"))
        self._cmb_filtro_comuna = QComboBox()
        self._cmb_filtro_comuna.setMinimumWidth(160)
        comunas = sorted({r["comuna"] for r in self._recintos if r["comuna"] != "—"})
        self._cmb_filtro_comuna.addItem("(todas)")
        self._cmb_filtro_comuna.addItems(comunas)
        self._cmb_filtro_comuna.currentIndexChanged.connect(self._refrescar_lista_recintos)
        filtros_lay.addWidget(self._cmb_filtro_comuna)

        filtros_lay.addSpacing(16)
        filtros_lay.addWidget(QLabel("Ordenar por:"))
        self._cmb_orden = QComboBox()
        self._cmb_orden.addItems([
            "Electores sin revisar (mayor primero)",
            "Cantidad de electores (mayor primero)",
            "Nombre (A-Z)",
        ])
        self._cmb_orden.currentIndexChanged.connect(self._refrescar_lista_recintos)
        filtros_lay.addWidget(self._cmb_orden)
        filtros_lay.addStretch()
        lay.addLayout(filtros_lay)

        # ── Lista seleccionable de recintos ──────────────────────────────
        lay.addWidget(QLabel("Recintos disponibles (central.gpkg):"))
        self._lst_recintos = QListWidget()
        self._lst_recintos.setSelectionMode(QAbstractItemView.SingleSelection)
        self._lst_recintos.setFixedHeight(200)
        self._lst_recintos.currentItemChanged.connect(
            lambda cur, _prev: self._proponer_fecha())
        lay.addWidget(self._lst_recintos)
        self._refrescar_lista_recintos()   # carga inicial con orden por defecto

        if not self._recintos:
            self._lst_recintos.clear()
            self._lst_recintos.addItem(
                "Sin datos — configura la carpeta de funcionarios en Config.")

        form = QFormLayout()
        self._cmb_func_asig = QComboBox()
        self._cmb_func_asig.addItems(self._funcionarios())
        form.addRow("Funcionario:", self._cmb_func_asig)

        self._txt_fecha = QLineEdit()
        self._txt_fecha.setPlaceholderText("2026-07-15 (se calcula al seleccionar recinto)")
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

        # Devolver asignación en nombre del funcionario seleccionado (Pieza 7).
        btn_dev = QPushButton("Devolver asignación del funcionario seleccionado")
        btn_dev.setStyleSheet(_btn_style("#b71c1c", "#c62828"))
        btn_dev.setToolTip(
            "Devuelve la asignación activa del funcionario elegido arriba. "
            "Permite elegir conservar o no el avance. Útil para limpiar estado.")
        btn_dev.clicked.connect(self._devolver_asignacion)
        lay.addWidget(btn_dev)
        lay.addStretch()
        return w

    def _devolver_asignacion(self):
        from .devolver_dialog import DevolverDialog, ejecutar_devolucion
        usuario = self._cmb_func_asig.currentText().strip()
        self._recargar_estado()
        asig = (self._estado or {}).get("funcionarios", {}).get(usuario)
        if not asig or not asig.get("codigo"):
            self._lbl_asig_msg.setText(
                f"✗ {usuario} no tiene una asignación activa para devolver.")
            self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return
        codigo = asig.get("codigo")
        dlg = DevolverDialog(codigo, usuario, self)
        if dlg.exec() != DialogAccepted:
            return
        ok, msg = ejecutar_devolucion(
            codigo, usuario, dlg.conservar_avance(), dlg.motivo())
        color = "#2e7d32" if ok else "#c62828"
        self._lbl_asig_msg.setText(f"{'✓' if ok else '✗'} {msg}")
        self._lbl_asig_msg.setStyleSheet(f"color:{color};font-size:11px;")
        if ok:
            self._recargar_estado()
            self._recargar_recintos()

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

        # Copiar gpkg del recinto si está marcado. Si el recinto fue devuelto
        # con avance, continúa desde ese gpkg en vez de extraer uno nuevo.
        if self._chk_copiar_gpkg.isChecked():
            from . import admin_archivos
            ok_gpkg, msg_gpkg, origen_gpkg = admin_archivos.preparar_gpkg_asignacion(
                codigo, usuario)
            if not ok_gpkg:
                self._lbl_asig_msg.setText(f"✗ Error preparando gpkg: {msg_gpkg}")
                self._lbl_asig_msg.setStyleSheet("color:#c62828;font-size:11px;")
                return

        # ADVERTENCIA de asignación múltiple: si el funcionario ya tiene una
        # asignación activa (no liberada), avisar. Se permite, pero se advierte.
        self._recargar_estado()
        actual = (self._estado or {}).get("funcionarios", {}).get(usuario)
        if actual and actual.get("codigo") and not actual.get("liberado"):
            cod_prev = actual.get("codigo")
            if cod_prev != codigo and not getattr(self, "_confirmar_multiple", False):
                self._lbl_asig_msg.setText(
                    f"⚠ {usuario} ya tiene activo el recinto {cod_prev}. "
                    f"Vuelve a presionar Asignar para confirmar la doble asignación.")
                self._lbl_asig_msg.setStyleSheet("color:#e65100;font-size:11px;")
                self._confirmar_multiple = True
                return
        self._confirmar_multiple = False

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
        gpkg_nota = (f" gpkg {origen_gpkg} ({msg_gpkg})" if self._chk_copiar_gpkg.isChecked()
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

            # LIBERAR al funcionario: al entregar a QA, queda disponible para
            # una nueva asignación. Se marca liberado=True en estado.json
            # (no se borra el registro, para conservar el historial del recinto).
            try:
                self._recargar_estado()
                estado = self._estado.copy()
                f = estado.get("funcionarios", {}).get(usuario)
                if f:
                    f["liberado"] = True
                    f["estado_flujo"] = "en_qa"
                    estado["generado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    _github_put(
                        self._creds["repo"], self._creds["branch"],
                        "estado.json", estado, self._creds["token"],
                        self._estado_sha,
                        f"admin: {usuario} liberado, {codigo} en QA")
                    self._recargar_estado()
            except Exception as e:
                self._lbl_ent_msg.setText(
                    f"✓ {msg} (gpkg en QA, pero no pude marcar liberado: {e})")
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

        # Alerta tipos geo inválidos — SE CREA ANTES del combo que la usa.
        # _refrescar_qa_pendiente() puebla el combo y dispara
        # _on_qa_recinto_changed → _verificar_tipos_qa_por_codigo, que lee
        # self._lbl_alerta_tipo. Si el label no existe aún, crashea con
        # AttributeError. Por eso se construye primero.
        self._lbl_alerta_tipo = QLabel("")
        self._lbl_alerta_tipo.setWordWrap(True)
        self._lbl_alerta_tipo.setStyleSheet(
            "background:#fff3cd;color:#856404;padding:6px;"
            "border-radius:4px;font-size:11px;")
        self._lbl_alerta_tipo.setVisible(False)

        # Selector de gpkg en QA_pendiente
        lay.addWidget(QLabel("Recintos en QA_pendiente:"))
        self._cmb_qa_recinto = QComboBox()
        self._cmb_qa_recinto.currentTextChanged.connect(self._on_qa_recinto_changed)
        lay.addWidget(self._cmb_qa_recinto)
        lay.addWidget(self._lbl_alerta_tipo)
        self._refrescar_qa_pendiente()

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
        # Guarda defensiva: este método puede dispararse mientras se puebla el
        # combo, antes de que el resto de la UI exista. Si el label aún no está,
        # salir en silencio en vez de crashear.
        if not hasattr(self, "_lbl_alerta_tipo"):
            return
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


    # ── Tab 5: Entregas SIGE ─────────────────────────────────────────────

    def _tab_entregas_sige(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("<b>Importar entregas SIGE (xlsx)</b>"))
        lay.addWidget(QLabel(
            '<span style="color:#666;font-size:10px">'
            'Escanea entregas xlsx del directorio de funcionarios. '
            'Al aprobar copia a QA_pendiente/, actualiza estado y registra bitácora.</span>'))

        btn_scan = QPushButton("Buscar entregas SIGE")
        btn_scan.setStyleSheet(_btn_style("#1565c0", "#1976d2"))
        btn_scan.clicked.connect(self._escanear_sige)
        lay.addWidget(btn_scan)

        lay.addWidget(QLabel("Entregas pendientes:"))
        self._lst_sige = QListWidget()
        self._lst_sige.setFixedHeight(140)
        self._lst_sige.setSelectionMode(QAbstractItemView.SingleSelection)
        self._lst_sige.currentItemChanged.connect(
            lambda cur, _prev: self._mostrar_resumen_sige(cur))
        lay.addWidget(self._lst_sige)

        lay.addWidget(QLabel("Resumen de filas (sin RUTs ni datos sensibles):"))
        self._tbl_sige = QTableWidget()
        self._tbl_sige.setColumnCount(5)
        self._tbl_sige.setHorizontalHeaderLabels(
            ["N°", "tipo_geo", "lat", "lon", "método"])
        self._tbl_sige.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl_sige.horizontalHeader().setStretchLastSection(True)
        self._tbl_sige.setFixedHeight(160)
        lay.addWidget(self._tbl_sige)

        self._lbl_sige_msg = QLabel("")
        self._lbl_sige_msg.setWordWrap(True)
        self._lbl_sige_msg.setStyleSheet("font-size:11px;")
        lay.addWidget(self._lbl_sige_msg)

        btn_aprobar = QPushButton("✓ Aprobar e importar entrega seleccionada")
        btn_aprobar.setStyleSheet(_btn_style("#2e7d32", "#388e3c"))
        btn_aprobar.clicked.connect(self._aprobar_sige)
        lay.addWidget(btn_aprobar)
        lay.addStretch()

        self._sige_filas_validadas = []   # cache de filas validadas
        self._sige_entrega_actual = None  # dict con recinto/usuario/ruta_xlsx
        return w

    def _escanear_sige(self):
        try:
            from . import importador_sige
        except ImportError as e:
            self._lbl_sige_msg.setText(f"✗ importador_sige no disponible: {e}")
            self._lbl_sige_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return
        self._lst_sige.clear()
        self._tbl_sige.setRowCount(0)
        self._sige_filas_validadas = []
        self._sige_entrega_actual = None

        try:
            entregas = importador_sige.escanear_entregas_sige()
        except Exception as e:
            self._lbl_sige_msg.setText(f"✗ Error escaneando: {e}")
            self._lbl_sige_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        if not entregas:
            self._lbl_sige_msg.setText("Sin entregas SIGE nuevas pendientes.")
            self._lbl_sige_msg.setStyleSheet("color:#666;font-size:11px;")
            return

        for e in entregas:
            label = (f"[{e['recinto']}] {e['usuario']} — "
                     f"{__import__('os').path.basename(e['ruta_xlsx'])} "
                     f"({e.get('ts_archivo', '')})")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, e)
            self._lst_sige.addItem(item)

        self._lbl_sige_msg.setText(f"{len(entregas)} entrega(s) SIGE encontradas.")
        self._lbl_sige_msg.setStyleSheet("color:#1565c0;font-size:11px;")

    def _mostrar_resumen_sige(self, item):
        self._tbl_sige.setRowCount(0)
        self._sige_filas_validadas = []
        self._sige_entrega_actual = None
        if not item:
            return
        entrega = item.data(Qt.UserRole)
        if not entrega:
            return

        try:
            from . import importador_sige
            _headers, filas_raw = importador_sige.leer_entrega_xlsx(entrega["ruta_xlsx"])
            filas_val, resumen = importador_sige.validar_entrega_sige(filas_raw)
        except Exception as e:
            self._lbl_sige_msg.setText(f"✗ Error leyendo xlsx: {e}")
            self._lbl_sige_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        self._sige_filas_validadas = filas_val
        self._sige_entrega_actual = entrega

        # Resumen de tipos (sin datos sensibles)
        n_exc = resumen.get("excepcion", 0)
        n_pend = resumen.get("pendiente", 0)
        n_val = resumen.get("validas", 0)
        self._lbl_sige_msg.setText(
            f"Filas: {n_val} válidas, {n_pend} pendientes (sin coords), "
            f"{n_exc} excepciones. "
            + (f"⚠ {n_exc} excepción(es) — revisar antes de aprobar." if n_exc else ""))
        self._lbl_sige_msg.setStyleSheet(
            "color:#b71c1c;font-size:11px;" if n_exc else "color:#1565c0;font-size:11px;")

        # Tabla de resumen por fila (solo tipo_geo, coordenadas y método — sin RUTs/dir)
        self._tbl_sige.setRowCount(len(filas_val))
        for row_i, fila in enumerate(filas_val):
            estado_fila = fila.get("_estado", "")
            self._tbl_sige.setItem(row_i, 0, QTableWidgetItem(str(row_i + 1)))
            self._tbl_sige.setItem(row_i, 1, QTableWidgetItem(str(fila.get("tipo_geo_id", ""))))
            self._tbl_sige.setItem(row_i, 2, QTableWidgetItem(str(fila.get("latitud", ""))))
            self._tbl_sige.setItem(row_i, 3, QTableWidgetItem(str(fila.get("longitud", ""))))
            self._tbl_sige.setItem(row_i, 4, QTableWidgetItem(str(fila.get("metodo", ""))))
            if estado_fila == "excepcion":
                for col in range(5):
                    it = self._tbl_sige.item(row_i, col)
                    if it:
                        it.setBackground(QColor("#ffcdd2"))
            elif estado_fila == "pendiente":
                for col in range(5):
                    it = self._tbl_sige.item(row_i, col)
                    if it:
                        it.setBackground(QColor("#fff9c4"))

    def _aprobar_sige(self):
        if not self._sige_entrega_actual or not self._sige_filas_validadas:
            self._lbl_sige_msg.setText("✗ Selecciona una entrega y espera el resumen.")
            self._lbl_sige_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        entrega = self._sige_entrega_actual
        n_exc = sum(1 for f in self._sige_filas_validadas if f.get("_estado") == "excepcion")
        if n_exc:
            resp = QMessageBox.question(
                self, "Hay excepciones",
                f"Esta entrega tiene {n_exc} fila(s) marcadas como excepción.\n"
                "¿Importar de todas formas? Las excepciones se conservan.",
                QMessageBox.Yes | QMessageBox.Cancel)
            if resp != QMessageBox.Yes:
                return

        try:
            from . import importador_sige
            ok, msg = importador_sige.procesar_entrega_sige(
                entrega["recinto"], entrega["usuario"],
                entrega["ruta_xlsx"], self._sige_filas_validadas)
        except Exception as e:
            self._lbl_sige_msg.setText(f"✗ Error al procesar: {e}")
            self._lbl_sige_msg.setStyleSheet("color:#c62828;font-size:11px;")
            return

        color = "#2e7d32" if ok else "#c62828"
        self._lbl_sige_msg.setText(f"{'✓' if ok else '✗'} {msg}")
        self._lbl_sige_msg.setStyleSheet(f"color:{color};font-size:11px;")
        if ok:
            # Quitar de la lista
            row = self._lst_sige.currentRow()
            self._lst_sige.takeItem(row)
            self._tbl_sige.setRowCount(0)
            self._sige_filas_validadas = []
            self._sige_entrega_actual = None


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
