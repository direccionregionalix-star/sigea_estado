"""
SIGEA Panel — Widget principal v1.1
- Detección de capa ya cargada (no duplica)
- Conteos por tipo_geo en cada botón
- Modo desconectado (lee gpkg local sin SIGEA)
- Tipos ocultables desde opciones avanzadas
"""
import time
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QScrollArea, QTextEdit, QDialog,
    QDialogButtonBox, QCheckBox, QMessageBox, QGroupBox,
    QSpacerItem, QSizePolicy, QLineEdit, QListWidget, QListWidgetItem,
    QComboBox, QApplication
)
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor

from qgis.core import QgsProject, QgsVectorLayer, QgsRectangle

from . import api, settings, rutas
from .compat import (QFrameHLine, QFrameNoFrame, ScrollBarAlwaysOff,
                      UserRole, DialogAccepted, BtnOk, BtnCancel,
                      MsgYes, MsgCancel)

import os as _os
import json as _json
import hashlib as _hashlib
from datetime import datetime as _dt

_MANIFEST_SUFIJO = ".listo"


def _manifest_hash(ruta, bloque=1 << 20):
    h = _hashlib.sha256()
    with open(ruta, "rb") as fh:
        while True:
            b = fh.read(bloque)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _manifest_escribir(ruta, por="Plugin QGIS"):
    """Escribe el manifest .listo tras guardar el gpkg (verificación OneDrive)."""
    try:
        datos = {"archivo": _os.path.basename(ruta),
                 "bytes": _os.path.getsize(ruta),
                 "sha256": _manifest_hash(ruta),
                 "generado": _dt.now().isoformat(timespec="seconds"),
                 "por": por}
        tmp = ruta + _MANIFEST_SUFIJO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            _json.dump(datos, fh, ensure_ascii=False, indent=1)
        _os.replace(tmp, ruta + _MANIFEST_SUFIJO)
        return True
    except Exception:
        return False


def _manifest_verificar(ruta):
    """Devuelve (estado, detalle): ok | sincronizando | sin_manifest | sin_archivo."""
    if not _os.path.exists(ruta):
        return "sin_archivo", "El archivo aún no llega a tu OneDrive."
    rm = ruta + _MANIFEST_SUFIJO
    if not _os.path.exists(rm):
        return "sin_manifest", ""
    try:
        with open(rm, encoding="utf-8") as fh:
            m = _json.load(fh)
    except Exception:
        return "sincronizando", "Manifest ilegible (sincronizando)."
    try:
        if _os.path.getmtime(ruta) > _os.path.getmtime(rm) + 2:
            return "sin_manifest", ""  # archivo editado después: no verificable
    except OSError:
        pass
    if _os.path.getsize(ruta) != m.get("bytes"):
        return "sincronizando", "OneDrive aún está bajando este archivo."
    if _manifest_hash(ruta) != m.get("sha256"):
        return "sincronizando", "OneDrive aún está bajando este archivo."
    return "ok", ""

# ---------------------------------------------------------------------------
# Dominio tipo_geo_id
# ---------------------------------------------------------------------------
TIPOS_GEO = [
    (2,  "EXACTO",         "#2e7d32"),
    (1,  "LOCALIDAD",      "#558b2f"),
    (3,  "CALLE",          "#f9a825"),
    (5,  "PROXIMIDAD",     "#ef6c00"),
    (4,  "NO GEO",         "#c62828"),
    (6,  "FUERA COMUNA",   "#6a1b9a"),
    (7,  "AUTOGEO",        "#0277bd"),
    (8,  "RECINTO NO GEO", "#546e7a"),
    (9,  "SIN TIPO",       "#757575"),
    (10, "MASIVO",         "#00838f"),
]
CAMPO_TIPO_GEO = "tipo_geo_id"
MAPA_TIPOS = {c: t for c, t, _ in TIPOS_GEO}


def _sep():
    f = QFrame(); f.setFrameShape(QFrameHLine)
    f.setStyleSheet("color: #e0e0e0;"); return f


def _lbl_sec(txt):
    l = QLabel(txt)
    l.setStyleSheet("font-size:10px;font-weight:600;color:#888;"
                    "text-transform:uppercase;letter-spacing:1px;"
                    "margin-top:6px;margin-bottom:2px;")
    return l


