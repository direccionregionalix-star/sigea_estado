"""
Compatibilidad Qt5 (PyQt5 / QGIS 3.x) ↔ Qt6 (PyQt6 / QGIS 4.x).

En PyQt6 los enums viven dentro de sub-clases; en PyQt5 están directamente
en el objeto (QFrame.HLine, Qt.UserRole, etc.). Este módulo exporta
constantes unificadas que funcionan en ambas versiones.

Uso: from .compat import QFrameHLine, QFrameNoFrame, ScrollBarAlwaysOff, ...
"""

from qgis.PyQt.QtWidgets import QFrame, QDialogButtonBox, QDialog, QDockWidget, QMessageBox
from qgis.PyQt.QtCore import Qt


def _get(obj, qt6_path, qt5_attr):
    """Obtiene un enum primero por la ruta Qt6, luego por el atributo Qt5."""
    # Intentar ruta Qt6 (ej: QFrame.Shape.HLine)
    try:
        result = obj
        for part in qt6_path.split("."):
            result = getattr(result, part)
        return result
    except AttributeError:
        pass
    # Fallback Qt5 (ej: QFrame.HLine)
    return getattr(obj, qt5_attr)


# QFrame
QFrameHLine     = _get(QFrame, "Shape.HLine",   "HLine")
QFrameNoFrame   = _get(QFrame, "Shape.NoFrame", "NoFrame")

# Qt scroll bar policy
ScrollBarAlwaysOff = _get(Qt, "ScrollBarPolicy.ScrollBarAlwaysOff", "ScrollBarAlwaysOff")

# Qt dock areas
DockLeft   = _get(Qt, "DockWidgetArea.LeftDockWidgetArea",   "LeftDockWidgetArea")
DockRight  = _get(Qt, "DockWidgetArea.RightDockWidgetArea",  "RightDockWidgetArea")
DockTop    = _get(Qt, "DockWidgetArea.TopDockWidgetArea",    "TopDockWidgetArea")
DockBottom = _get(Qt, "DockWidgetArea.BottomDockWidgetArea", "BottomDockWidgetArea")

# Qt.UserRole
UserRole = _get(Qt, "ItemDataRole.UserRole", "UserRole")

# QDialog
DialogAccepted = _get(QDialog, "DialogCode.Accepted", "Accepted")

# QDialogButtonBox
BtnOk     = _get(QDialogButtonBox, "StandardButton.Ok",     "Ok")
BtnCancel = _get(QDialogButtonBox, "StandardButton.Cancel", "Cancel")

# QDockWidget features
DockMovable   = _get(QDockWidget, "DockWidgetFeature.DockWidgetMovable",   "DockWidgetMovable")
DockFloatable = _get(QDockWidget, "DockWidgetFeature.DockWidgetFloatable", "DockWidgetFloatable")
DockClosable  = _get(QDockWidget, "DockWidgetFeature.DockWidgetClosable",  "DockWidgetClosable")

# QMessageBox standard buttons
MsgYes    = _get(QMessageBox, "StandardButton.Yes",    "Yes")
MsgNo     = _get(QMessageBox, "StandardButton.No",     "No")
MsgCancel = _get(QMessageBox, "StandardButton.Cancel", "Cancel")
