// Radar Geopolítico — mapa de sucesos
// Lee data/eventos.json (generado por la GitHub Action) y lo pinta en un mapa MapLibre.

const DATOS_URL = "data/eventos.json";
const REFRESCO_MS = 5 * 60 * 1000; // vuelve a leer los datos cada 5 minutos

// Estilos de mapa gratuitos de OpenFreeMap (sin clave de API).
// Se intenta el oscuro y, si no estuviera disponible, se usa el claro.
const ESTILOS = [
  "https://tiles.openfreemap.org/styles/dark",
  "https://tiles.openfreemap.org/styles/positron",
];

const TIPOS = {
  conflicto:   { label: "Conflictos",          color: "#ef5b5b" },
  protesta:    { label: "Protestas",           color: "#ffb347" },
  politica:    { label: "Política",            color: "#6aa9ff" },
  humanitaria: { label: "Crisis humanitarias", color: "#46d1c2" },
  desastre:    { label: "Desastres naturales", color: "#c58cf0" },
  sismo:       { label: "Terremotos",          color: "#93d35a" },
};
// Qué significa la verificación depende de la fuente:
// USGS y GDACS son organismos oficiales; GDELT se extrae automáticamente de la prensa.
function verificacion(e) {
  if (e.fuente === "GDELT") {
    return e.verificacion === "dev"
      ? `Muy difundido en prensa (${e.articulos} artículos), sin verificación oficial`
      : `Extraído de prensa (${e.articulos} artículos), sin verificar`;
  }
  return e.verificacion === "ok" ? `Dato oficial (${e.fuente})` : `Dato oficial preliminar (${e.fuente})`;
}

const estado = { eventos: [], actualizado: null, tipos: new Set(Object.keys(TIPOS)), horas: 72, q: "", sel: null };
let mapa, popup;

// ---------- Utilidades ----------
const $ = (id) => document.getElementById(id);
const puntos = (g) => "●".repeat(g) + "○".repeat(3 - g);
function hace(fecha) {
  const min = Math.round((Date.now() - new Date(fecha)) / 60000);
  if (min < 1) return "ahora";
  if (min < 60) return `hace ${min} min`;
  const h = Math.floor(min / 60);
  return h < 48 ? `hace ${h} h` : `hace ${Math.floor(h / 24)} d`;
}
function el(tag, props = {}, ...hijos) {
  const e = Object.assign(document.createElement(tag), props);
  for (const h of hijos) e.append(h);
  return e;
}

// ---------- Filtrado ----------
function visibles() {
  const desde = Date.now() - estado.horas * 3600e3;
  const q = estado.q.trim().toLowerCase();
  return estado.eventos.filter((e) =>
    estado.tipos.has(e.tipo) &&
    // los desastres activos (sequías, inundaciones…) se muestran aunque empezaran antes
    (e.tipo === "desastre" || new Date(e.fecha) >= desde) &&
    (!q || `${e.titulo} ${e.lugar} ${TIPOS[e.tipo]?.label}`.toLowerCase().includes(q))
  );
}

// ---------- Mapa ----------
async function elegirEstilo() {
  for (const url of ESTILOS) {
    try { if ((await fetch(url, { method: "HEAD" })).ok) return url; } catch {}
  }
  return ESTILOS[ESTILOS.length - 1];
}

