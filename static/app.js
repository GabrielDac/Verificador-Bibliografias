// Verificador de Bibliografías — © 2026 Gabriel Da Costa Porto Luzardo — GPL-3.0
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

let referencias = [];     // [{raw, estructurada, doi, url, anio, autor, titulo}]
let resultados = [];      // [{ref, res}]  res = null mientras está en cola
let filtro = "";
let detener = false;
let enCurso = false;

const EJEMPLO = `LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436–444. https://doi.org/10.1038/nature14539

Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. Advances in Neural Information Processing Systems, 30, 5998–6008.

García-Peñalvo, F. J. (2023). La percepción de la Inteligencia Artificial en contextos educativos tras el lanzamiento de ChatGPT: disrupción o pánico. Education in the Knowledge Society, 24, e31279. https://doi.org/10.14201/eks.31279

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

// ─────────────────────── 1 · Cargar ───────────────────────

async function extraer(opciones) {
  estado("estado-carga", "Analizando…", "ocupado");
  $("btn-detectar").disabled = true;
  try {
    const r = await fetch("/api/extraer", opciones);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || "No se pudo analizar el contenido.");
    referencias = d.referencias.map((x) => ({ ...x, estructurada: d.origen === "bibtex" || d.origen === "ris" }));
    const aviso = $("aviso-extraccion");
    aviso.hidden = !d.aviso;
    aviso.textContent = d.aviso || "";
    estado("estado-carga", `Se detectaron ${referencias.length} referencias.`, "ok");
    $("panel-resultados").hidden = true;
    $("panel-revisar").hidden = false;
    pintarRevision();
    $("panel-revisar").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    estado("estado-carga", e.message.includes("fetch") ? "No hubo respuesta del servidor. Probá de nuevo." : e.message, "error");
  } finally {
    $("btn-detectar").disabled = false;
  }
}

function subirArchivo(archivo) {
  if (!archivo) return;
  if (archivo.size > 25 * 1024 * 1024) return estado("estado-carga", "El archivo supera los 25 MB.", "error");
  const fd = new FormData();
  fd.append("archivo", archivo);
  estado("estado-carga", `Leyendo «${archivo.name}»…`, "ocupado");
  extraer({ method: "POST", body: fd });
}

function detectarTexto() {
  const texto = $("texto").value;
  if (!texto.trim()) return estado("estado-carga", "Pegá primero las referencias o soltá un archivo.", "error");
  extraer({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto }) });
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
    t.setAttribute("aria-label", `Referencia ${i + 1}`);
    t.addEventListener("input", () => {
      referencias[i] = { raw: t.value, estructurada: false };   // editada: se vuelve a analizar
      ajustarAlto(t);
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
  const n = referencias.length;
  $("cuenta-revisar").textContent = n === 1 ? "1 referencia" : `${n} referencias`;
  $("btn-verificar").textContent = n === 1 ? "Verificar 1 referencia" : `Verificar ${n} referencias`;
  $("btn-verificar").disabled = n === 0;
}

// ─────────────────────── 3 · Verificar ───────────────────────

async function verificarUna(i) {
  const item = resultados[i];
  try {
    const r = await fetch("/api/verificar", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(item.ref),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || "Sin respuesta");
    item.res = d;
  } catch (e) {
    item.res = {
      estado: "sin_comprobar", resumen: "No se pudo completar la verificación. Se puede reintentar.",
      notas: [], enlace: null, registro: null, fuentes: [], buscar: null,
    };
  }
  pintarTarjeta(i);
  pintarResumen();
}

async function verificarTodas() {
  referencias = referencias.filter((r) => (r.raw || "").trim().length >= 15);
  if (!referencias.length || enCurso) return;
  resultados = referencias.map((ref) => ({ ref, res: null }));
  filtro = "";
  detener = false;
  enCurso = true;
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
      await verificarUna(i);
    }
  };
  await Promise.all(Array.from({ length: SIMULTANEAS }, obrero));
  enCurso = false;
  $("btn-detener").hidden = true;
  $("btn-verificar").disabled = false;
  pintarResumen();
}

function pintarTarjeta(i) {
  const { ref, res } = resultados[i];
  const li = $("tarjeta-" + i);
  const e = res ? res.estado : "pendiente";
  li.className = "tarjeta " + e;
  li.dataset.estado = e;
  li.hidden = Boolean(filtro) && filtro !== e;
  let h = `<div class="tarjeta-cabeza"><span class="tarjeta-num">${i + 1}</span>
    <span class="sello sello-${e}">${ESTADOS[e]}</span>
    <span class="tarjeta-resumen">${res ? esc(res.resumen) : (enCurso ? "Verificando…" : "")}</span></div>
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
      const marca = { encontrada: "✓ ", parecida: "≈ ", sin_respuesta: "? " }[f.estado] || "";
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
  $("progreso-texto").textContent = hechas < total
    ? (enCurso ? `Verificando ${hechas} de ${total}…` : `Detenido en ${hechas} de ${total}.`)
    : `${total} referencias verificadas.`;
  const cuenta = {};
  resultados.forEach((r) => { if (r.res) cuenta[r.res.estado] = (cuenta[r.res.estado] || 0) + 1; });
  let h = `<button type="button" class="chip" data-filtro="" aria-pressed="${filtro === ""}">Todas <b>${total}</b></button>`;
  for (const e of ORDEN_FILTROS) {
    if (!cuenta[e]) continue;
    h += `<button type="button" class="chip" data-filtro="${e}" aria-pressed="${filtro === e}">${ESTADOS[e]} <b>${cuenta[e]}</b></button>`;
  }
  $("filtros").innerHTML = h;
}

