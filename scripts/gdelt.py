"""
GDELT 2.0: conflictos, protestas, política y crisis humanitarias.

GDELT publica cada 15 minutos un CSV con los sucesos detectados en noticias de todo
el mundo, ya clasificados con códigos CAMEO y geolocalizados. Es muy ruidoso:
la misma noticia aparece en cientos de medios y la geolocalización automática falla
a veces. Por eso aquí:

  1. Solo se usan los tipos de suceso que interesan (combates, protestas, amenazas…).
  2. Se descartan los sucesos situados solo a nivel de país (caerían en el centro del país).
  3. Se agrupan los sucesos del mismo tipo, en el mismo lugar y el mismo día en un único evento.
  4. Solo se muestran los grupos con suficientes artículos detrás.

El estado intermedio (grupos que aún no llegan al mínimo) se guarda en data/estado_gdelt.json.
"""

import csv
import gzip
import html
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from traducir import lugar_gdelt

RAIZ = Path(__file__).resolve().parent.parent
ESTADO = RAIZ / "data" / "estado_gdelt.json"
LASTUPDATE = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
URL_ARCHIVO = "http://data.gdeltproject.org/gdeltv2/{}.export.CSV.zip"
UA = {"User-Agent": "Mozilla/5.0 (compatible; RadarGeopolitico/1.0)"}

MAX_ARCHIVOS_POR_EJECUCION = 24   # 6 horas de datos; si se acumula retraso, se recupera en varias ejecuciones
HORAS_INICIALES = 6               # la primera vez, se cargan las últimas 6 h (luego el histórico crece solo)
VENTANA_HORAS = 72
MAX_TITULARES_POR_EJECUCION = 40  # titulares reales que se leen de las noticias en cada ejecución
MAX_EVENTOS = 700                 # tope de eventos GDELT en el mapa

# Columnas del CSV de eventos de GDELT 2.0 (61 columnas)
C_ID, C_DIA = 0, 1
C_ACTOR1, C_ACTOR2 = 6, 16
C_CODIGO, C_ES_RAIZ = 26, 25
C_ROOT = 28
C_MENCIONES, C_FUENTES, C_ARTICULOS, C_TONO = 31, 32, 33, 34
C_GEO_TIPO, C_GEO_NOMBRE, C_GEO_PAIS = 51, 52, 53
C_GEO_LAT, C_GEO_LON, C_GEO_ID = 56, 57, 58
C_FECHA_ALTA, C_URL = 59, 60

# Código CAMEO raíz -> (tipo en el mapa, gravedad base, nombre en español, mínimo de artículos para mostrarlo)
CATEGORIAS = {
    "04": ("politica", 1, "Reuniones diplomáticas", 25),
    "05": ("politica", 1, "Acuerdos diplomáticos", 20),
    "06": ("politica", 1, "Cooperación económica o militar", 20),
    "07": ("humanitaria", 1, "Ayuda humanitaria", 8),
    "13": ("politica", 1, "Amenazas", 15),
    "15": ("politica", 2, "Movilización militar", 8),
    "16": ("politica", 1, "Ruptura de relaciones o sanciones", 12),
    "17": ("politica", 2, "Represión y detenciones", 10),
    "14": ("protesta", 1, "Protestas", 6),
    "18": ("conflicto", 2, "Ataques", 6),
    "19": ("conflicto", 2, "Combates", 5),
    "20": ("conflicto", 3, "Violencia masiva", 4),
}

# Algunos códigos concretos dentro de esas familias, para afinar el título
SUBCODIGOS = {
    "145": "Disturbios", "1451": "Disturbios", "141": "Manifestaciones", "143": "Huelgas",
    "1823": "Asesinato selectivo", "183": "Atentado con explosivos", "1831": "Atentado suicida",
    "1832": "Atentado con explosivos", "1833": "Atentado con coche bomba", "181": "Secuestro",
    "190": "Enfrentamientos armados", "193": "Combates con armas ligeras", "194": "Bombardeos de artillería o tanques",
    "195": "Ataques aéreos", "1951": "Ataques con drones", "196": "Violación de alto el fuego",
    "202": "Matanza de civiles", "201": "Expulsiones masivas", "203": "Limpieza étnica",
    "173": "Detenciones", "175": "Represión violenta", "1721": "Toque de queda",
    "152": "Alerta militar", "154": "Movilización militar", "155": "Ciberataques",
    "163": "Sanciones o embargo", "166": "Expulsión de diplomáticos",
    "138": "Amenazas de ataque militar", "1384": "Amenaza nuclear", "071": "Ayuda económica", "073": "Ayuda humanitaria",
    "074": "Fuerzas de paz", "075": "Protección a refugiados", "057": "Firma de acuerdo", "046": "Negociaciones",
}


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _ts(dt):
    return dt.strftime("%Y%m%d%H%M%S")