async function iniciarMapa() {
  mapa = new maplibregl.Map({
    container: "map",
    style: await elegirEstilo(),
    center: [15, 25],
    zoom: 1.6,
    attributionControl: { compact: true },
  });
  mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  await new Promise((ok) => mapa.on("load", ok));

  mapa.addSource("eventos", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

  const color = ["match", ["get", "tipo"], ...Object.entries(TIPOS).flatMap(([k, t]) => [k, t.color]), "#cccccc"];
  const radio = ["interpolate", ["linear"], ["zoom"],
    1, ["*", ["get", "gravedad"], 2.5],
    8, ["*", ["get", "gravedad"], 6]];

  // Halo para los eventos graves
  mapa.addLayer({
    id: "eventos-halo", type: "circle", source: "eventos",
    filter: ["==", ["get", "gravedad"], 3],
    paint: { "circle-color": color, "circle-radius": ["*", radio, 2.2], "circle-opacity": 0.18, "circle-blur": 0.6 },
  });
  mapa.addLayer({
    id: "eventos", type: "circle", source: "eventos",
    paint: {
      "circle-color": color,
      "circle-radius": radio,
      "circle-stroke-color": ["case", ["==", ["get", "id"], ""], "#e9d8a6", "#0a1520"],
      "circle-stroke-width": 1.2,
    },
  });

  mapa.on("click", "eventos", (e) => seleccionar(e.features[0].properties.id, false));
  mapa.on("mouseenter", "eventos", () => (mapa.getCanvas().style.cursor = "pointer"));
  mapa.on("mouseleave", "eventos", () => (mapa.getCanvas().style.cursor = ""));
}

// ---------- Pintado ----------
function pintar() {
  const lista = visibles();

  if (mapa?.getSource("eventos")) {
    mapa.getSource("eventos").setData({
      type: "FeatureCollection",
      features: [...lista].sort((a, b) => a.gravedad - b.gravedad).map((e) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [e.lon, e.lat] },
        properties: { id: e.id, tipo: e.tipo, gravedad: e.gravedad },
      })),
    });
    mapa.setPaintProperty("eventos", "circle-stroke-color",
      ["case", ["==", ["get", "id"], estado.sel || ""], "#e9d8a6", "#0a1520"]);
    mapa.setPaintProperty("eventos", "circle-stroke-width",
      ["case", ["==", ["get", "id"], estado.sel || ""], 3, 1.2]);
  }

  // Recuento por tipo en los chips
  const n = {};
  for (const e of estado.eventos) n[e.tipo] = (n[e.tipo] || 0) + 1;
  document.querySelectorAll(".chip").forEach((c) => {
    c.hidden = !n[c.dataset.tipo];
    c.querySelector(".n").textContent = n[c.dataset.tipo] || 0;
  });

  // Feed
  const feed = $("feed");
  feed.replaceChildren();
  if (!lista.length) feed.append(el("div", { className: "empty", textContent: "No hay eventos con estos filtros." }));
  for (const e of lista) {
    const t = TIPOS[e.tipo] || { label: e.tipo, color: "#ccc" };
    const b = el("button", { className: "item" + (e.id === estado.sel ? " sel" : ""), onclick: () => seleccionar(e.id, true) },
      el("span", { className: "bar", style: `background:${t.color}` }),
      el("span", {},
        el("div", { className: "meta" },
          el("span", { textContent: t.label }),
          el("span", { textContent: puntos(e.gravedad), style: `color:${t.color}` })),
        el("div", { className: "t", textContent: e.titulo }),
        el("div", { className: "meta" },
          el("span", { textContent: e.lugar }),
          el("span", { textContent: hace(e.fecha) }))));
    b.dataset.id = e.id;
    feed.append(b);
  }

  $("feedcount").textContent = `${lista.length} eventos`;
  $("s-total").textContent = lista.length;
  $("s-crit").textContent = lista.filter((e) => e.gravedad === 3).length;
  $("s-upd").textContent = estado.actualizado ? hace(estado.actualizado) : "–";
  // Si los datos tienen más de una hora, el indicador "EN VIVO" se apaga
  const viejo = !estado.actualizado || Date.now() - new Date(estado.actualizado) > 3600e3;
  document.querySelector(".live").classList.toggle("stale", viejo);
}

function seleccionar(id, volar) {
  const e = estado.eventos.find((x) => x.id === id);
  if (!e) return;
  estado.sel = id;
  const t = TIPOS[e.tipo] || { label: e.tipo, color: "#ccc" };

  const cont = el("div", { className: "pop" },
    el("div", { className: "type", textContent: `${t.label}  ${puntos(e.gravedad)}`, style: `color:${t.color}` }),
    el("h2", { textContent: e.titulo }),
    el("div", { className: "place", textContent: e.lugar }));
  if (e.resumen) cont.append(el("p", { textContent: e.resumen }));
  const meta = el("div", { className: "meta" },
    el("span", { textContent: `${new Date(e.fecha).toISOString().slice(0, 16).replace("T", " ")} UTC` }),
    el("span", { textContent: verificacion(e) }));
  if (e.url) meta.append(el("a", { href: e.url, target: "_blank", rel: "noopener",
    textContent: e.fuente === "GDELT" ? "Leer la noticia" : `Ver en ${e.fuente}` }));
  cont.append(meta);

  popup?.remove();
  popup = new maplibregl.Popup({ offset: 12, maxWidth: "320px" }).setLngLat([e.lon, e.lat]).setDOMContent(cont).addTo(mapa);
  popup.on("close", () => { if (estado.sel === id) { estado.sel = null; pintar(); } });

  if (volar) mapa.flyTo({ center: [e.lon, e.lat], zoom: Math.max(mapa.getZoom(), 4), speed: 1.4 });
  pintar();
  if (!volar) document.querySelector(`.item[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ---------- Datos ----------
async function cargar() {
  try {
    const r = await fetch(`${DATOS_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    estado.eventos = d.eventos || [];
    estado.actualizado = d.actualizado;
  } catch (err) {
    console.error("No se pudieron cargar los eventos:", err);
  }
  pintar();
}

// ---------- Controles ----------
function iniciarControles() {
  const chips = $("chips");
  for (const [k, t] of Object.entries(TIPOS)) {
    const b = el("button", { className: "chip" },
      el("i", { style: `background:${t.color}` }), t.label, el("span", { className: "n", textContent: "0" }));
    b.dataset.tipo = k;
    b.setAttribute("aria-pressed", "true");
    b.onclick = () => {
      const on = estado.tipos.has(k);
      on ? estado.tipos.delete(k) : estado.tipos.add(k);
      b.setAttribute("aria-pressed", String(!on));
      pintar();
    };
    chips.append(b);
  }
  $("q").addEventListener("input", (e) => { estado.q = e.target.value; pintar(); });
  $("win").addEventListener("input", (e) => {
    estado.horas = +e.target.value;
    $("win-label").textContent = `${estado.horas} h`;
    pintar();
  });
}

(async function () {
  iniciarControles();
  await iniciarMapa();
  await cargar();
  setInterval(cargar, REFRESCO_MS);
  setInterval(pintar, 60 * 1000); // refresca los "hace X min"
})();