function aplicarFiltro(f) {
  filtro = f;
  resultados.forEach((r, i) => {
    $("tarjeta-" + i).hidden = Boolean(f) && (r.res ? r.res.estado : "pendiente") !== f;
  });
  pintarResumen();
}

// ─────────────────────── Exportar ───────────────────────

function filasInforme() {
  return resultados.filter((r) => r.res).map((r, i) => {
    const s = r.res, g = s.registro || {}, en = s.enlace || {};
    return {
      n: resultados.indexOf(r) + 1, estado: ESTADOS[s.estado], resumen: s.resumen, cita: r.ref.raw,
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
  const fecha = new Date().toLocaleDateString("es-UY", { year: "numeric", month: "long", day: "numeric" });
  if (fmt === "csv") {
    const cols = ["n", "estado", "resumen", "cita", "enlace", "notas", "titulo", "autores", "anio", "fuente", "url", "bases"];
    const rot = ["N.º", "Estado", "Resumen", "Referencia citada", "Enlace citado", "Observaciones", "Título registrado",
      "Autores registrados", "Año registrado", "Fuente del registro", "Enlace del registro", "Bases donde se encontró"];
    const celda = (v) => '"' + String(v).replace(/"/g, '""') + '"';
    const csv = [rot.map(celda).join(",")].concat(filas.map((f) => cols.map((c) => celda(f[c])).join(","))).join("\r\n");
    return descargar("verificacion-bibliografia.csv", "﻿" + csv, "text/csv;charset=utf-8");
  }
  if (fmt === "txt") {
    const txt = filas.map((f) => `${f.n}. [${f.estado.toUpperCase()}] ${f.cita}\n   ${f.resumen}` +
      (f.enlace ? `\n   ${f.enlace}` : "") + (f.notas ? `\n   ${f.notas}` : "") +
      (f.titulo ? `\n   Registro (${f.fuente}): ${f.titulo}. ${[f.autores, f.anio].filter(Boolean).join(", ")} ${f.url}` : "")).join("\n\n");
    return descargar("verificacion-bibliografia.txt", `Verificación de bibliografía — ${fecha}\n\n${txt}\n`, "text/plain;charset=utf-8");
  }
  const cuenta = {};
  filas.forEach((f) => { cuenta[f.estado] = (cuenta[f.estado] || 0) + 1; });
  const colores = { "Verificada": "#1E6B3C", "Con observaciones": "#7A5300", "No encontrada": "#9E2B25", "Retractada": "#9E2B25", "Sin comprobar": "#4D565C" };
  const cuerpo = filas.map((f) => `<li><p><b style="color:${colores[f.estado]}">${esc(f.estado)}.</b> ${esc(f.resumen)}</p>
    <p class="cita">${esc(f.cita)}</p>${f.enlace ? `<p>${esc(f.enlace)}</p>` : ""}${f.notas ? `<p>${esc(f.notas)}</p>` : ""}
    ${f.titulo ? `<p class="reg">Registro en ${esc(f.fuente)}: <b>${esc(f.titulo)}</b>. ${esc([f.autores, f.anio].filter(Boolean).join(", "))} ${enlace(f.url)}</p>` : ""}</li>`).join("\n");
  const doc = `<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Verificación de bibliografía</title>
<style>body{font-family:Georgia,serif;max-width:820px;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#20262A}
h1{font-size:1.5rem}li{margin-bottom:1.1rem;padding-bottom:.8rem;border-bottom:1px solid #D7DAD2}p{margin:.2rem 0}
.cita{font-size:1.02rem}.reg{font-size:.92rem;color:#4D565C}.pie{font-size:.85rem;color:#4D565C}a{color:#0D5E66;overflow-wrap:anywhere}</style></head>
<body><h1>Verificación de bibliografía</h1>
<p>${esc(fecha)} · ${filas.length} referencias · ${Object.entries(cuenta).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ")}</p>
<ol>${cuerpo}</ol>
<p class="pie">Informe generado con Verificador de Bibliografías. El resultado es una ayuda para la revisión y no un dictamen definitivo.</p></body></html>`;
  descargar("verificacion-bibliografia.html", doc, "text/html;charset=utf-8");
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

  const zona = $("zona");
  ["dragenter", "dragover"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("encima"); }));
  ["dragleave", "drop"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove("encima"); }));
  zona.addEventListener("drop", (e) => subirArchivo(e.dataTransfer.files[0]));
  zona.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("archivo").click(); } });
  // Soltar fuera de la zona no debe abrir el archivo en el navegador
  ["dragover", "drop"].forEach((ev) => window.addEventListener(ev, (e) => e.preventDefault()));
  $("archivo").addEventListener("change", (e) => { subirArchivo(e.target.files[0]); e.target.value = ""; });

  $("btn-detectar").addEventListener("click", detectarTexto);
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
  $("btn-detener").addEventListener("click", () => { detener = true; $("btn-detener").hidden = true; });
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
    pintarTarjeta(i);
    $("tarjeta-" + i).querySelector(".tarjeta-resumen").textContent = "Verificando…";
    verificarUna(i);
  });
  let espera;
  window.addEventListener("resize", () => {
    clearTimeout(espera);
    espera = setTimeout(() => $("lista-revisar").querySelectorAll("textarea").forEach(ajustarAlto), 150);
  });
  $("btn-fuentes").addEventListener("click", async () => {
    const el = $("estado-fuentes");
    el.textContent = "Consultando…";
    try {
      const d = await (await fetch("/api/fuentes")).json();
      el.textContent = Object.entries(d).map(([k, v]) => `${k}: ${v}`).join(" · ");
    } catch (e) {
      el.textContent = "No se pudo consultar.";
    }
  });
});
