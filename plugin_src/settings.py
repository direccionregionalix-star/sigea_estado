"""
Configuración del plugin — lee y escribe desde QSettings de QGIS.

Importante: las funciones internas se llaman _read/_write (NO get/set) para
no tapar los builtins set() y dict.get() de Python.
"""
from qgis.PyQt.QtCore import QSettings

SETTINGS_KEY = "SigeaPanel"


def _read(key, default=None):
    s = QSettings()
    return s.value(f"{SETTINGS_KEY}/{key}", default)


def _write(key, value):
    s = QSettings()
    s.setValue(f"{SETTINGS_KEY}/{key}", value)


# Alias públicos para el diálogo de configuración
def get(key, default=None):
    return _read(key, default)


def set_value(key, value):
    _write(key, value)


def sigea_url():
    # Conservado por compatibilidad. El plugin ya no usa LAN.
    return _read("url", "").rstrip("/")


def usuario():
    u = _read("usuario", "")
    if not u:
        try:
            import os
            u = os.getlogin()
        except Exception:
            u = ""
    return u


def modo_click_activo():
    return _read("modo_click", "false") == "true"


def set_modo_click(value):
    _write("modo_click", "true" if value else "false")


# Cache local para modo desconectado
def gpkg_path_cache():
    """Ruta del gpkg guardada localmente la última vez que hubo conexión."""
    return _read("gpkg_path_cache", "")


def set_gpkg_path_cache(path, codigo):
    _write("gpkg_path_cache", path)
    _write("gpkg_codigo_cache", codigo)


def gpkg_codigo_cache():
    return _read("gpkg_codigo_cache", "")


def tipos_ocultos():
    """Conjunto de tipo_geo_id que el usuario eligió ocultar en la botonera."""
    val = _read("tipos_ocultos", "")
    if not val:
        return set()
    try:
        return set(int(x) for x in str(val).split(",") if str(x).strip())
    except Exception:
        return set()


def set_tipos_ocultos(ids):
    _write("tipos_ocultos", ",".join(str(x) for x in sorted(ids)))


# --- Carpeta base local (resuelve el problema de rutas OneDrive distintas) ---
def carpeta_base_local():
    """Carpeta 'funcionarios' tal como la ve ESTE PC. Si está vacía, el plugin
    intentará detectarla automáticamente."""
    return _read("carpeta_base_local", "")


def set_carpeta_base_local(ruta):
    _write("carpeta_base_local", ruta or "")


# --- Estado online (Netlify) ---
def estado_url():
    """URL del estado.json publicado por SIGEA (ej: https://x.netlify.app/estado.json)."""
    return str(_read("estado_url", "")).strip().rstrip("/")


def set_estado_url(url):
    _write("estado_url", (url or "").strip())


# --- Carpeta de trabajo local (sesión, fuera de OneDrive) ---
def carpeta_trabajo_local():
    """Carpeta donde QGIS edita la copia local. Vacío = default por SO."""
    return str(_read("carpeta_trabajo_local", "")).strip()


def set_carpeta_trabajo_local(ruta):
    _write("carpeta_trabajo_local", (ruta or "").strip())
