"""
Recolector de eventos para Radar Geopolítico.

Descarga terremotos (USGS), desastres naturales (GDACS) y sucesos geopolíticos
(GDELT), los normaliza a un formato común y los guarda en docs/data/eventos.json.

Solo usa la biblioteca estándar de Python: no hay que instalar nada.
"""

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gdelt import recolectar_gdelt
from traducir import lista_paises, lugar_usgs

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "data" / "eventos.json"
VENTANA_HORAS = 72
TIMEOUT = 30
UA = {"User-Agent": "RadarGeopolitico/1.0 (+https://github.com)"}

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/EVENTS4APP"

TIPOS_GDACS = {  # (singular, plural)
    "TC": ("Ciclón tropical", "Ciclones tropicales"),
    "FL": ("Inundación", "Inundaciones"),
    "VO": ("Erupción volcánica", "Erupciones volcánicas"),
    "DR": ("Sequía", "Sequías"),
    "WF": ("Incendio forestal", "Incendios forestales"),
}
NOMBRE_ALERTA = {1: "verde", 2: "naranja", 3: "roja"}
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
            "lugar": lugar_usgs(p.get("place")),
            "titulo": f"Terremoto M{mag:.1f}".replace(".", ","),
            "resumen": resumen,
            "fuente": "USGS",
            "url": p.get("url"),
            "verificacion": "ok" if p.get("status") == "reviewed" else "dev",
        })
    return eventos


def recolectar_gdacs():
    """
    GDACS envía cada foco de incendio por separado, así que los incendios del mismo país
    se agrupan en un solo evento situado en el foco más grave. El resto de desastres
    (ciclones, inundaciones, volcanes, sequías) se mantienen uno a uno.
    """
    datos = descargar_json(GDACS_URL)
    eventos, incendios = [], {}
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
        url = p.get("url")
        if isinstance(url, dict):
            url = url.get("report") or url.get("details")
        grav = ALERTA_GDACS.get(str(p.get("alertlevel", "")).lower(), 1)
        paises = lista_paises(p.get("country") or "") or "Ubicación desconocida"
        singular, plural = TIPOS_GDACS[tipo]

        if tipo == "WF":
            g = incendios.setdefault(paises, {"n": 0, "grav": 0})
            g["n"] += 1
            if grav > g["grav"] or (grav == g["grav"] and iso(fecha) > g["fecha"]):
                g.update(grav=grav, fecha=iso(fecha), pos=pos, url=url, id=p.get("eventid"))
            continue

        nombre = (p.get("eventname") or "").strip()
        titulo = f"{singular} {nombre.title()}" if tipo in ("TC", "VO") and nombre else f"{singular} en {paises}"
        resumen = f"Nivel de alerta GDACS: {NOMBRE_ALERTA[grav]}."
        sev = (p.get("severitydata") or {}).get("severitytext")
        if sev:
            resumen += f" Datos técnicos: {sev}."
        eventos.append({
            "id": f"gdacs-{tipo}-{p.get('eventid')}",
            "tipo": "desastre",
            "gravedad": grav,
            "fecha": iso(fecha),
            "lat": round(pos[0], 4),
            "lon": round(pos[1], 4),
            "lugar": paises,
            "titulo": titulo,
            "resumen": resumen,
            "fuente": "GDACS",
            "url": url,
            "verificacion": "ok",
        })

    for paises, g in incendios.items():
        focos = f"{g['n']} focos activos" if g["n"] > 1 else "1 foco activo"
        eventos.append({
            "id": f"gdacs-WF-{g['id']}",
            "tipo": "desastre",
            "gravedad": g["grav"],
            "fecha": g["fecha"],
            "lat": round(g["pos"][0], 4),
            "lon": round(g["pos"][1], 4),
            "lugar": paises,
            "titulo": ("Incendios forestales" if g["n"] > 1 else "Incendio forestal") + f" en {paises}",
            "resumen": f"{focos} según GDACS. El punto marca el foco más grave. Nivel de alerta máximo: {NOMBRE_ALERTA[g['grav']]}.",
            "fuente": "GDACS",
            "url": g["url"],
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

    for nombre, funcion in (("USGS", recolectar_usgs), ("GDACS", recolectar_gdacs), ("GDELT", recolectar_gdelt)):
        prefijo = nombre.lower() + "-"
        try:
            nuevos = funcion()
            eventos += nuevos
            fuentes_ok.append(nombre)
            print(f"{nombre}: {len(nuevos)} eventos")
        except Exception as err:  # una fuente caída no debe tumbar el resto
            eventos += [e for e in existentes if e["id"].startswith(prefijo)]
            print(f"{nombre}: error -> {err}. Se mantienen los datos anteriores.", file=sys.stderr)

    # Terremotos y sucesos GDELT: solo los de las últimas 72 h.
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
    }, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"Guardados {len(eventos)} eventos en {SALIDA.name}")


if __name__ == "__main__":
    main()
