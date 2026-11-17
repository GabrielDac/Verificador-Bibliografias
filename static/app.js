// Verificador Bibliográfico — © 2026 Gabriel Da Costa Porto Luzardo — GPL-3.0
"use strict";

const $ = (id) => document.getElementById(id);

const ESTADOS = {
  verificada: "Verificada",
  observaciones: "Con observaciones",
  no_encontrada: "No encontrada",
  retractada: "Retractada",
  sin_comprobar: "Sin comprobar",
  pendiente: "En cola",
};
const ORDEN_FILTROS = ["verificada", "observaciones", "no_encontrada", "retractada", "sin_comprobar"];
const SIMULTANEAS = 3;
const REINTENTOS = [2500, 6000];          // esperas antes del 2.º y 3.er intento (ms)
const PING_CADA = 10 * 60 * 1000;         // mantener despierto el servidor
const INACTIVIDAD = 30 * 60 * 1000;       // dejar de hacerlo tras media hora sin uso

let referencias = [];     // [{raw, estructurada, doi, url, url_alt, anio, autor, titulo}]
let resultados = [];      // [{ref, res, ms}]
let filtro = "";
let detener = false;
let enCurso = false;
let inicioVerificacion = 0;
let ultimaActividad = Date.now();
let ultimoPing = 0;

const EJEMPLO = `LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436–444. https://doi.org/10.1038/nature14539

Butler, L.-A., Matthias, L., Simard, M.-A., Mongeon, P., & Haustein, S. (2023). The oligopoly's shift to open access: How the big five academic publishers profit from article processing charges. Quantitative Science Studies, 4(4), 778–799.

Carvidón, E., Paz Torres, M. y Rodríguez-Fleitas, M. (2021). Red de Bibliotecas Parlamentarias de América Latina y el Caribe. Informatio, 26(2). https://informatio.fic.edu.uy/index.php/informatio/article/view/366/391

Pérez, J. M., y Rodríguez, L. (2021). Bibliotecas cuánticas rioplatenses: un modelo imaginario de catalogación. Revista Inventada de Bibliotecología, 12(3), 45–67. https://doi.org/10.9999/rib.2021.123

Ranganathan, S. R. (1931). The five laws of library science. Madras Library Association.`;

// ─────────────────────── Utilidades ───────────────────────

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function enlace(url, texto) {
  if (!/^https?:\/\//i.test(url || "")) return esc(texto || url);
  return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(texto || url)}</a>`;
}

function estado(id, texto, clase) {
  const el = $(id);
  el.textContent = texto || "";
  el.className = "estado" + (clase ? " " + clase : "");
}

function descargar(nombre, contenido, tipo) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([contenido], { type: tipo }));
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

function ajustarAlto(t) {
  t.style.height = "auto";
  t.style.height = t.scrollHeight + 2 + "px";
}

function duracion(ms) {
  const s = Math.max(1, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60), r = s % 60;
  return r ? `${m} min ${r} s` : `${m} min`;
}

const espera = (ms) => new Promise((r) => setTimeout(r, ms));

/** fetch con reintentos ante fallas del servidor o de la red (no ante errores 4xx). */
async function pedir(url, opciones, alReintentar) {
  let ultimoError;
  for (let intento = 0; intento <= REINTENTOS.length; intento++) {
    if (intento > 0) {
      if (alReintentar) alReintentar(intento);
      await espera(REINTENTOS[intento - 1]);
    }
    try {
      const r = await fetch(url, opciones);
      ultimoPing = Date.now();
      const d = await r.json().catch(() => ({}));
      if (r.ok) return d;
      if (r.status < 500 && r.status !== 429) throw Object.assign(new Error(d.error || "Solicitud rechazada"), { final: true });
      ultimoError = new Error(d.error || `El servidor respondió ${r.status}`);
    } catch (e) {
      if (e.final) throw e;
      ultimoError = e;
    }
  }
  throw ultimoError;
}

// ─────────────────────── Estado de las bases ───────────────────────

const ROTULO_FUENTE = { ok: "en línea", vacia: "responde sin resultados", sin_respuesta: "sin respuesta", comprobando: "comprobando" };

function pintarFuente(nombre, est, ms) {
  const li = document.querySelector(`#lista-fuentes [data-fuente="${CSS.escape(nombre)}"]`);
  if (!li) return;
  li.className = "fuente " + est;
  li.title = ROTULO_FUENTE[est] + (ms ? ` · ${ms} ms` : "");
  li.querySelector(".visualmente-oculto").textContent = " " + ROTULO_FUENTE[est];
}

