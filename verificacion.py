# Verificador Bibliográfico — © 2026 Gabriel Da Costa Porto Luzardo — GPL-3.0
"""Verificación de una referencia.

Orden de trabajo:
  1. Se comprueba el enlace citado (DOI o dirección web).
  2. Si el enlace no alcanza para confirmar la referencia, se busca el
     trabajo por título y autor en varias bases de datos abiertas.
"""

import html
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

from extraccion import normalizar, limpiar_doi, RE_URL

# Variables de entorno opcionales (se definen en Render):
#   CONTACT_EMAIL   → identifica la herramienta ante Crossref, OpenAlex y NCBI («polite pool»)
#   NCBI_API_KEY    → sube el límite de consultas de PubMed
#   S2_API_KEY      → clave de Semantic Scholar (sin clave comparte un cupo público muy limitado)
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "").strip()
S2_API_KEY = os.environ.get("S2_API_KEY", "").strip()

UA = "VerificadorBibliografico/2.0 (herramienta educativa de software libre" + \
     (f"; mailto:{CONTACT_EMAIL}" if CONTACT_EMAIL else "") + ")"
UA_NAVEGADOR = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36 VerificadorBibliografico/2.0")

T_API = 9          # segundos por consulta a una base
T_PAGINA = 10      # segundos para abrir la página citada
MAX_PAGINA = 400_000

# Semantic Scholar solo se consulta con clave: sin ella comparte un cupo
# público que casi nunca responde desde un servidor compartido.
FUENTES = ["Crossref", "OpenAlex", "PubMed", "DOAJ", "OpenAIRE", "Open Library"] + \
          (["Semantic Scholar"] if S2_API_KEY else [])

# Ponencias, tesis, informes y otros documentos que las bases cubren poco
RE_LITERATURA_GRIS = re.compile(
    r"\b(presentad[oa] en|ponencia|jornadas?|congreso|simposio|encuentro|seminario|coloquio|"
    r"actas|memorias? del|tesis|tesina|trabajo final|monograf[ií]a de grado|informe|documento de trabajo|"
    r"conference|proceedings|symposium|workshop|thesis|dissertation|report|working paper|"
    r"\[en l[ií]nea\]|recuperado de|disponible en)\b", re.I)


# ─────────────────────────────────────────────
#  RED
# ─────────────────────────────────────────────

def http_json(url, timeout=T_API, headers=None):
    """Devuelve (estado_http, datos). Estado 0 = sin respuesta (red o tiempo)."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    try:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def _con_mailto(params):
    if CONTACT_EMAIL:
        params["mailto"] = CONTACT_EMAIL
    return params


def _host_publico(host):
    """Solo se abren direcciones públicas (evita que el servidor sea usado
    para alcanzar redes internas)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return None            # no resuelve
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False
        except ValueError:
            return False
    return True


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def abrir_pagina(url):
    """Abre la dirección citada siguiendo redirecciones de forma controlada.
    Devuelve dict: estado ('viva'|'caida'|'bloqueada'|'sin_respuesta'|'invalida'),
    codigo, url_final, tipo, texto."""
    abridor = urllib.request.build_opener(_SinRedireccion)
    actual = url
    for _ in range(6):
        p = urllib.parse.urlsplit(actual)
        if p.scheme not in ("http", "https") or not p.hostname:
            return {"estado": "invalida", "codigo": 0}
        publico = _host_publico(p.hostname)
        if publico is None:
            return {"estado": "caida", "codigo": 0, "detalle": "el dominio no existe"}
        if not publico:
            return {"estado": "invalida", "codigo": 0}
        try:
            # Direcciones con tildes o espacios
            segura = urllib.parse.urlunsplit((p.scheme, p.netloc.encode("idna").decode("ascii") if not p.netloc.isascii() else p.netloc,
                                              urllib.parse.quote(p.path, safe="/%:@!$&'()*+,;=~-._"),
                                              urllib.parse.quote(p.query, safe="=&%:@!$'()*+,;/?~-._"), ""))
            req = urllib.request.Request(segura, headers={
                "User-Agent": UA_NAVEGADOR, "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
                "Accept-Language": "es,en;q=0.8,pt;q=0.6"})
            with abridor.open(req, timeout=T_PAGINA) as resp:
                tipo = (resp.headers.get("Content-Type") or "").lower()
                cuerpo = resp.read(MAX_PAGINA) if "html" in tipo or "xml" in tipo or not tipo else b""
                m = re.search(r"charset=([\w\-]+)", tipo)
                try:
                    texto = cuerpo.decode(m.group(1) if m else "utf-8", errors="replace")
                except LookupError:
                    texto = cuerpo.decode("utf-8", errors="replace")
                return {"estado": "viva", "codigo": resp.status, "url_final": actual, "tipo": tipo, "texto": texto}
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                actual = urllib.parse.urljoin(actual, e.headers["Location"])
                continue
            if e.code in (404, 410):
                return {"estado": "caida", "codigo": e.code, "detalle": f"la página devuelve error {e.code}"}
            if e.code in (401, 402, 403, 405, 406, 429, 451, 503):
                return {"estado": "bloqueada", "codigo": e.code}
            return {"estado": "sin_respuesta", "codigo": e.code}
        except Exception:
            return {"estado": "sin_respuesta", "codigo": 0}
    return {"estado": "sin_respuesta", "codigo": 0}


