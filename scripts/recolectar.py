"""
Recolector de eventos para Radar Geopolítico.

Descarga terremotos (USGS) y desastres naturales (GDACS), los normaliza
a un formato común y los guarda en docs/data/eventos.json, conservando
los eventos de las últimas 72 horas.

Solo usa la biblioteca estándar de Python: no hay que instalar nada.
"""

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "data" / "eventos.json"
VENTANA_HORAS = 72
TIMEOUT = 30
UA = {"User-Agent": "RadarGeopolitico/1.0 (+https://github.com)"}

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"

TIPOS_GDACS = {
    "TC": "Ciclón tropical",
    "FL": "Inundación",
    "VO": "Erupción volcánica",
    "DR": "Sequía",
    "WF": "Incendio forestal",
}
ALERTA_GDACS = {"green": 1, "orange": 2, "red": 3}


def descargar_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def centro(geom):
    """Devuelve (lat, lon) de un Point o el centro aproximado de otra geometría."""
    if not geom:
        return None
    t, c = geom.get("type"), geom.get("coordinates")
    if t == "Point" and c:
        return c[1], c[0]
    # Para polígonos u otras formas: media de todos los vértices
    pts = []

    def recorrer(x):
        if isinstance(x, (list, tuple)) and x and isinstance(x[0], (int, float)):
            pts.append(x)
        elif isinstance(x, (list, tuple)):
            for y in x:
                recorrer(y)

    recorrer(c)
    if not pts:
        return None
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def gravedad_sismo(mag):
    if mag >= 6.5:
        return 3
    if mag >= 5.5:
        return 2
    return 1


def recolectar_usgs():
    datos = descargar_json(USGS_URL)
    eventos = []
    for f in datos.get("features", []):
        p = f.get("properties", {})
        lon, lat = f["geometry"]["coordinates"][:2]
        mag = p.get("mag") or 0
        fecha = datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc)
        resumen = f"Profundidad: {f['geometry']['coordinates'][2]:.0f} km."
        if p.get("tsunami"):
            resumen += " Aviso de posible tsunami emitido."
        eventos.append({
            "id": f"usgs-{f['id']}",
            "tipo": "sismo",
            "gravedad": gravedad_sismo(mag),
            "fecha": iso(fecha),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "lugar": p.get("place") or "Ubicación desconocida",
            "titulo": f"Terremoto M{mag:.1f}".replace(".", ","),
            "resumen": resumen,
            "fuente": "USGS",
            "url": p.get("url"),
            "verificacion": "ok" if p.get("status") == "reviewed" else "dev",
        })
    return eventos


def recolectar_gdacs():
    datos = descargar_json(GDACS_URL)
    eventos = []
    for f in datos.get("features", []):
        p = f.get("properties", {})
        tipo = p.get("eventtype")
        if tipo not in TIPOS_GDACS:  # los terremotos ya vienen de USGS
            continue
        pos = centro(f.get("geometry"))
        if not pos:
            continue
        try:
            fecha = datetime.fromisoformat(p.get("fromdate", "").replace("Z", "")).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        nombre = p.get("name") or p.get("eventname") or TIPOS_GDACS[tipo]
        url = p.get("url")
        if isinstance(url, dict):
            url = url.get("report") or url.get("details")
        eventos.append({
            "id": f"gdacs-{tipo}-{p.get('eventid')}",
            "tipo": "desastre",
            "gravedad": ALERTA_GDACS.get(str(p.get("alertlevel", "")).lower(), 1),
            "fecha": iso(fecha),
            "lat": round(pos[0], 4),
            "lon": round(pos[1], 4),
            "lugar": p.get("country") or "Ubicación desconocida",
            "titulo": f"{TIPOS_GDACS[tipo]}: {nombre}",
            "resumen": p.get("description") or "",
            "fuente": "GDACS",
            "url": url,
            "verificacion": "ok",
        })
    return eventos


def cargar_existentes():
    try:
        return json.loads(SALIDA.read_text("utf-8")).get("eventos", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def main():
    ahora = datetime.now(timezone.utc)
    limite = iso(ahora - timedelta(hours=VENTANA_HORAS))

    # Cada fuente que responde sustituye sus propios eventos por la versión más reciente.
    # Si una fuente falla, se conservan los eventos que ya teníamos de ella.
    existentes = cargar_existentes()
    eventos = []
    fuentes_ok = []

    for nombre, funcion in (("USGS", recolectar_usgs), ("GDACS", recolectar_gdacs)):
        prefijo = nombre.lower() + "-"
        try:
            nuevos = funcion()
            eventos += nuevos
            fuentes_ok.append(nombre)
            print(f"{nombre}: {len(nuevos)} eventos")
        except Exception as err:  # una fuente caída no debe tumbar el resto
            eventos += [e for e in existentes if e["id"].startswith(prefijo)]
            print(f"{nombre}: error -> {err}. Se mantienen los datos anteriores.", file=sys.stderr)

    # Terremotos: solo los de las últimas 72 h.
    # Desastres: GDACS solo lista los activos, así que se muestran mientras sigan en su lista
    # (una sequía o inundación puede durar semanas).
    eventos = [e for e in eventos if e["tipo"] == "desastre" or e["fecha"] >= limite]
    eventos.sort(key=lambda e: e["fecha"], reverse=True)

    # Si nada ha cambiado, no tocamos el archivo: así no se crea un commit vacío cada 15 min.
    if eventos == existentes:
        print("Sin eventos nuevos; el archivo no se modifica.")
        return

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({
        "actualizado": iso(ahora),
        "fuentes": fuentes_ok,
        "eventos": eventos,
    }, ensure_ascii=False, indent=1), "utf-8")
    print(f"Guardados {len(eventos)} eventos en {SALIDA.name}")


if __name__ == "__main__":
    main()