async function comprobarFuentes() {
  const btn = $("btn-fuentes");
  btn.disabled = true;
  document.querySelectorAll("#lista-fuentes .fuente").forEach((li) => pintarFuente(li.dataset.fuente, "comprobando"));
  const el = $("estado-servidor");
  el.textContent = "Conectando con el servidor…";
  const t0 = Date.now();
  const aviso = setTimeout(() => {
    el.textContent = "El servidor estaba en reposo y se está despertando. Puede tardar hasta un minuto…";
  }, 4000);
  try {
    await pedir("/api/ping");
    clearTimeout(aviso);
    el.textContent = "Servidor listo. Consultando cada base con un registro conocido…";
    const d = await pedir("/api/fuentes");
    const lista = d.fuentes || [];
    lista.forEach((f) => pintarFuente(f.nombre, f.estado, f.ms));
    const caidas = lista.filter((f) => f.estado === "sin_respuesta").map((f) => f.nombre);
    el.textContent = caidas.length
      ? `Sin respuesta: ${caidas.join(", ")}. La verificación usa las demás bases.`
      : `Todas las bases responden (comprobado en ${duracion(Date.now() - t0)}).`;
  } catch (e) {
    clearTimeout(aviso);
    el.textContent = "No se pudo conectar con el servidor. Probá «Comprobar de nuevo» en un momento.";
    document.querySelectorAll("#lista-fuentes .fuente").forEach((li) => pintarFuente(li.dataset.fuente, "sin_respuesta"));
  } finally {
    btn.disabled = false;
  }
}

// Mantiene despierto el servidor mientras alguien usa la página
function registrarActividad() { ultimaActividad = Date.now(); }
setInterval(() => {
  const activo = enCurso || Date.now() - ultimaActividad < INACTIVIDAD;
  if (activo && Date.now() - ultimoPing > PING_CADA) {
    ultimoPing = Date.now();
    fetch("/api/ping").catch(() => {});
  }
}, 60 * 1000);

// ─────────────────────── 1 · Cargar ───────────────────────

async function extraer(opciones, rotulo) {
  $("btn-detectar").disabled = true;
  const t0 = Date.now();
  const reloj = setInterval(() => {
    estado("estado-carga", `${rotulo}… ${duracion(Date.now() - t0)}`, "ocupado");
  }, 1000);
  estado("estado-carga", `${rotulo}…`, "ocupado");
  try {
    const d = await pedir("/api/extraer", opciones, () => {
      estado("estado-carga", `${rotulo}… el servidor tarda en responder, reintentando`, "ocupado");
    });
    referencias = d.referencias.map((x) => ({ ...x, estructurada: d.origen === "bibtex" || d.origen === "ris" }));
    const aviso = $("aviso-extraccion");
    aviso.hidden = !d.aviso;
    aviso.textContent = d.aviso || "";
    const extra = d.paginas ? ` (páginas leídas: ${d.paginas})` : "";
    estado("estado-carga", `Se detectaron ${referencias.length} referencias en ${duracion(Date.now() - t0)}${extra}.`, "ok");
    mostrarRevision();
  } catch (e) {
    estado("estado-carga", /fetch|network|Load failed/i.test(e.message)
      ? "No hubo respuesta del servidor. Probá de nuevo en un momento." : e.message, "error");
  } finally {
    clearInterval(reloj);
    $("btn-detectar").disabled = false;
  }
}

function subirArchivo(archivo) {
  if (!archivo) return;
  if (archivo.size > 25 * 1024 * 1024) return estado("estado-carga", "El archivo supera los 25 MB.", "error");
  const fd = new FormData();
  fd.append("archivo", archivo);
  const pdf = /\.pdf$/i.test(archivo.name) || archivo.type === "application/pdf";
  extraer({ method: "POST", body: fd }, pdf ? `Leyendo «${archivo.name}»` : `Analizando «${archivo.name}»`);
}

function detectarTexto() {
  const texto = $("texto").value;
  if (!texto.trim()) return estado("estado-carga", "Pegá primero las referencias o soltá un archivo.", "error");
  extraer({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto }) },
    "Separando las referencias");
}

