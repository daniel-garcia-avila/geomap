# Radar Geopolítico

Mapa mundial de sucesos en tiempo casi real. Funciona **sin servidor, sin base de datos y sin coste**:

- **GitHub Actions** ejecuta `scripts/recolectar.py` cada 15 minutos, descarga los datos y guarda `docs/data/eventos.json`.
- **GitHub Pages** publica la carpeta `docs/` como web.
- **MapLibre + OpenFreeMap** dibujan el mapa, sin clave de API.

Fase 1: terremotos (USGS) y desastres naturales activos (GDACS).

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
scripts/recolectar.py                    Descarga y normaliza los eventos (solo librería estándar)
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

Para añadir una fuente nueva (GDELT en la fase 2) basta con escribir otra función `recolectar_xxx()` que devuelva eventos con este formato y añadirla a la lista de `main()`.

## Limitaciones del plan gratuito

- GitHub puede retrasar unos minutos las tareas programadas en momentos de mucha carga.
- Si el repositorio pasa 60 días sin actividad, GitHub desactiva la tarea programada. Se reactiva desde la pestaña Actions.
- El mapa oscuro usa el estilo `dark` de OpenFreeMap. Si no estuviera disponible, la web cambia sola al estilo claro `positron`.
