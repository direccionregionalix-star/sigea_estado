"""
Resolución de la ruta LOCAL del gpkg de trabajo.

Problema: SIGEA corre en el PC de Seba y calcula rutas con SU vista del
OneDrive. Cuando OneDrive comparte la carpeta, cada colega la ve con un
nombre distinto ("Archivos de Sebastián... - dev_007"), así que la ruta
absoluta de SIGEA NO sirve en el PC del funcionario.

Solución: el plugin ignora la ruta absoluta de SIGEA y arma la suya con
  {carpeta_base_local}/{usuario}/R{codigo}.gpkg
donde carpeta_base_local es la carpeta 'funcionarios' tal como la ve ESTE PC.
Se detecta automáticamente o se configura a mano una sola vez.
"""
import os
import glob

from . import settings


def _candidatos_onedrive():
    """Carpetas raíz de OneDrive probables en este PC."""
    cands = []
    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        v = os.environ.get(var)
        if v and os.path.isdir(v):
            cands.append(v)
    # Perfil de usuario: buscar carpetas "OneDrive*"
    perfil = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    if os.path.isdir(perfil):
        for d in glob.glob(os.path.join(perfil, "OneDrive*")):
            if os.path.isdir(d) and d not in cands:
                cands.append(d)
    return cands


def detectar_carpeta_base():
    """Intenta encontrar la carpeta 'funcionarios' del proyecto en este PC.
    Devuelve la ruta o None. Busca una subcarpeta '...dev_007*/funcionarios'
    bajo cualquier raíz de OneDrive, en hasta 4 niveles."""
    usuario = settings.usuario()
    for raiz in _candidatos_onedrive():
        # Patrón directo: .../dev_007*/funcionarios
        for prof in ("*/funcionarios", "*/*/funcionarios",
                     "*/*/*/funcionarios", "*/*/*/*/funcionarios"):
            for cand in glob.glob(os.path.join(raiz, prof)):
                base = os.path.basename(os.path.dirname(cand)).lower()
                # Preferir las que vienen de dev_007 o tienen la carpeta del usuario
                if "dev_007" in cand.lower() or (
                        usuario and os.path.isdir(os.path.join(cand, usuario))):
                    return cand
        # Fallback: cualquier 'funcionarios' que contenga la carpeta del usuario
        if usuario:
            for prof in ("*/funcionarios", "*/*/funcionarios",
                         "*/*/*/funcionarios", "*/*/*/*/funcionarios"):
                for cand in glob.glob(os.path.join(raiz, prof)):
                    if os.path.isdir(os.path.join(cand, usuario)):
                        return cand
    return None


def carpeta_base():
    """Carpeta base efectiva: la configurada a mano, o la autodetectada.
    Si detecta una y no había ninguna guardada, la guarda."""
    manual = settings.carpeta_base_local()
    if manual and os.path.isdir(manual):
        return manual
    auto = detectar_carpeta_base()
    if auto:
        settings.set_carpeta_base_local(auto)
        return auto
    return manual or ""


def ruta_gpkg(codigo, usuario=None):
    """Ruta local del gpkg del recinto en ESTE PC, o None si no hay base."""
    base = carpeta_base()
    if not base:
        return None
    usr = usuario or settings.usuario()
    return os.path.join(base, usr, f"R{codigo}.gpkg")


def diagnostico():
    """Texto corto para mostrar en el plugin: qué carpeta está usando."""
    base = carpeta_base()
    if not base:
        return "✗ No encuentro la carpeta de trabajo. Configúrala con 'Examinar'."
    usr = settings.usuario()
    carpeta_usr = os.path.join(base, usr)
    if not os.path.isdir(carpeta_usr):
        return (f"⚠ Carpeta base OK pero no existe la subcarpeta '{usr}'. "
                f"¿Es correcto tu usuario?")
    n = len(glob.glob(os.path.join(carpeta_usr, "R*.gpkg")))
    return f"✓ {carpeta_usr} ({n} recinto(s))"