function mostrarRevision(enfocarUltima) {
  $("panel-resultados").hidden = true;
  $("panel-revisar").hidden = false;
  pintarRevision();
  if (enfocarUltima) {
    const cajas = $("lista-revisar").querySelectorAll("textarea");
    if (cajas.length) cajas[cajas.length - 1].focus();
  } else {
    $("panel-revisar").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// ─────────────────────── 2 · Revisar ───────────────────────

function pintarRevision() {
  const ol = $("lista-revisar");
  ol.innerHTML = "";
  referencias.forEach((ref, i) => {
    const li = document.createElement("li");
    const t = document.createElement("textarea");
    t.value = ref.raw;
    t.rows = 1;
    t.spellcheck = false;
    t.placeholder = "Escribí o pegá una referencia";
    t.setAttribute("aria-label", `Referencia ${i + 1}`);
    t.addEventListener("input", () => {
      referencias[i] = { raw: t.value, estructurada: false };   // editada: se vuelve a analizar
      ajustarAlto(t);
      contarRevision();
    });
    const h = document.createElement("div");
    h.className = "herramientas";
    if (i > 0) {
      const u = document.createElement("button");
      u.type = "button";
      u.textContent = "↑ Unir";
      u.title = "Unir con la referencia anterior";
      u.addEventListener("click", () => {
        referencias[i - 1] = { raw: (referencias[i - 1].raw + " " + referencias[i].raw).trim(), estructurada: false };
        referencias.splice(i, 1);
        pintarRevision();
      });
      h.appendChild(u);
    }
    const q = document.createElement("button");
    q.type = "button";
    q.textContent = "✕ Quitar";
    q.title = "Quitar esta referencia";
    q.addEventListener("click", () => { referencias.splice(i, 1); pintarRevision(); });
    h.appendChild(q);
    li.append(t, h);
    ol.appendChild(li);
    ajustarAlto(t);
  });
  contarRevision();
}

function contarRevision() {
  const n = referencias.filter((r) => (r.raw || "").trim().length >= 15).length;
  $("cuenta-revisar").textContent = n === 1 ? "1 referencia" : `${n} referencias`;
  $("btn-verificar").textContent = n === 1 ? "Verificar 1 referencia" : `Verificar ${n} referencias`;
  $("btn-verificar").disabled = n === 0 || enCurso;
}

// ─────────────────────── 3 · Verificar ───────────────────────

async function verificarUna(i) {
  const item = resultados[i];
  const t0 = Date.now();
  item.reintento = 0;
  try {
    item.res = await pedir("/api/verificar", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(item.ref),
    }, (n) => {
      item.reintento = n;
      pintarTarjeta(i);
    });
  } catch (e) {
    item.res = {
      estado: "sin_comprobar",
      resumen: "El servidor no respondió, ni siquiera después de reintentar. Podés volver a intentarlo.",
      notas: [], enlace: null, registro: null, fuentes: [], buscar: null,
    };
  }
  item.ms = Date.now() - t0;
  pintarTarjeta(i);
  pintarResumen();
}

async function verificarTodas() {
  referencias = referencias.filter((r) => (r.raw || "").trim().length >= 15);
  if (!referencias.length || enCurso) return;
  resultados = referencias.map((ref) => ({ ref, res: null, ms: 0 }));
  filtro = "";
  detener = false;
  enCurso = true;
  inicioVerificacion = Date.now();
  $("panel-resultados").hidden = false;
  $("btn-detener").hidden = false;
  $("btn-verificar").disabled = true;
  $("lista-resultados").innerHTML = "";
  resultados.forEach((_, i) => {
    const li = document.createElement("li");
    li.id = "tarjeta-" + i;
    $("lista-resultados").appendChild(li);
    pintarTarjeta(i);
  });
  pintarResumen();
  $("panel-resultados").scrollIntoView({ behavior: "smooth", block: "start" });

  let siguiente = 0;
  const obrero = async () => {
    while (!detener && siguiente < resultados.length) {
      const i = siguiente++;
      resultados[i].enCurso = true;
      pintarTarjeta(i);
      await verificarUna(i);
      resultados[i].enCurso = false;
    }
  };
  await Promise.all(Array.from({ length: SIMULTANEAS }, obrero));
  enCurso = false;
  $("btn-detener").hidden = true;
  contarRevision();
  pintarResumen();
}

function pintarTarjeta(i) {
  const item = resultados[i];
  const { ref, res } = item;
  const li = $("tarjeta-" + i);
  const e = res ? res.estado : "pendiente";
  li.className = "tarjeta " + e;
  li.hidden = Boolean(filtro) && filtro !== e;
  let enProceso = "";
  if (!res && item.enCurso) enProceso = item.reintento ? `El servidor tarda, reintento ${item.reintento} de ${REINTENTOS.length}…` : "Verificando…";
  let h = `<div class="tarjeta-cabeza"><span class="tarjeta-num">${i + 1}</span>
    <span class="sello sello-${e}">${ESTADOS[e]}</span>
    <span class="tarjeta-resumen">${res ? esc(res.resumen) : enProceso}</span></div>
    <p class="tarjeta-cita">${esc(ref.raw)}</p>`;
  if (res) {
    const en = res.enlace;
    for (const x of [en, en && en.segundo]) {
      if (!x) continue;
      h += `<p class="tarjeta-linea"><span class="rotulo">${x.tipo === "doi" ? "DOI citado" : "Enlace citado"}:</span> ${enlace(x.url, x.valor)} — ${esc(x.detalle || "")}`;
      if (x.archivo) h += ` ${enlace(x.archivo, "Ver la copia archivada")}`;
      h += "</p>";
    }
    if (res.notas && res.notas.length) h += "<ul>" + res.notas.map((n) => `<li>${esc(n)}</li>`).join("") + "</ul>";
    const g = res.registro;
    if (g) {
      const datos = [g.autores, g.anio, g.revista].filter(Boolean).map(esc).join(" · ");
      h += `<div class="registro"><span class="rotulo">Registro encontrado en ${esc(g.fuente)}</span>
        <strong>${esc(g.titulo)}</strong>${datos ? "<br>" + datos : ""}${g.url ? "<br>" + enlace(g.url, g.doi ? "https://doi.org/" + g.doi : g.url) : ""}</div>`;
    }
    h += '<div class="tarjeta-pie">';
    for (const f of res.fuentes || []) {
      const marca = { encontrada: "✓ ", parecida: "≈ " }[f.estado] || "";
      const pista = { encontrada: "Encontrada", parecida: "Registro parecido", no: "Consultada, sin resultado",
        sin_respuesta: "No respondió", no_consultada: "No hizo falta consultarla" }[f.estado] || "";
      h += `<span class="base ${esc(f.estado)}" title="${pista}">${marca}${esc(f.nombre)}</span>`;
    }
    h += '<span class="empuje">';
    if (res.buscar) h += enlace(res.buscar.scholar, "Google Académico") + enlace(res.buscar.google, "Google");
    if (e === "sin_comprobar") h += `<button type="button" data-reintentar="${i}">Reintentar</button>`;
    h += "</span></div>";
  }
  li.innerHTML = h;
}

function pintarResumen() {
  const total = resultados.length;
  const hechas = resultados.filter((r) => r.res).length;
  $("barra-avance").style.width = (total ? (100 * hechas) / total : 0) + "%";
  const transcurrido = Date.now() - inicioVerificacion;
  if (hechas < total && enCurso) {
    $("progreso-texto").textContent = `Verificando ${hechas} de ${total}`;
    if (hechas >= 1) {
      // Tiempo medio por referencia, dividido por las consultas simultáneas
      const ritmo = transcurrido / hechas;
      $("progreso-tiempo").textContent = `Van ${duracion(transcurrido)} · faltan aprox. ${duracion(ritmo * (total - hechas))}`;
    } else {
      $("progreso-tiempo").textContent = "Calculando el tiempo restante…";
    }
  } else if (hechas < total) {
    $("progreso-texto").textContent = `Detenido en ${hechas} de ${total}`;
    $("progreso-tiempo").textContent = "Podés exportar lo verificado hasta ahora.";
  } else {
    $("progreso-texto").textContent = `${total} ${total === 1 ? "referencia verificada" : "referencias verificadas"}`;
    $("progreso-tiempo").textContent = total ? `Tiempo total: ${duracion(transcurrido)}` : "";
  }
  const cuenta = {};
  resultados.forEach((r) => { if (r.res) cuenta[r.res.estado] = (cuenta[r.res.estado] || 0) + 1; });
  let h = `<button type="button" class="chip" data-filtro="" aria-pressed="${filtro === ""}">Todas <b>${total}</b></button>`;
  for (const e of ORDEN_FILTROS) {
    if (!cuenta[e]) continue;
    h += `<button type="button" class="chip chip-${e}" data-filtro="${e}" aria-pressed="${filtro === e}">${ESTADOS[e]} <b>${cuenta[e]}</b></button>`;
  }
  $("filtros").innerHTML = h;
  $("btn-exportar").disabled = hechas === 0;
}

function aplicarFiltro(f) {
  filtro = f;
  resultados.forEach((r, i) => {
    $("tarjeta-" + i).hidden = Boolean(f) && (r.res ? r.res.estado : "pendiente") !== f;
  });
  pintarResumen();
}

// Actualiza el tiempo transcurrido aunque no termine ninguna referencia
setInterval(() => { if (enCurso) pintarResumen(); }, 1000);

// ─────────────────────── Exportar ───────────────────────

function filasInforme() {
  return resultados.map((r, i) => ({ r, i })).filter(({ r }) => r.res).map(({ r, i }) => {
    const s = r.res, g = s.registro || {}, en = s.enlace || {};
    return {
      n: i + 1, estado: ESTADOS[s.estado], resumen: s.resumen, cita: r.ref.raw,
      enlace: [en.detalle, en.segundo && en.segundo.detalle].filter(Boolean).join(" "),
      notas: (s.notas || []).join(" "),
      titulo: g.titulo || "", autores: g.autores || "", anio: g.anio || "", fuente: g.fuente || "",
      url: g.url || "",
      bases: (s.fuentes || []).filter((f) => f.estado === "encontrada").map((f) => f.nombre).join(", "),
    };
  });
}

function exportar() {
  const filas = filasInforme();
  if (!filas.length) return;
  const fmt = $("fmt-exportar").value;
  const parcial = filas.length < resultados.length ? `-parcial-${filas.length}-de-${resultados.length}` : "";
  const nombre = "verificacion-bibliografica" + parcial;
  const fecha = new Date().toLocaleDateString("es-UY", { year: "numeric", month: "long", day: "numeric" });
  if (fmt === "csv") {
    const cols = ["n", "estado", "resumen", "cita", "enlace", "notas", "titulo", "autores", "anio", "fuente", "url", "bases"];
    const rot = ["N.º", "Estado", "Resumen", "Referencia citada", "Enlace citado", "Observaciones", "Título registrado",
      "Autores registrados", "Año registrado", "Fuente del registro", "Enlace del registro", "Bases donde se encontró"];
    const celda = (v) => '"' + String(v).replace(/"/g, '""') + '"';
    const csv = [rot.map(celda).join(",")].concat(filas.map((f) => cols.map((c) => celda(f[c])).join(","))).join("\r\n");
    return descargar(nombre + ".csv", "﻿" + csv, "text/csv;charset=utf-8");
  }
  if (fmt === "txt") {
    const txt = filas.map((f) => `${f.n}. [${f.estado.toUpperCase()}] ${f.cita}\n   ${f.resumen}` +
      (f.enlace ? `\n   ${f.enlace}` : "") + (f.notas ? `\n   ${f.notas}` : "") +
      (f.titulo ? `\n   Registro (${f.fuente}): ${f.titulo}. ${[f.autores, f.anio].filter(Boolean).join(", ")} ${f.url}` : "")).join("\n\n");
    return descargar(nombre + ".txt", `Verificación bibliográfica — ${fecha}\n\n${txt}\n`, "text/plain;charset=utf-8");
  }
  const cuenta = {};
  filas.forEach((f) => { cuenta[f.estado] = (cuenta[f.estado] || 0) + 1; });
  const colores = { "Verificada": "#1E6B3C", "Con observaciones": "#7A5300", "No encontrada": "#9E2B25", "Retractada": "#9E2B25", "Sin comprobar": "#4D565C" };
  const cuerpo = filas.map((f) => `<li value="${f.n}"><p><b style="color:${colores[f.estado]}">${esc(f.estado)}.</b> ${esc(f.resumen)}</p>
    <p class="cita">${esc(f.cita)}</p>${f.enlace ? `<p>${esc(f.enlace)}</p>` : ""}${f.notas ? `<p>${esc(f.notas)}</p>` : ""}
    ${f.titulo ? `<p class="reg">Registro en ${esc(f.fuente)}: <b>${esc(f.titulo)}</b>. ${esc([f.autores, f.anio].filter(Boolean).join(", "))} ${enlace(f.url)}</p>` : ""}</li>`).join("\n");
  const doc = `<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Verificación bibliográfica</title>
<style>body{font-family:Georgia,serif;max-width:820px;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#20262A}
h1{font-size:1.5rem}li{margin-bottom:1.1rem;padding-bottom:.8rem;border-bottom:1px solid #D7DAD2}p{margin:.2rem 0}
.cita{font-size:1.02rem}.reg{font-size:.92rem;color:#4D565C}.pie{font-size:.85rem;color:#4D565C}a{color:#0D5E66;overflow-wrap:anywhere}</style></head>
<body><h1>Verificación bibliográfica</h1>
<p>${esc(fecha)} · ${filas.length}${parcial ? ` de ${resultados.length}` : ""} referencias · ${Object.entries(cuenta).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ")}</p>
<ol>${cuerpo}</ol>
<p class="pie">Informe generado con Verificador Bibliográfico. El resultado es una ayuda para la revisión y no un dictamen definitivo.</p></body></html>`;
  descargar(nombre + ".html", doc, "text/html;charset=utf-8");
}

// ─────────────────────── Tema ───────────────────────

function aplicarTema(t) {
  if (t === "auto") t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = t;
}

function temaGuardado() {
  try { return localStorage.getItem("tema") || "auto"; } catch (e) { return "auto"; }
}

// ─────────────────────── Inicio ───────────────────────

document.addEventListener("DOMContentLoaded", () => {
  aplicarTema(temaGuardado());
  $("btn-tema").addEventListener("click", () => {
    const nuevo = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("tema", nuevo); } catch (e) { /* sin almacenamiento */ }
    aplicarTema(nuevo);
  });

  ["pointerdown", "keydown", "scroll", "pointermove"].forEach((ev) =>
    window.addEventListener(ev, registrarActividad, { passive: true }));

  comprobarFuentes();      // de paso despierta el servidor
  $("btn-fuentes").addEventListener("click", comprobarFuentes);

  const zona = $("zona");
  ["dragenter", "dragover"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("encima"); }));
  ["dragleave", "drop"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove("encima"); }));
  zona.addEventListener("drop", (e) => subirArchivo(e.dataTransfer.files[0]));
  zona.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("archivo").click(); } });
  ["dragover", "drop"].forEach((ev) => window.addEventListener(ev, (e) => e.preventDefault()));
  $("archivo").addEventListener("change", (e) => { subirArchivo(e.target.files[0]); e.target.value = ""; });

  $("btn-detectar").addEventListener("click", detectarTexto);
  $("btn-borrar").addEventListener("click", () => {
    $("texto").value = "";
    estado("estado-carga", "");
    $("texto").focus();
  });
  $("btn-una").addEventListener("click", () => {
    if (!referencias.length || referencias[referencias.length - 1].raw.trim()) referencias.push({ raw: "", estructurada: false });
    mostrarRevision(true);
  });
  $("btn-ejemplo").addEventListener("click", () => { $("texto").value = EJEMPLO; detectarTexto(); });
  $("btn-verificar").addEventListener("click", verificarTodas);
  $("btn-agregar").addEventListener("click", () => {
    referencias.push({ raw: "", estructurada: false });
    pintarRevision();
    const cajas = $("lista-revisar").querySelectorAll("textarea");
    cajas[cajas.length - 1].focus();
  });
  $("btn-vaciar").addEventListener("click", () => {
    referencias = [];
    pintarRevision();
    $("panel-revisar").hidden = true;
    $("panel-resultados").hidden = true;
    estado("estado-carga", "");
  });
  $("btn-detener").addEventListener("click", () => { detener = true; $("btn-detener").hidden = true; pintarResumen(); });
  $("btn-exportar").addEventListener("click", exportar);
  $("filtros").addEventListener("click", (e) => {
    const b = e.target.closest("[data-filtro]");
    if (b) aplicarFiltro(b.dataset.filtro);
  });
  $("lista-resultados").addEventListener("click", (e) => {
    const b = e.target.closest("[data-reintentar]");
    if (!b) return;
    const i = Number(b.dataset.reintentar);
    resultados[i].res = null;
    resultados[i].enCurso = true;
    pintarTarjeta(i);
    verificarUna(i).then(() => { resultados[i].enCurso = false; });
  });
  let pausa;
  window.addEventListener("resize", () => {
    clearTimeout(pausa);
    pausa = setTimeout(() => $("lista-revisar").querySelectorAll("textarea").forEach(ajustarAlto), 150);
  });
});
