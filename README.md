# Radar Geopolítico

Mapa mundial de sucesos en tiempo casi real. Funciona **sin servidor, sin base de datos y sin coste**:

- **GitHub Actions** ejecuta `scripts/recolectar.py` cada 15 minutos, descarga los datos y guarda `docs/data/eventos.json`.
- **GitHub Pages** publica la carpeta `docs/` como web.
- **MapLibre + OpenFreeMap** dibujan el mapa, sin clave de API.

Fuentes:

- **Terremotos**: USGS (Servicio Geológico de EE. UU.), magnitud 4,5 o más. Dato oficial.
- **Desastres naturales**: GDACS (ONU y Comisión Europea): ciclones, inundaciones, volcanes, sequías e incendios. Dato oficial.
- **Conflictos, protestas, política y crisis humanitarias**: GDELT, que analiza noticias de todo el mundo cada 15 minutos. Es extracción automática de prensa, sin verificación humana: la web lo indica en cada evento.

## Puesta en marcha (unos 10 minutos)

1. El repositorio debe ser **público** (en los públicos las Actions son gratuitas).
2. Sube todo el contenido de esta carpeta, incluida la carpeta oculta `.github`.
3. **Settings → Pages**: en *Source* elige *Deploy from a branch*, rama `main` y carpeta `/docs`. Guarda.
4. **Settings → Actions → General → Workflow permissions**: marca *Read and write permissions*. Guarda.
5. Pestaña **Actions** → *Actualizar datos* → **Run workflow** para lanzar la primera recogida sin esperar.
6. En uno o dos minutos la web estará en `https://daniel-garcia-avila.github.io/geomap/`.

A partir de ahí se actualiza sola. Solo se hace un commit cuando hay eventos nuevos.

## Probar en local

```bash
python scripts/recolectar.py      # descarga datos reales
cd docs && python -m http.server 8000
```

Abre http://localhost:8000

## Estructura

```
.github/workflows/actualizar-datos.yml   Tarea programada cada 15 min
scripts/recolectar.py                    Programa principal: USGS, GDACS y unión de todo (solo librería estándar)
scripts/gdelt.py                         Descarga, filtra y agrupa los sucesos de GDELT
scripts/traducir.py, paises_es.json      Traducción de países y ubicaciones al español
data/estado_gdelt.json                   Estado interno de GDELT (grupos que aún no llegan al mínimo)
docs/index.html, app.js, style.css       La web
docs/data/eventos.json                   Datos generados (no editar a mano)
```

## Formato de cada evento

```json
{
  "id": "usgs-us7000abc",
  "tipo": "sismo",            // conflicto | protesta | politica | humanitaria | desastre | sismo
  "gravedad": 2,              // 1 baja · 2 media · 3 grave
  "fecha": "2026-10-16T16:35:44Z",
  "lat": -23.6, "lon": -70.4,
  "lugar": "50 km SW of Antofagasta, Chile",
  "titulo": "Terremoto M6,1",
  "resumen": "Profundidad: 35 km.",
  "fuente": "USGS",
  "url": "https://earthquake.usgs.gov/...",
  "verificacion": "ok"        // ok | dev | no
}
```

## Cómo se filtra GDELT

GDELT detecta miles de sucesos cada hora y es muy ruidoso. El recolector:

1. Usa solo los tipos que interesan (códigos CAMEO): combates, ataques, violencia masiva, protestas, amenazas, movilización militar, sanciones, represión, diplomacia y ayuda humanitaria.
2. Descarta los sucesos situados solo a nivel de país.
3. Exige actores coherentes con el tipo de suceso: un combate necesita un actor armado (ejército, rebeldes, policía, gobierno o un grupo conocido); una reunión diplomática, dos países distintos con al menos un gobierno; la ayuda humanitaria, una ONG, un organismo internacional o un gobierno. Así se descartan noticias mal clasificadas.
4. Agrupa los del mismo tipo, lugar y día en un único evento.
5. Muestra solo los grupos con suficientes artículos detrás (el mínimo de cada tipo está en `CATEGORIAS`, en `scripts/gdelt.py`). Si ves demasiado ruido, sube esos números; si ves pocos eventos, bájalos.
6. Lee el titular real de la noticia más difundida de cada grupo y lo traduce al español.
7. Solo los sucesos violentos con muchísima cobertura llegan a gravedad máxima.

Si cambias los filtros y quieres que se apliquen también a lo ya acumulado, vacía `data/estado_gdelt.json` (deja `{"ultimo":null,"grupos":{}}`): en la siguiente ejecución se recargan las últimas 6 horas.

Para añadir otra fuente basta con escribir otra función `recolectar_xxx()` que devuelva eventos con este formato y añadirla a la lista de `main()`.

## Limitaciones del plan gratuito

- GitHub puede retrasar unos minutos las tareas programadas en momentos de mucha carga.
- Si el repositorio pasa 60 días sin actividad, GitHub desactiva la tarea programada. Se reactiva desde la pestaña Actions.
- El mapa oscuro usa el estilo `dark` de OpenFreeMap. Si no estuviera disponible, la web cambia sola al estilo claro `positron`.