def _redondear_15(dt):
    return dt.replace(minute=dt.minute - dt.minute % 15, second=0, microsecond=0)


def cargar_estado():
    try:
        return json.loads(ESTADO.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ultimo": None, "grupos": {}}


def guardar_estado(estado):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, separators=(",", ":")), "utf-8")


def ultimo_publicado():
    """Marca de tiempo del último archivo de eventos disponible en GDELT."""
    texto = _get(LASTUPDATE, 30).decode("utf-8", "replace")
    m = re.search(r"/(\d{14})\.export\.CSV\.zip", texto)
    if not m:
        raise RuntimeError("No se encontró el último archivo en lastupdate.txt")
    return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def filas(ts):
    """Descarga y lee un archivo de 15 minutos. Devuelve [] si GDELT no lo tiene."""
    try:
        datos = _get(URL_ARCHIVO.format(_ts(ts)))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        with z.open(z.namelist()[0]) as f:
            texto = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            return list(csv.reader(texto, delimiter="\t"))


def _float(x):
    try:
        return float(x)
    except ValueError:
        return None


def procesar_fila(r, grupos):
    if len(r) < 61 or r[C_ES_RAIZ] != "1":
        return
    root = r[C_ROOT].zfill(2)
    if root not in CATEGORIAS:
        return
    # 1 = solo país (cae en el centro del país, poco útil). 2-5 = región o ciudad.
    if r[C_GEO_TIPO] not in ("2", "3", "4", "5"):
        return
    lat, lon = _float(r[C_GEO_LAT]), _float(r[C_GEO_LON])
    if lat is None or lon is None:
        return
    lugar_id = r[C_GEO_ID] or f"{round(lat, 1)}:{round(lon, 1)}"
    dia = r[C_DIA]
    clave = f"{root}|{lugar_id}|{dia}"
    articulos = int(r[C_ARTICULOS] or 0)
    fuentes = int(r[C_FUENTES] or 0)
    alta = r[C_FECHA_ALTA]  # AAAAMMDDhhmmss

    g = grupos.get(clave)
    if not g:
        g = grupos[clave] = {
            "root": root, "lat": lat, "lon": lon, "nombre": r[C_GEO_NOMBRE],
            "dia": dia, "primero": alta, "ultimo": alta,
            "articulos": 0, "fuentes": 0, "eventos": 0,
            "codigos": {}, "actores": {}, "url": r[C_URL], "url_art": 0,
        }
    g["articulos"] += articulos
    g["fuentes"] += fuentes
    g["eventos"] += 1
    g["ultimo"] = max(g["ultimo"], alta)
    g["primero"] = min(g["primero"], alta)
    cod = r[C_CODIGO]
    g["codigos"][cod] = g["codigos"].get(cod, 0) + articulos
    for a in (r[C_ACTOR1], r[C_ACTOR2]):
        if a:
            g["actores"][a] = g["actores"].get(a, 0) + articulos
    if articulos > g["url_art"] and r[C_URL].startswith("http"):  # la noticia más difundida del grupo
        g["url"], g["url_art"] = r[C_URL], articulos


def podar(grupos, ahora):
    """Elimina grupos viejos y los pequeños que ya no van a crecer, para que el estado no engorde."""
    lim_total = _ts(ahora - timedelta(hours=VENTANA_HORAS))
    lim_pequeno = _ts(ahora - timedelta(hours=3))
    for k in list(grupos):
        g = grupos[k]
        minimo = CATEGORIAS[g["root"]][3]
        if g["ultimo"] < lim_total or (g["ultimo"] < lim_pequeno and g["articulos"] < minimo):
            del grupos[k]
        else:
            # solo nos interesan los 3 actores y códigos principales
            g["actores"] = dict(sorted(g["actores"].items(), key=lambda x: -x[1])[:3])
            g["codigos"] = dict(sorted(g["codigos"].items(), key=lambda x: -x[1])[:3])