def titulos_de_pagina(texto):
    """Títulos declarados por la página (metadatos académicos primero)."""
    out = []
    for nombre in ("citation_title", "DC.title", "dc.title", "DCTERMS.title", "og:title", "twitter:title"):
        for m in re.finditer(
                r"<meta[^>]+(?:name|property)\s*=\s*[\"']" + re.escape(nombre) + r"[\"'][^>]*>", texto, re.I):
            c = re.search(r"content\s*=\s*(\"([^\"]*)\"|'([^']*)')", m.group(0), re.I)
            if c:
                out.append(html.unescape(c.group(2) or c.group(3) or "").strip())
    m = re.search(r"<title[^>]*>(.*?)</title>", texto, re.I | re.S)
    if m:
        out.append(html.unescape(re.sub(r"\s+", " ", m.group(1))).strip())
    m = re.search(r"<h1[^>]*>(.*?)</h1>", texto, re.I | re.S)
    if m:
        out.append(html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(1))).strip())
    return [t for t in out if t]


def copia_archivada(url):
    estado, d = http_json("https://archive.org/wayback/available?" + urllib.parse.urlencode({"url": url}), timeout=7)
    if estado == 200 and d:
        c = (d.get("archived_snapshots") or {}).get("closest") or {}
        if c.get("available") and c.get("url"):
            return c["url"].replace("http://web.archive.org", "https://web.archive.org")
    return ""


# ─────────────────────────────────────────────
#  COMPARACIÓN
# ─────────────────────────────────────────────

def _razon(a, b):
    if not a or not b:
        return 0.0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    return sm.ratio() if sm.quick_ratio() > 0.6 else 0.0


def similitud_titulo(titulo_registro, ref):
    """0–1. Compara el título del registro con el título reconocido en la
    referencia y, además, lo busca dentro del texto completo de la referencia
    (así no depende de haber reconocido bien el título)."""
    a = normalizar(titulo_registro)
    if not a:
        return 0.0
    g = normalizar(ref.get("titulo", ""))
    r = normalizar(re.sub(r"10\.\d{4,9}/\S+", " ", RE_URL.sub(" ", ref.get("raw", ""))))
    ta, tg, tr = a.split(), g.split(), r.split()
    mejor = _razon(a, g)
    if len(ta) >= 4:
        if f" {a} " in f" {r} ":
            return 1.0
        n = len(ta)
        for ancho in (n, n - 1, n + 1):
            if ancho < 3:
                continue
            for i in range(0, max(1, len(tr) - ancho + 1)):
                mejor = max(mejor, _razon(a, " ".join(tr[i:i + ancho])))
                if mejor > 0.97:
                    return mejor
    # El registro o la referencia omiten el subtítulo
    if len(tg) >= 4 and len(ta) >= 4 and (a.startswith(g + " ") or g.startswith(a + " ")):
        mejor = max(mejor, 0.9)
    return mejor


def autores_coinciden(cand, ref):
    """True / False / None (sin datos para decidir)."""
    apellidos = [x for x in cand.get("apellidos", []) if x]
    if not apellidos:
        return None
    tokens = set(normalizar(ref.get("raw", "")).split())
    for ap in apellidos[:4]:
        partes = [p for p in normalizar(ap).split() if len(p) > 1]
        if not partes:
            continue
        if all(p in tokens for p in partes):
            return True
        # Nombre completo («Federico García Lorca»): alcanza con un apellido
        if cand.get("nombres_completos") and any(p in tokens for p in partes[-2:] if len(p) > 3):
            return True
    return None if cand.get("autor_institucional") else False


def anio_coincide(cand, ref):
    anios = [int(a) for a in cand.get("anios", []) if str(a).isdigit()]
    if not anios or not ref.get("anio"):
        return None
    y = int(ref["anio"])
    if any(abs(a - y) <= 1 for a in anios):
        return True
    return None if cand.get("anio_flexible") else False


