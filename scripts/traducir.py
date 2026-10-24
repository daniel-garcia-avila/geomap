"""Traducción al español de nombres de países y ubicaciones (sin servicios externos)."""

import json
import re
from pathlib import Path

PAISES = json.loads((Path(__file__).parent / "paises_es.json").read_text("utf-8"))

RUMBOS = str.maketrans({"W": "O"})  # N, S, E, O (oeste)


def pais(nombre):
    """'Russia' -> 'Rusia'. Si no se conoce, devuelve el nombre tal cual."""
    if not nombre:
        return nombre
    limpio = nombre.strip()
    return PAISES.get(limpio.lower(), limpio)


def lista_paises(texto):
    """'Zimbabwe, Mozambique, Zambia' -> 'Zimbabue, Mozambique y Zambia'."""
    partes = [pais(p) for p in texto.split(",") if p.strip()]
    if len(partes) <= 1:
        return partes[0] if partes else ""
    return ", ".join(partes[:-1]) + " y " + partes[-1]


def lugar_usgs(texto):
    """'101 km SSE of Vilyuchinsk, Russia' -> 'A 101 km al SSE de Vilyuchinsk, Rusia'."""
    if not texto:
        return "Ubicación desconocida"
    m = re.match(r"^(\d+)\s*km\s+([NSEW]{1,3})\s+of\s+(.+)$", texto)
    if m:
        km, rumbo, resto = m.groups()
        return f"A {km} km al {rumbo.translate(RUMBOS)} de {lugar_simple(resto)}"
    t = re.sub(r"^(south|north|east|west) of (the )?", lambda x: {"south": "Al sur de ", "north": "Al norte de ", "east": "Al este de ", "west": "Al oeste de "}[x.group(1).lower()], texto, flags=re.I)
    t = re.sub(r"\s+region$", " (región)", t, flags=re.I)
    return lugar_simple(t)


def lugar_simple(texto):
    """Traduce el último componente si es un país: 'Port-Olry, Vanuatu' -> 'Port-Olry, Vanuatu'."""
    partes = [p.strip() for p in texto.split(",")]
    partes[-1] = pais(partes[-1])
    return ", ".join(partes)


def lugar_gdelt(nombre_completo):
    """'Kyiv, Kyyiv, Misto, Ukraine' -> 'Kyiv, Ucrania'. 'Donets'k, Ukraine (general)' -> 'Donets'k, Ucrania'."""
    if not nombre_completo:
        return ""
    partes = [re.sub(r"\s*\(general\)", "", p).strip() for p in nombre_completo.split(",")]
    partes = [p for p in partes if p]
    if len(partes) == 1:
        return pais(partes[0])
    return f"{partes[0]}, {pais(partes[-1])}"


# ---------- Traducción de textos libres (titulares) ----------
# Usa el traductor web de Google en su modo gratuito (sin clave). No es una API oficial:
# si algún día deja de responder, la web muestra el titular original y se reintenta más tarde.

import urllib.parse
import urllib.request

_TRADUCTOR = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=es&dt=t&q="


def a_espanol(texto, timeout=8):
    """Devuelve el texto en español, o None si no se ha podido traducir (para reintentarlo después)."""
    if not texto:
        return None
    req = urllib.request.Request(_TRADUCTOR + urllib.parse.quote(texto), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    try:
        traduccion = "".join(seg[0] for seg in datos[0] if seg and seg[0]).strip()
    except (TypeError, IndexError):
        return None
    return traduccion or None