def leer_titular(url):
    """Lee el <title> de la noticia original. Puede fallar (paywalls, bloqueos): entonces devuelve None."""
    try:
        req = urllib.request.Request(url, headers={**UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=6) as r:
            crudo = r.read(150_000)
            if r.headers.get("Content-Encoding") == "gzip":
                crudo = gzip.decompress(crudo)
        texto = crudo.decode("utf-8", "replace")
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', texto, re.I) \
            or re.search(r"<title[^>]*>(.*?)</title>", texto, re.I | re.S)
        if not m:
            return None
        t = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        t = re.split(r"\s[|\-–—]\s(?=[^|\-–—]{2,40}$)", t)[0].strip()  # quita " - Nombre del medio"
        return t[:180] if len(t) > 15 else None
    except Exception:
        return None


def gravedad(g):
    tipo, base, _, minimo = CATEGORIAS[g["root"]]
    sube = 1 if g["articulos"] >= minimo * 6 else 0
    sube += 1 if g["articulos"] >= minimo * 20 else 0
    return min(3, base + sube)


def a_evento(clave, g):
    tipo, _, nombre, minimo = CATEGORIAS[g["root"]]
    codigo = max(g["codigos"], key=g["codigos"].get) if g["codigos"] else ""
    titulo_tipo = SUBCODIGOS.get(codigo) or SUBCODIGOS.get(codigo[:3]) or nombre
    lugar = lugar_gdelt(g["nombre"])
    actores = [a.title() for a in list(g["actores"])[:3]]
    resumen = []
    if g.get("titular"):
        resumen.append(f"Titular: «{g['titular']}»")
    if actores:
        resumen.append("Actores: " + ", ".join(actores) + ".")
    resumen.append(f"Detectado en {g['articulos']} artículos de prensa.")
    fecha = datetime.strptime(g["ultimo"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return {
        "id": "gdelt-" + re.sub(r"[^A-Za-z0-9-]", "-", clave),
        "tipo": tipo,
        "gravedad": gravedad(g),
        "fecha": fecha.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lat": round(g["lat"], 4),
        "lon": round(g["lon"], 4),
        "lugar": lugar,
        "titulo": f"{titulo_tipo} en {lugar.split(',')[0]}",
        "resumen": " ".join(resumen),
        "fuente": "GDELT",
        "url": g["url"],
        "articulos": g["articulos"],
        # GDELT se extrae automáticamente de la prensa: no hay verificación humana.
        "verificacion": "dev" if g["articulos"] >= minimo * 4 else "no",
    }


def recolectar_gdelt():
    ahora = datetime.now(timezone.utc)
    estado = cargar_estado()
    grupos = estado["grupos"]

    publicado = ultimo_publicado()
    if estado["ultimo"]:
        siguiente = datetime.strptime(estado["ultimo"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) + timedelta(minutes=15)
    else:
        siguiente = _redondear_15(publicado - timedelta(hours=HORAS_INICIALES) + timedelta(minutes=15))
    siguiente = max(siguiente, _redondear_15(ahora - timedelta(hours=VENTANA_HORAS)))

    procesados = 0
    while siguiente <= publicado and procesados < MAX_ARCHIVOS_POR_EJECUCION:
        try:
            for r in filas(siguiente):
                procesar_fila(r, grupos)
        except Exception as e:
            print(f"  GDELT {_ts(siguiente)}: {e}", file=sys.stderr)
            break  # se reintenta en la próxima ejecución
        estado["ultimo"] = _ts(siguiente)
        siguiente += timedelta(minutes=15)
        procesados += 1
    pendientes = max(0, int((publicado - siguiente).total_seconds() // 900) + 1)
    print(f"  GDELT: {procesados} archivos procesados, {pendientes} pendientes")

    podar(grupos, ahora)

    visibles = [(k, g) for k, g in grupos.items() if g["articulos"] >= CATEGORIAS[g["root"]][3]]
    visibles.sort(key=lambda kg: -kg[1]["articulos"] / CATEGORIAS[kg[1]["root"]][3])
    visibles = visibles[:MAX_EVENTOS]

    # Titulares reales para los grupos más relevantes que aún no lo tienen
    leidos = 0
    for _, g in visibles:
        if leidos >= MAX_TITULARES_POR_EJECUCION:
            break
        if "titular" not in g and g.get("url"):
            g["titular"] = leer_titular(g["url"])
            leidos += 1

    guardar_estado(estado)
    return [a_evento(k, g) for k, g in visibles]
