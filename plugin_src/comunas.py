"""
Comunas de La Araucanía — resolución del código SII de 4 dígitos que pide
SIGEC, a partir de lo que traiga la capa de trabajo (código CUT, código SII
o nombre).

El código SIGEC (4 dígitos, ej. "9115" Pucón) coincide con el código CUT sin
el cero a la izquierda. Si la capa trae el nombre, se invierte el mapa.
"""

# Código SII/CUT de 4 dígitos → nombre (las 32 comunas de Araucanía)
COMUNAS = {
    "9101": "Temuco", "9102": "Carahue", "9103": "Cunco",
    "9104": "Curarrehue", "9105": "Freire", "9106": "Galvarino",
    "9107": "Gorbea", "9108": "Lautaro", "9109": "Loncoche",
    "9110": "Melipeuco", "9111": "Nueva Imperial", "9112": "Padre Las Casas",
    "9113": "Perquenco", "9114": "Pitrufquén", "9115": "Pucón",
    "9116": "Saavedra", "9117": "Teodoro Schmidt", "9118": "Toltén",
    "9119": "Vilcún", "9120": "Villarrica", "9121": "Cholchol",
    "9201": "Angol", "9202": "Collipulli", "9203": "Curacautín",
    "9204": "Ercilla", "9205": "Lonquimay", "9206": "Los Sauces",
    "9207": "Lumaco", "9208": "Purén", "9209": "Renaico",
    "9210": "Traiguén", "9211": "Victoria",
}


def _normalizar_texto(s):
    """minúsculas, sin tildes, sin espacios extra — para comparar nombres."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ñ", "n")):
        s = s.replace(a, b)
    return " ".join(s.split())


# Mapa inverso nombre normalizado → código
_POR_NOMBRE = {_normalizar_texto(v): k for k, v in COMUNAS.items()}


def codigo_sigec(valor):
    """Resuelve el código SII de 4 dígitos que pide SIGEC desde lo que sea
    que traiga la capa: código CUT ('09115'), código SII ('9115'), float
    ('9115.0') o nombre ('Pucón'). Devuelve el código o None si no se puede."""
    if valor is None:
        return None
    bruto = str(valor).strip()
    if not bruto:
        return None

    # ¿Es numérico (código)? Quitar parte decimal y ceros a la izquierda
    candidato = bruto.split(".")[0].lstrip("0")
    if candidato.isdigit():
        # CUT de Araucanía = 4 dígitos empezando en 91xx o 92xx
        if candidato in COMUNAS:
            return candidato
        # A veces viene el código de 5 dígitos sin cero (raro) o con región
        if len(candidato) == 5 and candidato[0] == "0":
            c2 = candidato.lstrip("0")
            if c2 in COMUNAS:
                return c2

    # ¿Es nombre?
    cod = _POR_NOMBRE.get(_normalizar_texto(bruto))
    if cod:
        return cod

    return None


def nombre_de(codigo):
    """Nombre de comuna desde su código, acepta 4 dígitos ('9121') o 5 con
    cero a la izquierda ('09121', formato CUT que usa central.gpkg). Si no
    se reconoce, devuelve el código tal cual se recibió."""
    bruto = str(codigo).strip()
    candidato = bruto.lstrip("0")
    return COMUNAS.get(candidato, bruto)


def opciones_ordenadas():
    """Lista [(codigo, nombre)] ordenada por nombre, para poblar un combo."""
    return sorted(COMUNAS.items(), key=lambda kv: kv[1])