def evaluar(cand, ref, directo=False):
    """directo=True cuando el registro viene del propio enlace citado (DOI):
    ahí un título corto no es ambiguo."""
    sim = similitud_titulo(cand.get("titulo", ""), ref)
    au, an = autores_coinciden(cand, ref), anio_coincide(cand, ref)
    corto = not directo and len(normalizar(cand.get("titulo", "")).split()) < 4
    if sim >= 0.88:
        if corto and au is not True:
            nivel = "no"
        elif au is False or an is False:
            nivel = "parcial"
        else:
            nivel = "coincide"
    elif sim >= 0.72 and au is True and not corto:
        nivel = "parcial"
    else:
        nivel = "no"
    dif = []
    if nivel == "parcial":
        if sim < 0.88:
            dif.append("El título registrado es parecido pero no igual al citado.")
        if au is False:
            dif.append("Los autores registrados (" + (cand.get("autores") or "sin dato") +
                       ") no coinciden con los citados.")
        if an is False:
            dif.append(f"El año registrado es {cand['anios'][0]} y la referencia dice {ref['anio']}.")
    return {"sim": round(sim, 3), "autor": au, "anio": an, "nivel": nivel, "diferencias": dif}


# ─────────────────────────────────────────────
#  NORMALIZACIÓN DE REGISTROS
# ─────────────────────────────────────────────

def _registro(fuente, titulo, personas=None, anios=None, revista="", doi="", url="",
              retractada=False, nombres_completos=False, anio_flexible=False):
    """personas: lista de (apellido, nombre_para_mostrar)."""
    personas = [p for p in (personas or []) if p and (p[0] or p[1])]
    muestra = [p[1] or p[0] for p in personas[:3]]
    autores = "; ".join(muestra) + ("; et al." if len(personas) > 3 else "")
    doi = limpiar_doi(doi)
    return {
        "fuente": fuente, "titulo": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", titulo or "")).strip(),
        "apellidos": [p[0] for p in personas], "autores": autores,
        "nombres_completos": nombres_completos,
        "autor_institucional": bool(personas) and all(len(p) > 2 and p[2] for p in personas),
        "anios": [str(a) for a in (anios or []) if a], "anio_flexible": anio_flexible,
        "revista": revista or "", "doi": doi,
        "url": url or (f"https://doi.org/{doi}" if doi else ""),
        "retractada": bool(retractada),
    }


def _de_crossref(m):
    personas = []
    for a in m.get("author") or m.get("editor") or []:
        if a.get("family"):
            personas.append((a["family"], (a["family"] + ", " + a.get("given", "")).strip(", ")))
        elif a.get("name"):
            personas.append((a["name"], a["name"], True))
    anio = ""
    for clave in ("issued", "published", "published-print", "published-online", "created"):
        partes = (m.get(clave) or {}).get("date-parts") or [[None]]
        if partes and partes[0] and partes[0][0]:
            anio = partes[0][0]
            break
    titulo = " ".join(m.get("title") or [])
    retract = any((u.get("type") or "").lower() in ("retraction", "withdrawal", "removal")
                  for u in (m.get("updated-by") or [])) or bool(re.match(r"^\s*(retracted|retraction)\b", titulo, re.I))
    return _registro("Crossref", titulo, personas, [anio], " ".join(m.get("container-title") or []),
                     m.get("DOI", ""), retractada=retract)


def _de_openalex(w):
    personas = []
    for a in w.get("authorships") or []:
        n = ((a.get("author") or {}).get("display_name") or "").strip()
        if n:
            personas.append((n, n))
    fuente = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    return _registro("OpenAlex", w.get("display_name") or w.get("title") or "", personas,
                     [w.get("publication_year")], fuente, (w.get("doi") or ""),
                     url=(w.get("doi") or w.get("id") or ""), retractada=w.get("is_retracted"),
                     nombres_completos=True)


# ─────────────────────────────────────────────
#  FUENTES — por DOI
# ─────────────────────────────────────────────

def crossref_doi(doi):
    estado, d = http_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/") +
                          ("?" + urllib.parse.urlencode(_con_mailto({})) if CONTACT_EMAIL else ""))
    if estado == 200 and d and d.get("message"):
        return "ok", _de_crossref(d["message"])
    return ("no", None) if estado == 404 else ("sin_respuesta", None)


