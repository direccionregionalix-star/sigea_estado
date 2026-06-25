"""
Sesión local de trabajo — resuelve los conflictos de OneDrive.

PROBLEMA: QGIS bloquea el .gpkg con WAL/SHM mientras edita. OneDrive intenta
sincronizar ese archivo abierto, no puede, y crea copias de conflicto
("R01339-DESKTOP-ABC.gpkg"). Avisar con manifests no lo evitaba.

SOLUCIÓN: QGIS nunca abre el archivo directamente en OneDrive.
  1. Al cargar: se COPIA el .gpkg de OneDrive a una carpeta de trabajo LOCAL
     (fuera de OneDrive). QGIS edita esa copia local → OneDrive nunca ve un
     archivo abierto → cero conflictos.
  2. "Pausar y sincronizar": se cierra la copia local y se escribe de vuelta
     a OneDrive como R{codigo}.gpkg (nombre estable, sobrescritura atómica).
     OneDrive sincroniza un archivo cerrado y sano.
  3. Antes de sobrescribir, el anterior se mueve a _respaldos/ con timestamp.
     Se conservan los últimos 3. Sin ruido visual en la carpeta principal.
  4. Al recargar, el archivo bueno siempre es R{codigo}.gpkg — nombre estable,
     no hay que cazar timestamps.

CRÍTICO: el copiado es BINARIO (shutil.copy2), nunca por capas/atributos.
Así la geometría editada (el punto movido) viaja intacta — no se reconstruye
desde lat/lon, que fue la causa del bug de v4.14.
"""
import os
import glob
import time
import shutil
from datetime import datetime

from . import settings


MAX_RESPALDOS = 3
MAX_RESPALDOS_LOCAL = 5   # respaldos en el disco del funcionario (independiente de OneDrive)


def _dir_historico():
    """Carpeta local de respaldos históricos, en el disco del funcionario.
    Independiente de OneDrive: si OneDrive falla, esto salva el trabajo."""
    return _asegurar_dir(os.path.join(carpeta_trabajo(), "_historico"))


def respaldar_local(codigo, etiqueta="auto"):
    """Copia la sesión local actual a _historico/ con timestamp. Conserva los
    últimos MAX_RESPALDOS_LOCAL por recinto. Devuelve (ok, ruta_o_msg).
    NO cierra la sesión ni toca OneDrive — es un respaldo puro."""
    local = ruta_local(codigo)
    if not os.path.exists(local):
        return False, "No hay sesión local que respaldar."
    _limpiar_locks(local)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = os.path.join(_dir_historico(), f"R{codigo}_{ts}_{etiqueta}.gpkg")
    try:
        shutil.copy2(local, destino)
    except (OSError, shutil.Error) as e:
        return False, f"No pude respaldar localmente: {e}"
    # Rotar: conservar los últimos N por recinto
    respaldos = sorted(glob.glob(
        os.path.join(_dir_historico(), f"R{codigo}_*.gpkg")))
    for viejo in respaldos[:-MAX_RESPALDOS_LOCAL] if len(respaldos) > MAX_RESPALDOS_LOCAL else []:
        try:
            os.remove(viejo)
        except OSError:
            pass
    return True, destino


def carpeta_trabajo():
    """Carpeta local donde QGIS edita (fuera de OneDrive). Configurable;
    por defecto C:\\sigea_work (o ~/sigea_work en otros SO)."""
    manual = settings.carpeta_trabajo_local()
    if manual:
        return manual
    # Default por plataforma
    if os.name == "nt":
        base = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep,
                            "sigea_work")
    else:
        base = os.path.join(os.path.expanduser("~"), "sigea_work")
    return base


def _asegurar_dir(d):
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    return d


def ruta_local(codigo):
    """Ruta del .gpkg de trabajo local para este recinto."""
    return os.path.join(_asegurar_dir(carpeta_trabajo()), f"R{codigo}.gpkg")


def ruta_onedrive(codigo, usuario=None):
    """Ruta del .gpkg en la carpeta del funcionario en OneDrive."""
    from . import rutas
    return rutas.ruta_gpkg(codigo, usuario)


def _limpiar_locks(ruta):
    """Borra -wal y -shm sueltos de un gpkg (tras cerrar QGIS)."""
    for ext in ("-wal", "-shm"):
        try:
            if os.path.exists(ruta + ext):
                os.remove(ruta + ext)
        except OSError:
            pass


def abrir_sesion(codigo, usuario=None):
    """Copia el .gpkg de OneDrive a la carpeta local de trabajo.
    Devuelve (ruta_local, mensaje). Si ya hay copia local, la conserva
    (el funcionario podría estar retomando sin haber sincronizado)."""
    origen = ruta_onedrive(codigo, usuario)
    if not origen or not os.path.exists(origen):
        return None, f"No encuentro R{codigo}.gpkg en tu OneDrive."

    destino = ruta_local(codigo)

    # Si ya existe copia local más nueva que la de OneDrive, respetarla:
    # el funcionario está retomando trabajo no sincronizado.
    if os.path.exists(destino):
        t_local = os.path.getmtime(destino)
        t_one = os.path.getmtime(origen)
        if t_local >= t_one:
            return destino, ("Retomando tu trabajo local sin sincronizar. "
                             "Recuerda 'Pausar y sincronizar' al terminar.")

    # Copia binaria (geometría intacta) + limpiar locks heredados
    try:
        shutil.copy2(origen, destino)
        _limpiar_locks(destino)
    except (OSError, shutil.Error) as e:
        return None, f"No pude copiar a la carpeta local: {e}"
    return destino, "Trabajando en copia local. OneDrive no tocará el archivo abierto."


