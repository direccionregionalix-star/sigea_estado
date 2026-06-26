def classFactory(iface):
    from .plugin import SigeaPlugin
    return SigeaPlugin(iface)
