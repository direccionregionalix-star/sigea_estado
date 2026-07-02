"""
Diálogo de configuración — usuario, URL de estado online y carpetas.
El plugin ya no usa conexión LAN a SIGEA: todo va por estado online (GitHub/Railway).
"""
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QDialogButtonBox, QLabel, QPushButton, QHBoxLayout, QFileDialog,
    QCheckBox, QGroupBox, QGridLayout
)
from qgis.PyQt.QtCore import Qt
from .compat import BtnOk, BtnCancel

from . import settings, rutas


class SigeaConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración SIGEA")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel('<b>Conexión online</b>'))

        form = QFormLayout()

        self._usuario = QLineEdit(settings.usuario())
        self._usuario.setPlaceholderText("mespinozan")
        form.addRow("Usuario:", self._usuario)

        self._estado_url = QLineEdit(settings.estado_url())
        self._estado_url.setPlaceholderText("https://tu-sitio.railway.app/estado.json")
        self._estado_url.setToolTip(
            "URL del estado.json publicado por SIGEA (Railway). "
            "El plugin lee la asignación y el token de escritura desde aquí.")
        form.addRow("URL estado online:", self._estado_url)
        lay.addLayout(form)

        # Prueba de conexión al estado online
        self._lbl_test = QLabel("")
        self._lbl_test.setStyleSheet("font-size: 11px;")
        btn_test = QPushButton("Probar conexión online")
        btn_test.clicked.connect(self._test_online)
        test_row = QHBoxLayout()
        test_row.addWidget(btn_test)
        test_row.addWidget(self._lbl_test)
        test_row.addStretch()
        lay.addLayout(test_row)

        # --- Carpeta de trabajo local ---
        lay.addWidget(QLabel('<b>Carpeta de trabajo (este PC)</b>'))
        lay.addWidget(QLabel(
            '<span style="color:#666;font-size:10px">'
            'La carpeta <b>funcionarios</b> tal como la ves en TU OneDrive. '
            'El plugin la detecta solo; si falla, elígela a mano.</span>'))

        self._carpeta = QLineEdit(settings.carpeta_base_local())
        self._carpeta.setPlaceholderText("(se detecta automáticamente)")
        btn_examinar = QPushButton("Examinar…")
        btn_examinar.clicked.connect(self._examinar)
        btn_auto = QPushButton("Detectar")
        btn_auto.clicked.connect(self._detectar)
        carp_row = QHBoxLayout()
        carp_row.addWidget(self._carpeta, 1)
        carp_row.addWidget(btn_auto)
        carp_row.addWidget(btn_examinar)
        lay.addLayout(carp_row)

        self._lbl_carpeta = QLabel("")
        self._lbl_carpeta.setWordWrap(True)
        self._lbl_carpeta.setStyleSheet("font-size: 11px; margin-top:2px;")
        lay.addWidget(self._lbl_carpeta)
        self._refrescar_diag()

        # --- Carpeta de trabajo local (fuera de OneDrive) ---
        lay.addWidget(QLabel('<b>Carpeta de trabajo local</b>'))
        lay.addWidget(QLabel(
            '<span style="color:#666;font-size:10px">'
            'Carpeta LOCAL (fuera de OneDrive) donde QGIS edita la copia de '
            'trabajo. Evita los conflictos de OneDrive. Vacío = '
            'C:\\sigea_work por defecto.</span>'))
        self._carpeta_trabajo = QLineEdit(settings.carpeta_trabajo_local())
        self._carpeta_trabajo.setPlaceholderText("C:\\sigea_work (por defecto)")
        btn_examinar_t = QPushButton("Examinar…")
        btn_examinar_t.clicked.connect(self._examinar_trabajo)
        trab_row = QHBoxLayout()
        trab_row.addWidget(self._carpeta_trabajo, 1)
        trab_row.addWidget(btn_examinar_t)
        lay.addLayout(trab_row)

        # --- Opciones avanzadas ---
        grp = QGroupBox("Opciones avanzadas")
        gl = QVBoxLayout(grp)

        self._chk_click = QCheckBox("Modo clic (experimental)")
        self._chk_click.setChecked(settings.modo_click_activo())
        self._chk_click.setToolTip("Asigna tipo_geo al hacer clic en el mapa. "
                                   "Pruébalo tú antes de recomendarlo al equipo.")
        gl.addWidget(self._chk_click)

        self._chk_admin = QCheckBox("Habilitar modo admin")
        self._chk_admin.setChecked(settings.modo_admin_habilitado())
        self._chk_admin.setToolTip(
            "Muestra el botón 🔑 Modo Admin si el token tiene acceso de escritura. "
            "Solo para el supervisor del proceso. Apagado por defecto.")
        gl.addWidget(self._chk_admin)

        gl.addWidget(QLabel("Tipos visibles en la botonera:"))
        TIPOS = [(2, "EXACTO"), (1, "LOCALIDAD"), (3, "CALLE"), (5, "PROXIMIDAD"),
                 (4, "NO GEO"), (6, "FUERA COMUNA"), (7, "AUTOGEO"),
                 (8, "RECINTO NO GEO"), (9, "SIN TIPO"), (10, "MASIVO")]
        ocultos = settings.tipos_ocultos()
        self._chks_tipos = {}
        grid = QGridLayout()
        for i, (cod, nom) in enumerate(TIPOS):
            chk = QCheckBox(nom)
            chk.setChecked(cod not in ocultos)
            grid.addWidget(chk, i // 2, i % 2)
            self._chks_tipos[cod] = chk
        gl.addLayout(grid)
        lay.addWidget(grp)

        btns = QDialogButtonBox(BtnOk | BtnCancel)
        btns.accepted.connect(self._guardar)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _test_online(self):
        from . import api
        settings.set_estado_url(self._estado_url.text().strip())
        settings.set_value("usuario", self._usuario.text().strip())
        try:
            asig, generado = api.estado_online()
            hora = generado.replace("T", " ")[:16] if generado else "?"
            self._lbl_test.setText(f"✓ Online (al {hora})")
            self._lbl_test.setStyleSheet("color: #2e7d32; font-size: 11px;")
        except api.SigeaError as e:
            self._lbl_test.setText(f"✗ {e}")
            self._lbl_test.setStyleSheet("color: #c62828; font-size: 11px;")

    def _examinar(self):
        inicio = self._carpeta.text().strip() or settings.carpeta_base_local() or ""
        d = QFileDialog.getExistingDirectory(
            self, "Elige la carpeta 'funcionarios'", inicio)
        if d:
            self._carpeta.setText(d)
            settings.set_carpeta_base_local(d)
            self._refrescar_diag()

    def _examinar_trabajo(self):
        inicio = self._carpeta_trabajo.text().strip() or ""
        d = QFileDialog.getExistingDirectory(
            self, "Elige la carpeta de trabajo local (fuera de OneDrive)", inicio)
        if d:
            self._carpeta_trabajo.setText(d)

    def _detectar(self):
        settings.set_value("usuario", self._usuario.text().strip())
        settings.set_carpeta_base_local("")
        base = rutas.detectar_carpeta_base()
        if base:
            self._carpeta.setText(base)
            settings.set_carpeta_base_local(base)
        self._refrescar_diag()

    def _refrescar_diag(self):
        settings.set_value("usuario", self._usuario.text().strip())
        if self._carpeta.text().strip():
            settings.set_carpeta_base_local(self._carpeta.text().strip())
        txt = rutas.diagnostico()
        color = "#2e7d32" if txt.startswith("✓") else (
            "#a9791f" if txt.startswith("⚠") else "#c62828")
        self._lbl_carpeta.setText(txt)
        self._lbl_carpeta.setStyleSheet(f"color:{color}; font-size:11px;")

    def _guardar(self):
        settings.set_value("usuario", self._usuario.text().strip())
        settings.set_estado_url(self._estado_url.text().strip())
        settings.set_carpeta_base_local(self._carpeta.text().strip())
        settings.set_carpeta_trabajo_local(self._carpeta_trabajo.text().strip())
        settings.set_modo_click(self._chk_click.isChecked())
        settings.set_modo_admin_habilitado(self._chk_admin.isChecked())
        ocultos = {cod for cod, chk in self._chks_tipos.items()
                   if not chk.isChecked()}
        settings.set_tipos_ocultos(ocultos)
        self.accept()