def _rotar_respaldos(codigo, gpkg_onedrive):
    """Mueve el R{codigo}.gpkg actual de OneDrive a _respaldos/ con timestamp.
    Conserva los últimos MAX_RESPALDOS."""
    if not os.path.exists(gpkg_onedrive):
        return
    carpeta = os.path.dirname(gpkg_onedrive)
    resp_dir = _asegurar_dir(os.path.join(carpeta, "_respaldos"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = os.path.join(resp_dir, f"R{codigo}_{ts}.gpkg")
    try:
        shutil.copy2(gpkg_onedrive, destino)
    except (OSError, shutil.Error):
        return
    # Conservar solo los últimos N
    respaldos = sorted(glob.glob(os.path.join(resp_dir, f"R{codigo}_*.gpkg")))
    sobrantes = respaldos[:-MAX_RESPALDOS] if len(respaldos) > MAX_RESPALDOS else []
    for viejo in sobrantes:
        try:
            os.remove(viejo)
        except OSError:
            pass


def sincronizar(codigo, usuario=None, manifest_cb=None):
    """Escribe la copia local de vuelta a OneDrive (sobrescritura atómica),
    respaldando el anterior. La capa ya debe estar QUITADA del proyecto y
    el archivo local cerrado antes de llamar esto.
    manifest_cb: función opcional (ruta) -> None para escribir el manifest.
    Devuelve (ok, mensaje)."""
    local = ruta_local(codigo)
    if not os.path.exists(local):
        return False, "No hay copia local que sincronizar."

    destino = ruta_onedrive(codigo, usuario)
    if not destino:
        return False, "No encuentro tu carpeta de OneDrive."

    _asegurar_dir(os.path.dirname(destino))
    _limpiar_locks(local)

    # Respaldar el actual de OneDrive antes de pisarlo
    _rotar_respaldos(codigo, destino)

    # Escritura atómica: copiar a .tmp y renombrar
    tmp = destino + ".tmp"
    try:
        shutil.copy2(local, tmp)
        os.replace(tmp, destino)
    except (OSError, shutil.Error) as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False, f"No pude escribir a OneDrive: {e}"

    # VERIFICACIÓN DE INTEGRIDAD: el archivo en OneDrive debe existir y
    # coincidir en tamaño y hash con la copia local. Si no, la sincronización
    # NO es confiable — avisar y NO borrar nada local.
    try:
        if not os.path.exists(destino):
            return False, "El archivo no quedó en OneDrive tras copiar."
        if os.path.getsize(destino) != os.path.getsize(local):
            return False, "El archivo en OneDrive quedó con tamaño distinto. "\
                          "Tu trabajo sigue a salvo en la copia local."
        if _hash_archivo(destino) != _hash_archivo(local):
            return False, "La verificación de integridad falló. Tu trabajo "\
                          "sigue a salvo en la copia local."
    except OSError as e:
        return False, f"No pude verificar la sincronización: {e}. "\
                      "Tu trabajo sigue a salvo en la copia local."

    # Manifest para que SIGEA pueda verificar la sincronización del otro lado
    if manifest_cb:
        try:
            manifest_cb(destino)
        except Exception:
            pass

    return True, ("Sincronizado y verificado en OneDrive. Espera a que OneDrive "
                  "suba el archivo (ícono verde) antes de cerrar el equipo.")


def _hash_archivo(ruta, bloque=1 << 20):
    """SHA-256 de un archivo, por bloques (no carga todo en memoria)."""
    import hashlib
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for chunk in iter(lambda: f.read(bloque), b""):
            h.update(chunk)
    return h.hexdigest()


def limpiar_local(codigo):
    """Cierra la sesión local de forma SEGURA: antes de quitar la copia de
    trabajo, la respalda en _historico/. Así NUNCA se pierde el trabajo,
    aunque OneDrive haya fallado en la nube. Devuelve True si todo ok."""
    local = ruta_local(codigo)
    if not os.path.exists(local):
        return True
    # 1) Respaldar SIEMPRE antes de borrar (la red de seguridad)
    respaldar_local(codigo, etiqueta="cierre")
    # 2) Recién entonces quitar la copia de trabajo activa
    _limpiar_locks(local)
    try:
        os.remove(local)
        return True
    except OSError:
        return False


def hay_sesion_local(codigo):
    """True si existe una copia local de trabajo para este recinto."""
    return os.path.exists(ruta_local(codigo))