class SigeaPanel(QWidget):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.asignacion = None
        self.capa_activa = None
        self._codigo_activo = None
        self._conectado = False
        self._modo = "cache"
        self._build_ui()
        self._setup_timer()
        self.cargar_asignacion()

    # ------------------------------------------------------------------
    # Construcción UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.setMinimumWidth(240)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(3)

        # Cabecera
        self._lbl_usuario = QLabel("—")
        self._lbl_usuario.setStyleSheet(
            "font-size:13px;font-weight:700;color:#1a1a2e;")
        self._lbl_estado = QLabel("● Desconectado")
        self._lbl_estado.setStyleSheet("font-size:11px;color:#999;")

        hdr = QHBoxLayout()
        izq = QVBoxLayout()
        izq.setSpacing(1)
        izq.addWidget(self._lbl_usuario)
        izq.addWidget(self._lbl_estado)
        hdr.addLayout(izq); hdr.addStretch()

        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setFixedSize(26, 26)
        self._btn_refresh.setToolTip("Recargar asignación desde SIGEA")
        self._btn_refresh.setStyleSheet(
            "QPushButton{border:1px solid #ccc;border-radius:4px;font-size:13px;}"
            "QPushButton:hover{background:#f0f0f0;}")
        self._btn_refresh.clicked.connect(self.cargar_asignacion)
        hdr.addWidget(self._btn_refresh)

        self._btn_config = QPushButton("⚙")
        self._btn_config.setFixedSize(26, 26)
        self._btn_config.setToolTip("Configuración: URL, usuario y carpeta de trabajo")
        self._btn_config.setStyleSheet(
            "QPushButton{border:1px solid #ccc;border-radius:4px;font-size:13px;}"
            "QPushButton:hover{background:#f0f0f0;}")
        self._btn_config.clicked.connect(self._abrir_config)
        hdr.addWidget(self._btn_config)
        root.addLayout(hdr)
        root.addWidget(_sep())

        # Recinto activo
        root.addWidget(_lbl_sec("Mi recinto activo"))
        self._lbl_recinto = QLabel("Sin asignación activa")
        self._lbl_recinto.setStyleSheet(
            "font-size:14px;font-weight:700;color:#1a1a2e;")
        self._lbl_recinto.setWordWrap(True)
        root.addWidget(self._lbl_recinto)

        self._lbl_meta = QLabel("")
        self._lbl_meta.setStyleSheet("font-size:11px;color:#555;")
        root.addWidget(self._lbl_meta)

        self._lbl_plazo = QLabel("")
        self._lbl_plazo.setStyleSheet("font-size:11px;")
        root.addWidget(self._lbl_plazo)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(13)
        self._progress.setStyleSheet(
            "QProgressBar{border:1px solid #ccc;border-radius:3px;"
            "background:#eee;text-align:center;font-size:10px;}"
            "QProgressBar::chunk{background:#2e7d32;border-radius:2px;}")
        root.addWidget(self._progress)

        self._lbl_avance = QLabel("0 / 0 rectificados")
        self._lbl_avance.setStyleSheet("font-size:11px;color:#555;")
        root.addWidget(self._lbl_avance)

        self._btn_cargar = QPushButton("▶  Cargar recinto en mapa")
        self._btn_cargar.setStyleSheet(self._estilo("#1565c0", "#1976d2"))
        self._btn_cargar.clicked.connect(self.cargar_capa)
        self._btn_cargar.setEnabled(False)
        root.addWidget(self._btn_cargar)

        self._btn_pausa = QPushButton("⏸  Pausar y sincronizar")
        self._btn_pausa.setStyleSheet(self._estilo("#00897b", "#26a69a"))
        self._btn_pausa.clicked.connect(self.pausar_sincronizar)
        self._btn_pausa.setEnabled(False)
        self._btn_pausa.setToolTip(
            "Cierra tu copia local y la sube a OneDrive de forma segura.\n"
            "Quita la capa del proyecto: para seguir, espera unos segundos\n"
            "y vuelve a cargar el recinto.")
        root.addWidget(self._btn_pausa)

        self._btn_respaldo = QPushButton("💾  Respaldar ahora")
        self._btn_respaldo.setStyleSheet(self._estilo("#6a4c93", "#8159b5"))
        self._btn_respaldo.clicked.connect(self.respaldar_ahora)
        self._btn_respaldo.setEnabled(False)
        self._btn_respaldo.setToolTip(
            "Guarda una copia de seguridad de tu trabajo actual SIN cerrar\n"
            "la sesión. Quedan los últimos 5 respaldos en tu disco local.\n"
            "Úsalo cuando quieras, especialmente antes de pausas largas.")
        root.addWidget(self._btn_respaldo)

        # --- Buscador SIGEC (colapsable) ---
        self._build_sigec(root)

        root.addWidget(_sep())

        # Botonera tipo_geo
        root.addWidget(_lbl_sec("Asignar tipo geo  (puntos seleccionados)"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrameNoFrame)
        scroll.setHorizontalScrollBarPolicy(ScrollBarAlwaysOff)
        cont = QWidget()
        self._grid_tipos = QVBoxLayout(cont)
        self._grid_tipos.setContentsMargins(0, 0, 0, 0)
        self._grid_tipos.setSpacing(2)

        self._btns_tipo = {}
        ocultos = settings.tipos_ocultos()
        for codigo, texto, color in TIPOS_GEO:
            btn = self._crear_btn_tipo(codigo, texto, color)
            btn.setVisible(codigo not in ocultos)
            self._grid_tipos.addWidget(btn)
            self._btns_tipo[codigo] = btn

        scroll.setWidget(cont)
        scroll.setMaximumHeight(260)
        root.addWidget(scroll)

        root.addWidget(_sep())

        # Acciones
        root.addWidget(_lbl_sec("Acciones"))

        self._btn_avance = QPushButton("↑  Registrar avance")
        self._btn_avance.setStyleSheet(self._estilo("#546e7a", "#607d8b"))
        self._btn_avance.clicked.connect(self.registrar_avance)
        self._btn_avance.setEnabled(False)
        root.addWidget(self._btn_avance)

        self._btn_entregar = QPushButton("✓  Entregar recinto")
        self._btn_entregar.setStyleSheet(self._estilo("#2e7d32", "#388e3c"))
        self._btn_entregar.clicked.connect(self.entregar)
        self._btn_entregar.setEnabled(False)
        root.addWidget(self._btn_entregar)

        root.addStretch()

        self._lbl_msg = QLabel("")
        self._lbl_msg.setWordWrap(True)
        self._lbl_msg.setStyleSheet("font-size:10px;color:#555;margin-top:2px;")
        root.addWidget(self._lbl_msg)

    def _crear_btn_tipo(self, codigo, texto, color):
        btn = QPushButton()
        btn.setFixedHeight(30)
        btn.setStyleSheet(
            f"QPushButton{{background:{color};color:white;border:none;"
            f"border-radius:4px;font-size:11px;font-weight:600;"
            f"text-align:left;padding-left:8px;}}"
            f"QPushButton:hover{{filter:brightness(1.1);}}"
            f"QPushButton:disabled{{background:#ccc;color:#888;}}")
        btn.setEnabled(False)
        btn.setProperty("tipo_codigo", codigo)
        btn.clicked.connect(lambda _, c=codigo: self.asignar_tipo_geo(c))
        # Texto inicial sin conteo
        btn.setText(f"{texto}")
        return btn

    def _estilo(self, c, h):
        return (f"QPushButton{{background:{c};color:white;border:none;"
                f"border-radius:4px;padding:5px;font-size:11px;font-weight:600;}}"
                f"QPushButton:hover{{background:{h};}}"
                f"QPushButton:disabled{{background:#ccc;color:#888;}}")

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------
    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._refrescar_silencioso)
        self._timer.start()

    # ------------------------------------------------------------------
    # Lógica principal
    # ------------------------------------------------------------------
    def cargar_asignacion(self):
        """Cadena de fallback: estado online (Railway/GitHub) → caché local."""
        usuario = settings.usuario()
        self._lbl_usuario.setText(usuario or "Sin usuario")

        # 1) Estado online
        try:
            asig, generado = api.estado_online()
            self._set_modo("online", generado)
            if asig is None:
                self._set_sin_asignacion()
                return
            self._aplicar_asignacion(asig)
            return
        except api.SigeaError:
            pass

        # 2) Caché local
        self._set_modo("cache")
        self._modo_desconectado()

    def _set_modo(self, modo, generado=""):
        """Modo de operación: online | cache."""
        self._modo = modo
        if modo == "online":
            hora = generado.replace("T", " ")[:16] if generado else "?"
            self._lbl_estado.setText(f"● Online (al {hora})")
            self._lbl_estado.setStyleSheet("font-size:11px;color:#2e7d32;")
        else:
            self._lbl_estado.setText("● Sin conexión  (caché local)")
            self._lbl_estado.setStyleSheet("font-size:11px;color:#ef6c00;")

    def _aplicar_asignacion(self, asig):
        # Si hay más de una asignación activa, dejar elegir cuál trabajar
        lista = asig.get("asignaciones")
        if lista and len(lista) > 1:
            elegida = self._elegir_asignacion(lista)
            if elegida is None:
                return  # el usuario canceló
            asig = elegida
        elif lista and len(lista) == 1:
            asig = lista[0]

        self.asignacion = asig
        # Fijar el código del recinto activo (blinda el conteo)
        self._codigo_activo = asig.get("codigo")
        # Cachear código + ruta LOCAL para modo desconectado
        try:
            cod = asig.get("codigo", "")
            ruta_local = rutas.ruta_gpkg(cod) if cod else None
            if ruta_local:
                settings.set_gpkg_path_cache(ruta_local, cod)
        except Exception:
            pass
        self._actualizar_vista()
        if self._modo == "lan":
            self._set_msg("")

    def _elegir_asignacion(self, lista):
        """Muestra un diálogo para elegir entre varias asignaciones activas.
        Devuelve el dict elegido o None si cancela."""
        from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel,
                                         QListWidget, QListWidgetItem,
                                         QDialogButtonBox)
        from qgis.PyQt.QtCore import Qt
        dlg = QDialog(self)
        dlg.setWindowTitle("Elige el recinto a trabajar")
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Tienes varios recintos asignados. Elige uno "
                             "(trabaja uno a la vez):"))
        lw = QListWidget()
        for a in lista:
            pct = (round(100 * a.get("avance", 0) / a["n_electores"])
                   if a.get("n_electores") else 0)
            dias = a.get("dias_restantes")
            plazo = f" · {dias}d restantes" if dias is not None else ""
            txt = (f"R{a['codigo']} — {a.get('unidad', '')} "
                   f"({a.get('comuna', '')})  ·  {a.get('avance', 0)}/"
                   f"{a.get('n_electores', 0)} ({pct}%){plazo}")
            item = QListWidgetItem(txt)
            item.setData(UserRole, a)
            lw.addItem(item)
        lw.setCurrentRow(0)
        lay.addWidget(lw)
        btns = QDialogButtonBox(BtnOk | BtnCancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() != DialogAccepted:
            return None
        item = lw.currentItem()
        return item.data(UserRole) if item else None

    def _abrir_config(self):
        from .config_dialog import SigeaConfigDialog
        dlg = SigeaConfigDialog(self)
        if dlg.exec():
            self._aplicar_tipos_ocultos()
            self.cargar_asignacion()

    def _aplicar_tipos_ocultos(self):
        ocultos = settings.tipos_ocultos()
        for codigo, btn in self._btns_tipo.items():
            btn.setVisible(codigo not in ocultos)

    def _modo_desconectado(self):
        """Carga desde caché local sin SIGEA."""
        gpkg_path = settings.gpkg_path_cache()
        codigo = settings.gpkg_codigo_cache()
        if not gpkg_path or not codigo:
            self._lbl_recinto.setText("Sin conexión y sin caché local.")
            self._lbl_meta.setText("Configura la conexión a SIGEA.")
            return

        self._codigo_activo = codigo
        self._lbl_recinto.setText(f"R{codigo}  (modo local)")
        self._lbl_meta.setText("Sin conexión a SIGEA — solo rectificación local")
        self._lbl_plazo.setText("")
        self._btn_cargar.setEnabled(True)
        # En modo desconectado no se puede registrar ni entregar
        self._btn_avance.setEnabled(False)
        self._btn_entregar.setEnabled(False)
        self._set_msg("Sin conexión online. Puedes rectificar pero no publicar avance. Verifica la URL en ⚙.", error=True)

    def _set_sin_asignacion(self):
        self.asignacion = None
        self._lbl_recinto.setText("Sin asignación activa")
        self._lbl_meta.setText("")
        self._lbl_plazo.setText("")
        self._progress.setValue(0)
        self._lbl_avance.setText("0 / 0 rectificados")
        self._btn_cargar.setEnabled(False)
        self._btn_avance.setEnabled(False)
        self._btn_entregar.setEnabled(False)
        self._set_btns_tipo(False)

    def _actualizar_vista(self):
        a = self.asignacion
        self._lbl_recinto.setText(a.get("unidad_nombre", "—"))
        self._lbl_meta.setText(
            f"{str(a.get('comuna','')).title()} · {a.get('n_electores',0)} electores")

        dias = a.get("dias_restantes")
        if dias is None:
            txt, color = f"Plazo: {a.get('fecha_estimada','—')}", "#555"
        elif dias < 0:
            txt, color = f"⚠ Vencido hace {abs(dias)} días", "#c62828"
        elif dias <= 2:
            txt, color = f"⚠ {a.get('fecha_estimada')} ({dias} d)", "#ef6c00"
        else:
            txt, color = f"Plazo: {a.get('fecha_estimada')} ({dias} d)", "#2e7d32"
        self._lbl_plazo.setText(txt)
        self._lbl_plazo.setStyleSheet(
            f"font-size:11px;color:{color};font-weight:600;")

        rev = a.get("avance", 0)
        total = a.get("n_electores", 0)
        pct = round(100 * rev / total) if total else 0
        self._progress.setValue(pct)
        self._lbl_avance.setText(f"{rev} / {total} rectificados ({pct}%)")

        self._btn_cargar.setEnabled(True)
        self._btn_avance.setEnabled(True)
        self._btn_entregar.setEnabled(True)
        self._btn_avance.setToolTip("Registrar avance en GitHub")
        self._btn_entregar.setToolTip("Marcar recinto entregado (publica avance final en GitHub)")

    # ------------------------------------------------------------------
    # Cargar capa — detecta si ya está cargada
    # ------------------------------------------------------------------
    def cargar_capa(self):
        # El código del recinto viene de SIGEA (o de la caché). La RUTA, en
        # cambio, la resolvemos localmente: la ruta absoluta de SIGEA no sirve
        # porque cada PC ve el OneDrive compartido con otro nombre.
        if self.asignacion:
            codigo = self.asignacion.get("codigo") or settings.gpkg_codigo_cache()
        else:
            codigo = settings.gpkg_codigo_cache()

        if not codigo:
            self._set_msg("No hay recinto asignado.", error=True)
            return

        # Ruta LOCAL en este PC
        ruta = rutas.ruta_gpkg(codigo)
        if not ruta:
            self._set_msg("No encuentro tu carpeta de trabajo. Ábrela con el "
                          "botón ⚙ y usa 'Examinar carpeta'.", error=True)
            return

        # Guardar el código activo: el conteo SIEMPRE será sobre esta capa
        self._codigo_activo = codigo
        # Cachear para modo desconectado
        ruta_one = rutas.ruta_gpkg(codigo)
        if ruta_one:
            settings.set_gpkg_path_cache(ruta_one, codigo)

        # Verificación de sincronización OneDrive antes de copiar a local
        if ruta_one:
            est, det = _manifest_verificar(ruta_one)
            if est == "sin_archivo":
                self._set_msg(f"⏳ {det} (busqué en {ruta_one}). Si el archivo "
                              "ya está en tu OneDrive, revisa tu carpeta con ⚙.",
                              error=True)
                return
            if est == "sincronizando":
                self._set_msg(f"⏳ {det} Reintenta en unos segundos.", error=True)
                return

        # Abrir SESIÓN LOCAL: copia el gpkg de OneDrive a la carpeta de trabajo
        # local. QGIS edita esa copia → OneDrive nunca ve el archivo abierto.
        from . import sesion
        ruta, msg_sesion = sesion.abrir_sesion(codigo)
        if not ruta:
            self._set_msg(msg_sesion, error=True)
            return

        nombre_capa = f"R{codigo}"

        # Detectar si la capa ya está cargada en QGIS (por nombre Y ruta local)
        for layer in QgsProject.instance().mapLayers().values():
            if (isinstance(layer, QgsVectorLayer) and
                    layer.name() == nombre_capa and layer.isValid() and
                    layer.source().split("|")[0] == ruta):
                self.capa_activa = layer
                self.iface.setActiveLayer(layer)
                self._set_msg(f"Capa {nombre_capa} ya estaba cargada — activada.")
                self._set_btns_tipo(True)
                try:
                    layer.selectionChanged.connect(self._on_sel_cambiada)
                except Exception:
                    pass
                self._actualizar_conteos()
                self._actualizar_btn_pausa()
                return

        # No estaba cargada — cargar desde la copia local
        uri = f"{ruta}|layername={nombre_capa}"
        layer = QgsVectorLayer(uri, nombre_capa, "ogr")
        if not layer.isValid():
            self._set_msg(f"No se pudo abrir {nombre_capa} en {ruta}.", error=True)
            return

        QgsProject.instance().addMapLayer(layer)
        self.capa_activa = layer
        self.iface.setActiveLayer(layer)
        self.iface.zoomToActiveLayer()
        layer.selectionChanged.connect(self._on_sel_cambiada)
        self._set_btns_tipo(True)
        self._actualizar_conteos()
        self._actualizar_btn_pausa()
        self._set_msg(f"Capa {nombre_capa} cargada. {msg_sesion}")

    # ------------------------------------------------------------------
    # Asignar tipo_geo
    # ------------------------------------------------------------------
    def asignar_tipo_geo(self, codigo_tipo):
        layer = self._capa_valida()
        if not layer:
            self._set_msg("Primero carga el recinto en el mapa.", error=True)
            return
        sel = layer.selectedFeatureIds()
        if not sel:
            self._set_msg("Selecciona puntos en el mapa primero.", error=True)
            return
        if not layer.isEditable():
            self.iface.actionToggleEditing().trigger()
        idx = layer.fields().indexOf(CAMPO_TIPO_GEO)
        if idx < 0:
            self._set_msg(f"Campo '{CAMPO_TIPO_GEO}' no encontrado.", error=True)
            return
        layer.beginEditCommand(f"tipo_geo_id={codigo_tipo}")
        for fid in sel:
            layer.changeAttributeValue(fid, idx, codigo_tipo)
        layer.endEditCommand()
        nombre = MAPA_TIPOS.get(codigo_tipo, str(codigo_tipo))
        self._set_msg(f"{len(sel)} punto(s) → {nombre}")
        self._actualizar_conteos()

    # ------------------------------------------------------------------
    # Conteos por tipo en los botones
    # ------------------------------------------------------------------
    def _actualizar_conteos(self):
        """Actualiza el texto de cada botón con el conteo actual de la capa."""
        layer = self._capa_valida()
        if not layer:
            for codigo, texto, _ in TIPOS_GEO:
                self._btns_tipo[codigo].setText(texto)
            return

        idx = layer.fields().indexOf(CAMPO_TIPO_GEO)
        if idx < 0:
            return

        conteos = {}
        total = 0
        revisados = 0
        for feat in layer.getFeatures():
            total += 1
            t = feat.attributes()[idx]
            try:
                t = int(t) if t is not None and str(t) not in ("", "NULL", "None") else None
            except (ValueError, TypeError):
                t = None
            if t is not None:
                conteos[t] = conteos.get(t, 0) + 1
                if t not in (8, 9):
                    revisados += 1

        # Actualizar botones
        for codigo, texto, _ in TIPOS_GEO:
            cnt = conteos.get(codigo, 0)
            btn = self._btns_tipo[codigo]
            if cnt > 0:
                btn.setText(f"{texto}  [{cnt}]")
            else:
                btn.setText(texto)

        # Actualizar barra
        pct = round(100 * revisados / total) if total else 0
        self._progress.setValue(pct)
        self._lbl_avance.setText(f"{revisados} / {total} rectificados ({pct}%)")

    # ------------------------------------------------------------------
    # Registrar avance y Entregar
    # ------------------------------------------------------------------
    def _actualizar_btn_pausa(self):
        """Habilita los botones de pausa y respaldo si hay sesión local."""
        try:
            from . import sesion
            hay = bool(self._codigo_activo) and sesion.hay_sesion_local(self._codigo_activo)
            self._btn_pausa.setEnabled(hay)
            self._btn_respaldo.setEnabled(hay)
        except Exception:
            pass

    def respaldar_ahora(self):
        """Respaldo manual: copia la sesión actual a _historico/ sin cerrar."""
        from . import sesion
        codigo = self._codigo_activo
        if not codigo:
            self._set_msg("No hay recinto activo para respaldar.", error=True)
            return
        # Guardar primero los cambios pendientes de QGIS al gpkg local
        layer = self._capa_valida()
        if layer:
            try:
                if layer.isEditable():
                    layer.commitChanges()
                    layer.startEditing()  # seguir editando tras el commit
            except RuntimeError:
                pass
        ok, info = sesion.respaldar_local(codigo, etiqueta="manual")
        if ok:
            import os
            self._set_msg(f"✓ Respaldo guardado: {os.path.basename(info)}")
        else:
            self._set_msg(f"⚠ {info}", error=True)

    def pausar_sincronizar(self):
        """Cierra la copia local, la sube a OneDrive (con respaldo rotado) y
        quita la capa del proyecto. El funcionario recarga para continuar."""
        from . import sesion
        codigo = self._codigo_activo
        if not codigo:
            self._set_msg("No hay recinto activo.", error=True)
            return

        # 1) Confirmar cambios pendientes y cerrar edición
        layer = self._capa_valida()
        if layer:
            try:
                if layer.isEditable():
                    layer.commitChanges()
            except RuntimeError:
                layer = None

        # 2) Quitar la capa del proyecto: libera el lock del archivo local
        #    (QGIS suelta el .gpkg, -wal y -shm). Sin esto OneDrive vería WAL.
        quitadas = 0
        for lyr in list(QgsProject.instance().mapLayers().values()):
            try:
                if (isinstance(lyr, QgsVectorLayer) and
                        lyr.name() == f"R{codigo}"):
                    QgsProject.instance().removeMapLayer(lyr.id())
                    quitadas += 1
            except RuntimeError:
                continue
        self.capa_activa = None

        # 3) Procesar eventos para que QGIS suelte de verdad el archivo
        try:
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass
        time.sleep(0.3)

        # 4) RESPALDO PREVIO: antes de tocar OneDrive, asegurar copia local.
        #    Si la sincronización fallara, el trabajo queda a salvo igual.
        sesion.respaldar_local(codigo, etiqueta="prepausa")

        # 5) Sincronizar copia local → OneDrive (con verificación de integridad)
        ok, msg = sesion.sincronizar(
            codigo,
            manifest_cb=lambda ruta: _manifest_escribir(
                ruta, por=f"Plugin ({settings.usuario()})"))
        if not ok:
            # NO se borra la copia local: el trabajo sigue en sigea_work y en
            # _historico. El funcionario puede reintentar sin perder nada.
            self._set_msg(f"⚠ {msg} Tu trabajo NO se perdió: sigue en tu "
                          "copia local. Reintenta 'Pausar y sincronizar'.",
                          error=True)
            return

        # 6) Cierre seguro: limpiar_local respalda en _historico antes de borrar
        sesion.limpiar_local(codigo)

        self._set_btns_tipo(False)
        self._btn_pausa.setEnabled(False)
        self._btn_respaldo.setEnabled(False)
        self._actualizar_conteos()
        self._set_msg(f"✓ {msg}")

    # ------------------------------------------------------------------
    # Buscador SIGEC
    # ------------------------------------------------------------------
    def _build_sigec(self, root):
        """Sección colapsable de búsqueda de direcciones (SIGEC)."""
        self._grp_sigec = QGroupBox("🔍 Buscar dirección (SIGEC)")
        self._grp_sigec.setCheckable(True)
        self._grp_sigec.setChecked(False)  # colapsado por defecto
        self._grp_sigec.toggled.connect(self._toggle_sigec)
        gl = QVBoxLayout(self._grp_sigec)
        gl.setSpacing(5)

        # Comuna inferida / selector de fallback
        self._lbl_comuna_sigec = QLabel("")
        self._lbl_comuna_sigec.setStyleSheet("font-size:10px;color:#555")
        gl.addWidget(self._lbl_comuna_sigec)

        self._combo_comuna = QComboBox()
        self._combo_comuna.setVisible(False)  # solo si no se infiere
        from . import comunas
        for cod, nom in comunas.opciones_ordenadas():
            self._combo_comuna.addItem(f"{nom} ({cod})", cod)
        gl.addWidget(self._combo_comuna)

        # Campo de dirección + botón
        fila = QHBoxLayout()
        self._inp_dir = QLineEdit()
        self._inp_dir.setPlaceholderText("ej: malleco 5, los aromos…")
        self._inp_dir.returnPressed.connect(self.buscar_sigec)
        fila.addWidget(self._inp_dir, 1)
        self._btn_buscar = QPushButton("Buscar")
        self._btn_buscar.clicked.connect(self.buscar_sigec)
        fila.addWidget(self._btn_buscar)
        gl.addLayout(fila)

        # Lista de resultados
        self._lst_sigec = QListWidget()
        self._lst_sigec.setMaximumHeight(150)
        self._lst_sigec.itemDoubleClicked.connect(self._elegir_resultado_sigec)
        gl.addWidget(self._lst_sigec)

        self._lbl_sigec_msg = QLabel("")
        self._lbl_sigec_msg.setWordWrap(True)
        self._lbl_sigec_msg.setStyleSheet("font-size:10px;color:#666")
        gl.addWidget(self._lbl_sigec_msg)

        # Empezar oculto el contenido (colapsado)
        for w in (self._lbl_comuna_sigec, self._combo_comuna, self._inp_dir,
                  self._btn_buscar, self._lst_sigec, self._lbl_sigec_msg):
            w.setVisible(False)

        root.addWidget(self._grp_sigec)

    def _toggle_sigec(self, abierto):
        for w in (self._lbl_comuna_sigec, self._inp_dir, self._btn_buscar,
                  self._lst_sigec, self._lbl_sigec_msg):
            w.setVisible(abierto)
        # El combo solo si no hay comuna inferida
        if abierto:
            self._refrescar_comuna_sigec()

    def _comuna_actual_sigec(self):
        """Infiere el código SIGEC (4 díg) de la capa de trabajo activa.
        Devuelve (codigo, fuente) donde fuente es 'capa' o 'combo'."""
        from . import comunas
        # 1) intentar inferir de la capa cargada
        layer = self._capa_valida()
        if layer:
            idx = layer.fields().indexOf("comuna")
            if idx >= 0:
                for feat in layer.getFeatures():
                    val = feat.attributes()[idx]
                    cod = comunas.codigo_sigec(val)
                    if cod:
                        return cod, "capa"
                    break  # con el primer registro basta
        # 2) fallback: el combo
        cod = self._combo_comuna.currentData()
        return cod, "combo"

    def _refrescar_comuna_sigec(self):
        """Actualiza la etiqueta/combo de comuna según lo que se pueda inferir."""
        from . import comunas
        cod, fuente = self._comuna_actual_sigec()
        if fuente == "capa" and cod:
            self._lbl_comuna_sigec.setText(
                f"Comuna: {comunas.nombre_de(cod)} ({cod}) — de la capa")
            self._combo_comuna.setVisible(False)
            # sincronizar el combo por si luego se necesita
            i = self._combo_comuna.findData(cod)
            if i >= 0:
                self._combo_comuna.setCurrentIndex(i)
        else:
            self._lbl_comuna_sigec.setText(
                "No pude inferir la comuna de la capa — elígela:")
            self._combo_comuna.setVisible(True)

    def buscar_sigec(self):
        from . import sigec
        query = self._inp_dir.text().strip()
        if not query:
            self._lbl_sigec_msg.setText("Escribe una dirección para buscar.")
            return
        cod, _ = self._comuna_actual_sigec()
        if not cod:
            self._lbl_sigec_msg.setText("Falta la comuna.")
            return
        self._lst_sigec.clear()
        self._lbl_sigec_msg.setText("Buscando…")
        QApplication.processEvents()
        try:
            resultados = sigec.buscar(cod, query, limite=20)
        except sigec.SigecError as e:
            self._lbl_sigec_msg.setText(str(e))
            return
        self._resultados_sigec = resultados
        if not resultados:
            self._lbl_sigec_msg.setText("Sin coincidencias. Prueba con otra "
                                        "escritura o menos palabras.")
            return
        for r in resultados:
            score = r.get("score")
            etq = f"{r.get('direccion', '?')}  ·  {r.get('rol', '')}"
            if score is not None:
                etq += f"  ·  {round(float(score), 2)}"
            item = QListWidgetItem(etq)
            item.setData(UserRole, r)
            self._lst_sigec.addItem(item)
        self._lbl_sigec_msg.setText(
            f"{len(resultados)} resultado(s). Doble clic para cargar el predio.")

    def _elegir_resultado_sigec(self, item):
        from . import sigec, sigec_layer, comunas
        r = item.data(UserRole)
        if not r:
            return
        # Cargar el polígono como capa temporal (sin pisar la de trabajo)
        capa = sigec_layer.capa_un_resultado(r)
        if capa is None:
            self._lbl_sigec_msg.setText("El predio no trae geometría válida.")
            return
        QgsProject.instance().addMapLayer(capa)
        # Zoom al predio
        try:
            ext = capa.extent()
            ext.scale(1.4)  # un poco de margen
            self.iface.mapCanvas().setExtent(ext)
            self.iface.mapCanvas().refresh()
        except Exception:
            pass
        # Copiar centroide al portapapeles (lat, lon) para el flujo de asignación
        lat, lon = r.get("lat"), r.get("lon")
        if lat is not None and lon is not None:
            try:
                QApplication.clipboard().setText(f"{lat}, {lon}")
            except Exception:
                pass
        # Registrar la selección para el aprendizaje (best-effort)
        cod, _ = self._comuna_actual_sigec()
        try:
            sigec.registrar_seleccion(self._inp_dir.text().strip(), cod,
                                      r.get("rol", ""))
        except Exception:
            pass
        self._lbl_sigec_msg.setText(
            f"✓ {r.get('direccion', 'predio')} cargado. Centroide copiado "
            "al portapapeles.")

    def registrar_avance(self):
        if not self.asignacion:
            return
        layer = self._capa_valida()
        if not layer:
            self._set_msg("Primero carga el recinto en el mapa.", error=True)
            return
        if layer.isEditable():
            layer.commitChanges()
        # El avance va directo a GitHub. El archivo de OneDrive se actualiza
        # aparte con "Pausar y sincronizar" (no aquí: editamos copia local).
        conteos, total = self._conteos_capa()
        codigo = self._codigo_activo or ""
        from . import github_report
        ok, msg = github_report.publicar_avance(codigo, conteos, total)
        if ok:
            n_rev = sum(n for t, n in conteos.items() if int(t) not in (8, 9))
            self.asignacion["avance"] = n_rev
            self._actualizar_vista()
            self._set_msg(f"✓ {msg}")
        else:
            self._set_msg(f"Error: {msg}", error=True)

    def _conteos_capa(self):
        """Devuelve (conteos_dict, total) de la capa activa.
        conteos_dict: {tipo_geo_id: n}."""
        layer = self._capa_valida()
        if not layer:
            return {}, 0
        idx = layer.fields().indexOf(CAMPO_TIPO_GEO)
        if idx < 0:
            return {}, 0
        conteos = {}
        total = 0
        for feat in layer.getFeatures():
            total += 1
            t = feat.attributes()[idx]
            try:
                t = int(t) if t is not None and str(t) not in ("", "NULL", "None") else None
            except (ValueError, TypeError):
                t = None
            if t is not None:
                conteos[t] = conteos.get(t, 0) + 1
        return conteos, total

    def entregar(self):
        if not self.asignacion:
            return
        layer = self._capa_valida()
        if layer and layer.isEditable():
            resp = QMessageBox.question(
                self, "Ediciones sin guardar",
                "Hay cambios sin guardar. ¿Guardar antes de entregar?",
                MsgYes | MsgCancel)
            if resp == MsgCancel:
                return
            layer.commitChanges()

        # Manifest local para que SIGEA pueda verificar el archivo al reimportar
        if layer and layer.source():
            ruta_src = layer.source().split("|")[0]
            _manifest_escribir(ruta_src, por=f"Plugin entrega ({settings.usuario()})")

        conteos, total_feat = self._conteos_capa()
        n_rev = self._contar_revisados()
        total = self.asignacion.get("n_electores", 0)
        pct = round(100 * n_rev / total) if total else 0

        dlg = _EntregaDialog(n_rev, total, pct, self)
        if dlg.exec() != DialogAccepted:
            return

        # Publicar avance final a GitHub (mismo mecanismo que registrar_avance)
        from . import github_report
        codigo = self._codigo_activo or ""
        ok, msg = github_report.publicar_avance(
            codigo, conteos, total_feat,
            metadata_version="entrega")
        if ok:
            self._set_msg("✓ Recinto entregado y avance publicado en GitHub.")
            if layer:
                QgsProject.instance().removeMapLayer(layer.id())
                self.capa_activa = None
            self.asignacion = None
            self._set_sin_asignacion()
        else:
            self._set_msg(f"Error publicando entrega: {msg}", error=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _capa_valida(self):
        """Devuelve SOLO la capa del recinto activo (R{codigo}). Nunca cae a
        la capa 'activa' arbitraria de QGIS: eso causaba conteos exagerados
        cuando el usuario seleccionaba otra capa (padrón, recintos, etc.).

        Si la capa fue quitada del proyecto (botón derecho → Quitar capa),
        Qt destruye el objeto C++ pero la referencia Python sigue viva como
        wrapper huérfano: cualquier llamada sobre ella lanza RuntimeError
        ("wrapped C/C++ object ... has been deleted"), no una Exception
        normal. Hay que atraparla explícitamente o el timer de refresco
        revienta cada 60s."""
        # 1) la referencia guardada, si sigue válida y es la correcta
        if self.capa_activa is not None:
            try:
                if (self.capa_activa.isValid() and
                        self._es_capa_recinto(self.capa_activa)):
                    return self.capa_activa
            except RuntimeError:
                pass  # objeto C++ eliminado: la capa fue quitada del proyecto
            self.capa_activa = None
        # 2) buscar por nombre exacto entre las capas del proyecto
        if self._codigo_activo:
            objetivo = f"R{self._codigo_activo}"
            for layer in QgsProject.instance().mapLayers().values():
                try:
                    if (isinstance(layer, QgsVectorLayer) and layer.isValid() and
                            layer.name() == objetivo):
                        self.capa_activa = layer
                        return layer
                except RuntimeError:
                    continue
        return None

    def _es_capa_recinto(self, layer):
        try:
            return (self._codigo_activo is not None and
                    layer.name() == f"R{self._codigo_activo}")
        except Exception:
            return False

    def _contar_revisados(self):
        layer = self._capa_valida()
        if not layer:
            return 0
        idx = layer.fields().indexOf(CAMPO_TIPO_GEO)
        if idx < 0:
            return 0
        count = 0
        for feat in layer.getFeatures():
            t = feat.attributes()[idx]
            try:
                t = int(t) if t is not None and str(t) not in ("", "NULL", "None") else None
                if t is not None and t not in (8, 9):
                    count += 1
            except (ValueError, TypeError):
                pass
        return count

    def _refrescar_silencioso(self):
        self._actualizar_conteos()

    def _on_sel_cambiada(self, *args):
        layer = self._capa_valida()
        tiene = layer is not None and layer.selectedFeatureCount() > 0
        self._set_btns_tipo(tiene)

    def _set_btns_tipo(self, enabled):
        for btn in self._btns_tipo.values():
            btn.setEnabled(enabled and btn.isVisible())

    def _set_msg(self, txt, error=False):
        self._lbl_msg.setText(txt)
        c = "#c62828" if error else "#2e7d32"
        self._lbl_msg.setStyleSheet(f"font-size:10px;color:{c};margin-top:2px;")


# ------------------------------------------------------------------
# Diálogo de entrega
# ------------------------------------------------------------------
class _EntregaDialog(QDialog):
    def __init__(self, n_rev, total, pct, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirmar entrega")
        self.setMinimumWidth(300)
        lay = QVBoxLayout(self)
        color = "#2e7d32" if pct >= 90 else ("#ef6c00" if pct >= 50 else "#c62828")
        lay.addWidget(QLabel('<b style="font-size:13px">¿Entregar el recinto?</b>'))
        lay.addWidget(QLabel(
            f'<span style="color:{color};font-size:12px">'
            f'{n_rev} / {total} rectificados ({pct}%)</span>'))
        if pct < 100:
            av = QLabel(f"Quedarán {total - n_rev} puntos sin tipo geo.")
            av.setStyleSheet("color:#ef6c00;font-size:11px;")
            lay.addWidget(av)
        lay.addWidget(QLabel("Observaciones (opcional):"))
        self._obs = QTextEdit()
        self._obs.setFixedHeight(55)
        self._obs.setPlaceholderText("Nota para el supervisor...")
        lay.addWidget(self._obs)
        btns = QDialogButtonBox(BtnOk | BtnCancel)
        btns.button(BtnOk).setText("Entregar")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def observaciones(self):
        return self._obs.toPlainText().strip()