def openalex_doi(doi):
    estado, d = http_json("https://api.openalex.org/works/https://doi.org/" + urllib.parse.quote(doi, safe="/") +
                          "?" + urllib.parse.urlencode(_con_mailto(
                              {"select": "id,doi,display_name,publication_year,authorships,primary_location,is_retracted"})))
    if estado == 200 and d:
        return "ok", _de_openalex(d)
    return ("no", None) if estado == 404 else ("sin_respuesta", None)


def datacite_doi(doi):
    estado, d = http_json("https://api.datacite.org/dois/" + urllib.parse.quote(doi, safe="/"),
                          headers={"Accept": "application/vnd.api+json"})
    if estado == 200 and d and d.get("data"):
        at = d["data"].get("attributes") or {}
        personas = []
        for c in at.get("creators") or []:
            if c.get("familyName"):
                personas.append((c["familyName"], c.get("name") or c["familyName"]))
            elif c.get("name"):
                personas.append((c["name"].split(",")[0], c["name"]))
        titulo = ((at.get("titles") or [{}])[0]).get("title", "")
        return "ok", _registro("DataCite", titulo, personas, [at.get("publicationYear")],
                               at.get("publisher") if isinstance(at.get("publisher"), str) else (at.get("publisher") or {}).get("name", ""),
                               at.get("doi", doi))
    return ("no", None) if estado == 404 else ("sin_respuesta", None)


def doi_existe(doi):
    """Consulta el registro general de DOI (cubre agencias sin API propia, como mEDRA)."""
    estado, d = http_json("https://doi.org/api/handles/" + urllib.parse.quote(doi, safe="/"), timeout=7)
    if estado == 200 and d:
        return d.get("responseCode") == 1
    if estado == 404:
        return False
    return None


# ─────────────────────────────────────────────
#  FUENTES — búsqueda por título y autor
# ─────────────────────────────────────────────

def _consulta(ref):
    return (ref.get("titulo") or "").strip()[:300]


def buscar_crossref(ref):
    cita = re.sub(r"\b10\.\d{4,9}/\S+", " ", RE_URL.sub(" ", ref.get("raw", "")))
    cita = re.sub(r"\s+", " ", cita).strip()[:400]
    params = _con_mailto({"rows": "5", "query.bibliographic": cita or _consulta(ref)})
    estado, d = http_json("https://api.crossref.org/works?" + urllib.parse.urlencode(params))
    if estado != 200 or not d:
        return "sin_respuesta", []
    return "ok", [_de_crossref(it) for it in (d.get("message") or {}).get("items", [])]


def buscar_openalex(ref):
    q = re.sub(r"[,|:]", " ", _consulta(ref))
    if not q:
        return "ok", []
    params = _con_mailto({"per-page": "5", "search": q,
                          "select": "id,doi,display_name,publication_year,authorships,primary_location,is_retracted"})
    estado, d = http_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params))
    if estado != 200 or d is None:
        return "sin_respuesta", []
    return "ok", [_de_openalex(w) for w in d.get("results", [])]


def buscar_semantic(ref):
    q = _consulta(ref)
    if not q:
        return "ok", []
    url = ("https://api.semanticscholar.org/graph/v1/paper/search/match?" +
           urllib.parse.urlencode({"query": q, "fields": "title,authors,year,externalIds,venue,url"}))
    estado, d = http_json(url, headers={"x-api-key": S2_API_KEY} if S2_API_KEY else None)
    if estado == 404:
        return "ok", []
    if estado != 200 or d is None:
        return "sin_respuesta", []
    out = []
    for p in d.get("data", []):
        personas = [(a.get("name", ""), a.get("name", "")) for a in p.get("authors") or []]
        out.append(_registro("Semantic Scholar", p.get("title", ""), personas, [p.get("year")], p.get("venue", ""),
                             (p.get("externalIds") or {}).get("DOI", ""), url=p.get("url", ""), nombres_completos=True))
    return "ok", out


