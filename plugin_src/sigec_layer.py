"""
Convierte resultados de SIGEC en una capa temporal de QGIS (memoria, 4326),
con los polígonos de predios etiquetados por dirección.

Sigue el patrón de carga de capas del plugin: QgsVectorLayer de memoria,
sin tocar la capa de trabajo. La capa se agrega aparte y se le hace zoom.
"""
import json

from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsField, QgsFields,
    QgsProject, QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import QVariant


def _geom_desde_geojson(geom_geojson):
    """Construye una QgsGeometry desde el geom_geojson (dict o str)."""
    if geom_geojson is None:
        return None
    if isinstance(geom_geojson, str):
        try:
            geom_geojson = json.loads(geom_geojson)
        except (ValueError, TypeError):
            return None
    try:
        return QgsGeometry.fromWkt(_geojson_a_wkt(geom_geojson))
    except Exception:
        return None


def _geojson_a_wkt(g):
    """GeoJSON Polygon/MultiPolygon → WKT. Implementación mínima sin libs."""
    t = g.get("type")
    coords = g.get("coordinates", [])

    def anillo(pts):
        return "(" + ", ".join(f"{p[0]} {p[1]}" for p in pts) + ")"

    def poligono(rings):
        return "(" + ", ".join(anillo(r) for r in rings) + ")"

    if t == "Polygon":
        return "POLYGON " + poligono(coords)
    if t == "MultiPolygon":
        return "MULTIPOLYGON (" + ", ".join(poligono(p) for p in coords) + ")"
    if t == "Point":
        return f"POINT ({coords[0]} {coords[1]})"
    raise ValueError(f"Tipo de geometría no soportado: {t}")


def resultados_a_capa(resultados, nombre_capa="SIGEC · resultados"):
    """Crea una capa de memoria con los polígonos de los resultados.
    Devuelve la capa (no la agrega al proyecto) o None si no hay geometrías."""
    fields = QgsFields()
    fields.append(QgsField("rol", QVariant.String))
    fields.append(QgsField("direccion", QVariant.String))
    fields.append(QgsField("score", QVariant.Double))
    fields.append(QgsField("lat", QVariant.Double))
    fields.append(QgsField("lon", QVariant.Double))

    capa = QgsVectorLayer("MultiPolygon?crs=EPSG:4326", nombre_capa, "memory")
    if not capa.isValid():
        return None
    dp = capa.dataProvider()
    dp.addAttributes(fields.toList())
    capa.updateFields()

    feats = []
    for r in resultados:
        geom = _geom_desde_geojson(r.get("geom_geojson"))
        if geom is None or geom.isEmpty():
            continue
        f = QgsFeature(capa.fields())
        f.setGeometry(geom)
        f.setAttribute("rol", str(r.get("rol", "")))
        f.setAttribute("direccion", str(r.get("direccion", "")))
        f.setAttribute("score", float(r.get("score") or 0))
        f.setAttribute("lat", float(r.get("lat") or 0))
        f.setAttribute("lon", float(r.get("lon") or 0))
        feats.append(f)

    if not feats:
        return None
    dp.addFeatures(feats)
    capa.updateExtents()
    _aplicar_estilo(capa)
    return capa


def _aplicar_estilo(capa):
    """Relleno semitransparente + etiqueta con la dirección."""
    try:
        capa.renderer().symbol().setOpacity(0.45)
    except Exception:
        pass
    try:
        from qgis.core import (QgsPalLayerSettings, QgsTextFormat,
                               QgsVectorLayerSimpleLabeling)
        from qgis.PyQt.QtGui import QFont
        s = QgsPalLayerSettings()
        s.fieldName = "direccion"
        s.enabled = True
        fmt = QgsTextFormat()
        fmt.setFont(QFont("Sans", 8))
        s.setFormat(fmt)
        capa.setLabeling(QgsVectorLayerSimpleLabeling(s))
        capa.setLabelsEnabled(True)
    except Exception:
        pass


def capa_un_resultado(resultado, nombre_capa=None):
    """Capa temporal con un solo predio elegido."""
    nombre = nombre_capa or f"SIGEC · {resultado.get('rol', 'predio')}"
    return resultados_a_capa([resultado], nombre)
