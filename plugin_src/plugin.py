"""
SIGEA Panel — Plugin QGIS
Lifecycle: registro, menú, toolbar, panel acoplable.
"""
import os
from qgis.PyQt.QtWidgets import QAction, QDockWidget
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from .compat import (DockLeft, DockRight, DockTop, DockBottom,
                      DockMovable, DockFloatable, DockClosable)

from .panel import SigeaPanel
from .config_dialog import SigeaConfigDialog


class SigeaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.panel_dock = None
        self.action_toggle = None
        self.action_config = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))

        # Acción toggle del panel
        self.action_toggle = QAction(icon, "Panel SIGEA", self.iface.mainWindow())
        self.action_toggle.setCheckable(True)
        self.action_toggle.setToolTip("Mostrar/ocultar panel SIGEA")
        self.action_toggle.triggered.connect(self._toggle_panel)

        # Acción configuración
        self.action_config = QAction("Configurar SIGEA…", self.iface.mainWindow())
        self.action_config.triggered.connect(self._open_config)

        # Menú
        self.iface.addPluginToMenu("SIGEA", self.action_toggle)
        self.iface.addPluginToMenu("SIGEA", self.action_config)

        # Toolbar
        self.iface.addToolBarIcon(self.action_toggle)

        # Crear panel acoplable
        self._crear_panel()

    def _crear_panel(self):
        self.panel = SigeaPanel(self.iface)
        self.panel_dock = QDockWidget("SIGEA", self.iface.mainWindow())
        self.panel_dock.setObjectName("SigeaPanelDock")
        self.panel_dock.setWidget(self.panel)
        # Acoplable en cualquier lado, flotante, o segunda pantalla
        self.panel_dock.setAllowedAreas(
            DockLeft | DockRight |
            DockTop | DockBottom
        )
        self.panel_dock.setFeatures(
            DockMovable |
            DockFloatable |
            DockClosable
        )
        self.iface.mainWindow().addDockWidget(DockRight, self.panel_dock)
        self.panel_dock.visibilityChanged.connect(self.action_toggle.setChecked)

    def _toggle_panel(self, checked):
        if self.panel_dock:
            self.panel_dock.setVisible(checked)

    def _open_config(self):
        dlg = SigeaConfigDialog(self.iface.mainWindow())
        if dlg.exec():
            # Recargar panel con nueva configuración
            self.panel.cargar_asignacion()

    def unload(self):
        self.iface.removePluginMenu("SIGEA", self.action_toggle)
        self.iface.removePluginMenu("SIGEA", self.action_config)
        self.iface.removeToolBarIcon(self.action_toggle)
        if self.panel_dock:
            self.iface.mainWindow().removeDockWidget(self.panel_dock)
            self.panel_dock.deleteLater()
            self.panel_dock = None