def buscar_pubmed(ref):
    q = re.sub(r"[\[\]()\"]", " ", _consulta(ref))
    if not q:
        return "ok", []
    extra = {"tool": "verificadorbibliografias"}
    if CONTACT_EMAIL:
        extra["email"] = CONTACT_EMAIL
    if NCBI_API_KEY:
        extra["api_key"] = NCBI_API_KEY
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    estado, d = http_json(base + "esearch.fcgi?" + urllib.parse.urlencode(
        dict(db="pubmed", term=f"{q}[Title]", retmax="4", retmode="json", sort="relevance", **extra)))
    if estado != 200 or d is None:
        return "sin_respuesta", []
    ids = (d.get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return "ok", []
    estado, d = http_json(base + "esummary.fcgi?" + urllib.parse.urlencode(
        dict(db="pubmed", id=",".join(ids), retmode="json", **extra)))
    if estado != 200 or d is None:
        return "sin_respuesta", []
    out = []
    for pmid in ids:
        info = (d.get("result") or {}).get(pmid) or {}
        if not info.get("title"):
            continue
        personas = []
        for a in info.get("authors") or []:
            n = a.get("name", "")
            personas.append((" ".join(n.split()[:-1]) or n, n))
        doi = next((x.get("value", "") for x in info.get("articleids") or [] if x.get("idtype") == "doi"), "")
        tipos = " ".join(info.get("pubtype") or []).lower()
        out.append(_registro("PubMed", info["title"], personas, [(info.get("pubdate") or "")[:4]],
                             info.get("fulljournalname") or info.get("source", ""), doi,
                             url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                             retractada="retracted publication" in tipos))
    return "ok", out


def buscar_doaj(ref):
    q = re.sub(r"[\"\\/:()\[\]{}!^~*?+\-&|<>=]", " ", _consulta(ref))
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        return "ok", []
    url = ("https://doaj.org/api/search/articles/" +
           urllib.parse.quote(f'bibjson.title:"{q}"', safe="") + "?pageSize=5")
    estado, d = http_json(url)
    if estado != 200 or d is None:
        return "sin_respuesta", []
    out = []
    for r in d.get("results", []):
        b = r.get("bibjson") or {}
        personas = [(a.get("name", ""), a.get("name", "")) for a in b.get("author") or []]
        doi = next((i.get("id", "") for i in b.get("identifier") or [] if i.get("type") == "doi"), "")
        enlace = next((l.get("url", "") for l in b.get("link") or [] if l.get("url")), "")
        out.append(_registro("DOAJ", b.get("title", ""), personas, [b.get("year")],
                             (b.get("journal") or {}).get("title", ""), doi, url=enlace, nombres_completos=True))
    return "ok", out


def buscar_openlibrary(ref):
    q = _consulta(ref)
    if not q:
        return "ok", []
    params = {"title": q, "limit": "5", "fields": "key,title,subtitle,author_name,first_publish_year,publish_year"}
    if ref.get("autor"):
        params["author"] = ref["autor"]
    estado, d = http_json("https://openlibrary.org/search.json?" + urllib.parse.urlencode(params))
    if estado != 200 or d is None:
        return "sin_respuesta", []
    out = []
    for doc in d.get("docs", []):
        personas = [(n, n) for n in doc.get("author_name") or []]
        anios = [doc.get("first_publish_year")] + list(doc.get("publish_year") or [])[:40]
        out.append(_registro("Open Library", doc.get("title", ""), personas, anios, "",
                             url="https://openlibrary.org" + doc.get("key", ""),
                             nombres_completos=True, anio_flexible=True))
    return "ok", out


def buscar_openaire(ref):
    """OpenAIRE Graph: repositorios institucionales, ponencias y tesis
    (incluida la red latinoamericana). Sin clave."""
    q = _consulta(ref)
    if not q:
        return "ok", []
    url = ("https://api.openaire.eu/graph/v1/researchProducts?" +
           urllib.parse.urlencode({"mainTitle": q, "pageSize": "5"}))
    estado, d = http_json(url)
    if estado != 200 or d is None:
        return "sin_respuesta", []
    out = []
    for r in d.get("results") or []:
        personas = []
        for a in r.get("authors") or []:
            n = (a.get("fullName") or " ".join(x for x in (a.get("name"), a.get("surname")) if x) or "").strip()
            if n:
                personas.append((a.get("surname") or n, n))
        doi = next((p.get("value", "") for p in r.get("pids") or [] if (p.get("scheme") or "").lower() == "doi"), "")
        enlace = ""
        for inst in r.get("instances") or []:
            for u in inst.get("urls") or []:
                enlace = enlace or u
        if not enlace and r.get("id"):
            enlace = "https://explore.openaire.eu/search/result?id=" + urllib.parse.quote(r["id"], safe=":")
        fuentes_r = [x for x in r.get("sources") or [] if x and x.lower() not in ("crossref", "datacite", "unpaywall")]
        fuente = (max(fuentes_r, key=len) if fuentes_r else "") or r.get("publisher") or ""
        out.append(_registro("OpenAIRE", r.get("mainTitle") or "", personas,
                             [(r.get("publicationDate") or "")[:4]], fuente[:120], doi, url=enlace,
                             nombres_completos=True))
    return "ok", out


BUSCADORES = {
    "Crossref": buscar_crossref, "OpenAlex": buscar_openalex, "PubMed": buscar_pubmed,
    "DOAJ": buscar_doaj, "OpenAIRE": buscar_openaire, "Open Library": buscar_openlibrary,
}
if S2_API_KEY:
    BUSCADORES["Semantic Scholar"] = buscar_semantic
PRIORIDAD = {n: i for i, n in enumerate(["Crossref", "DataCite", "OpenAlex", "PubMed", "DOAJ", "OpenAIRE",
                                         "Semantic Scholar", "Open Library", "Página citada"])}


def buscar_en_bases(ref):
    """Consulta todas las bases en paralelo. Devuelve (estados, candidatos_evaluados)."""
    estados, evaluados = {}, []
    with ThreadPoolExecutor(max_workers=len(BUSCADORES)) as ex:
        tareas = {ex.submit(f, ref): n for n, f in BUSCADORES.items()}
        for t in as_completed(tareas):
            nombre = tareas[t]
            try:
                estado, cands = t.result()
            except Exception:
                estado, cands = "sin_respuesta", []
            if estado != "ok":
                estados[nombre] = "sin_respuesta"
                continue
            mejor = "no"
            for c in cands:
                ev = evaluar(c, ref)
                if ev["nivel"] != "no":
                    evaluados.append((c, ev))
                    mejor = "encontrada" if ev["nivel"] == "coincide" or mejor == "encontrada" else "parecida"
            estados[nombre] = mejor
    return estados, evaluados


def _mejor(evaluados):
    if not evaluados:
        return None, None
    return min(evaluados, key=lambda ce: (ce[1]["nivel"] != "coincide", -ce[1]["sim"],
                                          PRIORIDAD.get(ce[0]["fuente"], 99)))


# ─────────────────────────────────────────────
#  VERIFICACIÓN COMPLETA
# ─────────────────────────────────────────────

def _publico(c):
    return {k: c.get(k, "") for k in ("fuente", "titulo", "autores", "revista", "doi", "url")} | {
        "anio": (c.get("anios") or [""])[0]}


def _enlaces_busqueda(ref):
    q = ref.get("titulo") or ref.get("raw", "")[:200]
    return {"scholar": "https://scholar.google.com/scholar?" + urllib.parse.urlencode(
                {"q": (q + " " + (ref.get("autor") or "")).strip()}),
            "google": "https://www.google.com/search?" + urllib.parse.urlencode({"q": f'"{q}"'})}


def verificar(ref):
    notas, enlace, registro = [], None, None
    estados = {n: "no_consultada" for n in FUENTES}
    confirmada = False      # el enlace citado alcanzó para confirmar
    parcial_enlace = None   # el enlace lleva a un registro con datos distintos
    retractada = False

    # ── 1 · El enlace citado ──────────────────────────────
    doi = ref.get("doi") or ""
    if doi:
        enlace = {"tipo": "doi", "valor": doi, "url": "https://doi.org/" + doi}
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_cr, f_oa = ex.submit(crossref_doi, doi), ex.submit(openalex_doi, doi)
            (e_cr, c_cr), (e_oa, c_oa) = f_cr.result(), f_oa.result()
        estados["Crossref"] = {"ok": "encontrada", "no": "no"}.get(e_cr, "sin_respuesta")
        estados["OpenAlex"] = {"ok": "encontrada", "no": "no"}.get(e_oa, "sin_respuesta")
        cand = c_cr or c_oa
        if not cand and e_cr != "sin_respuesta":
            e_dc, cand = datacite_doi(doi)
            if cand:
                estados["DataCite"] = "encontrada"
        if cand:
            ev = evaluar(cand, ref, directo=True)
            retractada = bool((c_cr or {}).get("retractada") or (c_oa or {}).get("retractada"))
            if ev["nivel"] == "coincide":
                confirmada, registro = True, cand
                enlace.update(estado="coincide", detalle="El DOI existe y sus datos coinciden con la referencia.")
            elif ev["nivel"] == "parcial":
                parcial_enlace, registro = ev, cand
                enlace.update(estado="coincide", detalle="El DOI existe y lleva a un trabajo con este título.")
            else:
                retractada = False
                enlace.update(estado="otro_trabajo",
                              detalle=f"El DOI existe pero pertenece a otro trabajo: «{cand['titulo'][:160]}».")
                for n in ("Crossref", "OpenAlex"):
                    estados[n] = "no_consultada"
        else:
            existe = doi_existe(doi)
            if existe:
                enlace.update(estado="ok", detalle="El DOI está registrado, pero su agencia no ofrece los datos para compararlos.")
            elif existe is False and e_cr == "no":
                enlace.update(estado="no_existe", detalle="El DOI citado no está registrado.")
            else:
                enlace.update(estado="sin_comprobar", detalle="No se pudo consultar el DOI en este momento.")

    url = ref.get("url") or ""
    if url and not confirmada and not parcial_enlace:
        pag = abrir_pagina(url)
        e_url = {"tipo": "url", "valor": url, "url": url}
        alt = ref.get("url_alt") or ""
        if pag["estado"] != "viva" and alt and alt != url:
            pag_alt = abrir_pagina(alt)
            if pag_alt["estado"] == "viva":
                pag = pag_alt
                e_url.update(valor=alt, url=alt)
                notas.append("El enlace citado tenía un guion de corte de línea dentro de la dirección. "
                             "Sin ese guion, la página funciona.")
        if pag["estado"] == "viva":
            sims = [(similitud_titulo(t, ref), t) for t in titulos_de_pagina(pag.get("texto", ""))]
            sim, tit = max(sims, default=(0, ""))
            if sim >= 0.85:
                e_url.update(estado="coincide", detalle="La página responde y su título coincide con la referencia.")
                if not registro:
                    confirmada = True
                    registro = _registro("Página citada", tit, url=pag.get("url_final") or url)
            elif "pdf" in pag.get("tipo", ""):
                e_url.update(estado="ok", detalle="El enlace responde y entrega un PDF. No se comparó su contenido.")
            else:
                e_url.update(estado="ok", detalle="El enlace responde, pero la página no declara un título que permita confirmarla.")
        elif pag["estado"] == "caida":
            archivo = copia_archivada(url)
            e_url.update(estado="caido", detalle="El enlace citado no funciona (" + pag.get("detalle", "sin respuesta") + ")." +
                         (" Hay una copia en Internet Archive." if archivo else ""), archivo=archivo)
        elif pag["estado"] == "bloqueada":
            e_url.update(estado="sin_comprobar", detalle="El sitio no permite la consulta automática. Abrilo a mano para comprobarlo.")
        elif pag["estado"] == "invalida":
            e_url.update(estado="sin_comprobar", detalle="La dirección no es una página web pública.")
        else:
            e_url.update(estado="sin_comprobar", detalle="El sitio no respondió a tiempo.")
        if enlace:                       # había DOI y además URL
            enlace["segundo"] = e_url
        else:
            enlace = e_url

    # ── 2 · Búsqueda en bases de datos ────────────────────
    hallado = None
    if not confirmada and not parcial_enlace:
        est_b, evaluados = buscar_en_bases(ref)
        for n, v in est_b.items():
            estados[n] = v
        cand, ev = _mejor(evaluados)
        if cand:
            hallado = ev
            registro = cand
            retractada = any(c.get("retractada") for c, e in evaluados if e["nivel"] == "coincide")

    # ── 3 · Dictamen ──────────────────────────────────────
    e_estado = (enlace or {}).get("estado")
    seg = ((enlace or {}).get("segundo") or {}).get("estado")
    if confirmada:
        estado, resumen = "verificada", "El enlace citado confirma la referencia."
        if registro and registro["fuente"] == "Página citada":
            resumen = "La página citada existe y su título coincide."
    elif parcial_enlace:
        estado, resumen = "observaciones", "El DOI lleva al trabajo, pero algunos datos citados no coinciden con el registro."
        notas += parcial_enlace["diferencias"]
    elif hallado and hallado["nivel"] == "coincide":
        donde = ", ".join(n for n, v in estados.items() if v == "encontrada")
        if e_estado in ("no_existe", "sin_comprobar") and doi and (registro.get("doi") or "").lower() == doi.lower():
            # La base confirma ese mismo DOI aunque el registro general no haya respondido.
            estado, resumen = "verificada", f"Encontrada por título y autor en {donde}, con el mismo DOI citado."
            enlace.update(estado="coincide", detalle="El DOI coincide con el del registro encontrado.")
        elif e_estado in ("otro_trabajo", "no_existe"):
            estado = "observaciones"
            resumen = f"El trabajo existe ({donde}), pero el DOI citado es incorrecto."
            if registro.get("doi"):
                notas.append(f"DOI registrado para este trabajo: {registro['doi']}")
        else:
            estado, resumen = "verificada", f"Encontrada por título y autor en {donde}."
            if "caido" in (e_estado, seg):
                notas.append("El enlace citado ya no funciona, pero el trabajo existe." +
                             (f" Enlace vigente: {registro['url']}" if registro.get("url") else ""))
    elif hallado:
        estado, resumen = "observaciones", "Se encontró un trabajo muy parecido, con diferencias respecto de lo citado."
        notas += hallado["diferencias"]
    else:
        registro = None
        consultadas = [v for n, v in estados.items() if n in BUSCADORES]
        sin_resp = sum(1 for v in consultadas if v == "sin_respuesta")
        if e_estado == "otro_trabajo" or e_estado == "no_existe":
            estado = "no_encontrada"
            resumen = "No se encontró en ninguna base y el DOI citado " + \
                      ("pertenece a otro trabajo." if e_estado == "otro_trabajo" else "no existe.") + \
                      " Es una señal fuerte de referencia inventada o mal copiada."
        elif "ok" in (e_estado, seg) or (e_estado == "coincide"):
            estado, resumen = "observaciones", "El enlace citado funciona, pero no se pudo confirmar el contenido de forma automática."
        elif sin_resp >= 3 or estados.get("Crossref") == estados.get("OpenAlex") == "sin_respuesta":
            estado, resumen = "sin_comprobar", "Varias bases no respondieron. Volvé a intentarlo en unos minutos."
        elif "caido" in (e_estado, seg) and RE_LITERATURA_GRIS.search(ref.get("raw", "")):
            estado = "observaciones"
            resumen = ("El enlace citado no funciona y el documento no figura en las bases, "
                       "que cubren poco ponencias, tesis e informes.")
            notas.append("Puede ser un documento real cuyo sitio cambió de dirección. "
                         "Buscalo por título en el sitio de la institución o en Google Académico.")
        else:
            estado = "no_encontrada"
            resumen = "No se encontró en las bases consultadas."
            if "caido" in (e_estado, seg):
                resumen = "El enlace citado no funciona y el trabajo no aparece en las bases consultadas."
            notas.append("Las bases cubren sobre todo artículos. Libros, tesis, informes, normas y páginas web "
                         "pueden existir sin figurar en ellas. Comprobala a mano antes de descartarla.")
    if retractada:
        estado, resumen = "retractada", "El trabajo existe, pero figura como retractado."

    return {
        "estado": estado, "resumen": resumen, "notas": notas, "enlace": enlace,
        "registro": _publico(registro) if registro else None,
        "fuentes": [{"nombre": n, "estado": v} for n, v in estados.items()],
        "buscar": _enlaces_busqueda(ref),
    }


# ─────────────────────────────────────────────
#  SALUD DE LAS FUENTES
# ─────────────────────────────────────────────

def salud():
    """Comprueba que cada base devuelva de verdad un registro conocido.
    Devuelve una lista ordenada de {nombre, estado, ms}."""
    import time
    prueba = {"raw": "LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436–444.",
              "titulo": "Deep learning", "autor": "LeCun", "anio": "2015"}
    libro = {"raw": "Borges, J. L. (1944). Ficciones. Sur.", "titulo": "Ficciones", "autor": "Borges", "anio": "1944"}
    repo = {"raw": "Carvidón, E., Paz Torres, M. y Rodríguez-Fleitas, M. (2021). Red de Bibliotecas Parlamentarias "
                   "de América Latina y el Caribe. Informatio, 26(2).",
            "titulo": "Red de Bibliotecas Parlamentarias de América Latina y el Caribe", "autor": "Carvidón", "anio": "2021"}

    def busqueda(f, r):
        def _():
            estado, cands = f(r)
            return "sin_respuesta" if estado != "ok" else ("ok" if cands else "vacia")
        return _

    pruebas = [(n, busqueda(f, libro if n == "Open Library" else repo if n == "OpenAIRE" else prueba))
               for n, f in BUSCADORES.items()]
    pruebas.append(("DataCite", lambda: "ok" if datacite_doi("10.5281/zenodo.3233118")[0] in ("ok", "no") else "sin_respuesta"))
    pruebas.append(("Internet Archive", lambda: "ok" if http_json(
        "https://archive.org/wayback/available?url=example.com", timeout=7)[0] == 200 else "sin_respuesta"))

    def medir(nombre, f):
        t0 = time.monotonic()
        try:
            estado = f()
        except Exception:
            estado = "sin_respuesta"
        return {"nombre": nombre, "estado": estado, "ms": int((time.monotonic() - t0) * 1000)}

    orden = list(BUSCADORES) + ["DataCite", "Internet Archive"]
    with ThreadPoolExecutor(max_workers=len(pruebas)) as ex:
        res = list(ex.map(lambda p: medir(*p), pruebas))
    return sorted(res, key=lambda r: orden.index(r["nombre"]))
