# Verificador Bibliográfico — © 2026 Gabriel Da Costa Porto Luzardo — GPL-3.0
"""Extracción de referencias por reglas (sin IA).

Entrada: PDF, texto pegado, BibTeX o RIS.
Salida: lista de referencias, cada una con su texto original y los datos
que se pudieron reconocer (DOI, URL, año, primer autor, título probable).
"""

import re
import unicodedata

MAYUS = "A-ZÁÉÍÓÚÑÜÀÈÌÒÙÂÊÎÔÛÄËÏÖÇÃÕØÅŠŽČŁ"
MINUS = "a-záéíóúñüàèìòùâêîôûäëïöçãõøåšžčł"

RE_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
RE_URL = re.compile(r"(https?://[^\s<>\"]+)", re.I)
RE_ANIO = re.compile(r"(?<![\d/.\-])(1[5-9]\d{2}|20\d{2})[a-z]?(?![\d/\-])")
FECHA_PREVIA = r"(?:\d{1,2}\s+(?:de\s+)?[A-Za-zÁÉÍÓÚáéíóú]{3,10}\.?,?\s+(?:de\s+|del\s+)?|[A-Za-zÁÉÍÓÚáéíóú]{3,10}\.?\s+\d{1,2},?\s+)?"
RE_ANIO_PAR = re.compile(r"\(\s*" + FECHA_PREVIA + r"(1[5-9]\d{2}|20\d{2})[a-z]?\b[^)]{0,25}\)")
RE_SIN_FECHA = re.compile(r"\(\s*(s\.\s?f\.|n\.\s?d\.|en prensa|in press)\s*\)", re.I)

ENCABEZADOS = (
    r"referencias\s+bibliogr[aá]ficas?", r"referencias", r"bibliograf[ií]a(\s+citada|\s+consultada)?",
    r"literatura\s+citada", r"obras\s+citadas", r"fuentes\s+consultadas", r"lista\s+de\s+referencias",
    r"references(\s+cited)?", r"bibliography", r"works\s+cited", r"literature\s+cited",
    r"refer[eê]ncias(\s+bibliogr[aá]ficas)?", r"bibliografia",
)
RE_ENCABEZADO = re.compile(
    r"^\s*(?:\d{1,2}\.?\s+|[IVX]{1,5}\.?\s+)?(?:" + "|".join(ENCABEZADOS) + r")\s*[:.]?\s*$", re.I)
RE_CORTE = re.compile(
    r"^\s*(?:\d{1,2}\.?\s+|[IVX]{1,5}\.?\s+)?(?:anexos?|ap[eé]ndices?|appendix|appendices|"
    r"agradecimientos|acknowledge?ments|notas|sobre\s+(?:el|la|los)\s+autor(?:es|a)?|"
    r"about\s+the\s+authors?|supplementary\s+material|material\s+suplementario)\b.{0,40}$", re.I)

RE_NUMERADA = re.compile(r"^\s*(?:\[(\d{1,3})\]|\(?(\d{1,3})[.)])\s+(?=\S)")

# Comienzo típico de una referencia autor-año o de autor con iniciales.
RE_INICIO = re.compile(
    r"^(?:"
    # Apellido, I.  |  Apellido Apellido, Nombre  |  de la Torre, J.
    rf"(?:(?:de|del|de la|da|dos|van|von|di|le|la)\s+)?[{MAYUS}][\w'’\-]+(?:[ \-][{MAYUS}][\w'’\-]+){{0,3}},\s+[{MAYUS}]"
    # Vancouver sin número: Apellido AB, ...
    rf"|[{MAYUS}][\w'’\-]+(?:[ \-][{MAYUS}][\w'’\-]+)?\s+[{MAYUS}]{{1,3}}[,.]"
    # Autor institucional seguido del año entre paréntesis
    rf"|[{MAYUS}][^()]{{2,90}}?\.?\s*\((?:" + FECHA_PREVIA + r"(?:1[5-9]\d{2}|20\d{2})|s\.\s?f\.|n\.\s?d\.)"
    # Raya de autor repetido
    r"|[—–_\-]{3,}"
    r")")

MAX_REFERENCIAS = 300


# ─────────────────────────────────────────────
#  UTILIDADES
# ─────────────────────────────────────────────

def normalizar(s):
    """Minúsculas, sin tildes ni signos, espacios simples."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def limpiar_doi(doi):
    doi = (doi or "").strip()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    doi = doi.rstrip(".,;:)]}>'\"”’")
    # Paréntesis de cierre sobrante: 10.1000/abc(1)2 es válido, 10.1000/abc) no.
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    return doi


def _limpiar_url(u):
    u = u.rstrip(".,;:]}>'\"”’")
    while u.endswith(")") and u.count(")") > u.count("("):
        u = u[:-1]
    return u


# ─────────────────────────────────────────────
#  PDF → TEXTO
# ─────────────────────────────────────────────

def _texto_pagina(pagina):
    tp = pagina.get_textpage()
    try:
        t = tp.get_text_range() or ""
    finally:
        tp.close()
    # pdfium marca el guion de fin de línea con caracteres de control
    return t.replace("\ufffe", "-").replace("\x02", "-").replace("\r\n", "\n").replace("\r", "\n")


def texto_de_pdf(datos):
    """Texto del PDF leído desde la última página hacia atrás, hasta encontrar
    el encabezado de la bibliografía. Devuelve (texto, paginas_leidas, total).
    Lanza ValueError con un mensaje legible si no se puede."""
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(datos)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise ValueError("El PDF está protegido con contraseña.")
        raise ValueError("No se pudo leer el archivo como PDF.")
    try:
        total = len(doc)
        paginas = []
        for i in range(total - 1, -1, -1):
            pag = doc[i]
            try:
                paginas.insert(0, _texto_pagina(pag))
            finally:
                pag.close()
            texto = "\n\x0c\n".join(paginas)
            # Un encabezado en esta página con contenido suficiente debajo
            if any(RE_ENCABEZADO.match(l) for l in paginas[0].split("\n")):
                _, hallada = seccion_referencias(texto)
                if hallada:
                    return texto, len(paginas), total
        texto = "\n\x0c\n".join(paginas)
    finally:
        doc.close()
    if len(texto.strip()) < 200:
        raise ValueError("El PDF no tiene texto seleccionable (parece una imagen escaneada). "
                         "Pegá las referencias como texto.")
    return texto, total, total


# ─────────────────────────────────────────────
#  LOCALIZAR LA SECCIÓN DE REFERENCIAS
# ─────────────────────────────────────────────

def seccion_referencias(texto):
    """Devuelve (texto_de_la_seccion, se_encontro_encabezado)."""
    lineas = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n").split("\n")
    candidatos = [i for i, l in enumerate(lineas) if RE_ENCABEZADO.match(l)]
    if not candidatos:
        return texto, False
    # El último encabezado que deja contenido suficiente por debajo
    # (evita la entrada «Referencias» del índice).
    inicio = None
    for i in reversed(candidatos):
        resto = [l for l in lineas[i + 1:] if l.strip()]
        if len(resto) >= 2 and sum(len(l) for l in resto) > 120:
            inicio = i
            break
    if inicio is None:
        return texto, False
    cuerpo = lineas[inicio + 1:]
    for j, l in enumerate(cuerpo):
        if j > 3 and RE_CORTE.match(l) and len(l.strip()) < 60:
            cuerpo = cuerpo[:j]
            break
    return "\n".join(cuerpo), True


# ─────────────────────────────────────────────
#  SEPARAR REFERENCIAS
# ─────────────────────────────────────────────

def _unir(lineas, alternativas=None):
    """Une las líneas de una referencia reparando guiones de corte y enlaces partidos.
    Si un enlace quedó cortado justo después de un guion, no se sabe si el guion
    es parte de la dirección o solo del corte de línea: se conserva y se anota
    en `alternativas` la versión sin guion, para probarla si la primera falla."""
    out = ""
    for l in lineas:
        l = l.strip()
        if not l:
            continue
        if not out:
            out = l
            continue
        ultimo = out.split()[-1]
        en_enlace = bool(re.search(r"(https?://|doi\.org/|^10\.\d{4,9}/)", ultimo, re.I))
        primero = l.split()[0]
        if en_enlace and out[-1] in "/-._=?&%:~" and re.match(r"^[\w\-./?=&%#~+:()]+$", primero):
            if out[-1] == "-" and alternativas is not None:
                cola = re.search(r"[^/\s]*-$", out).group(0)
                cabeza = re.match(r"[^/\s]*", primero).group(0)
                if cola[:-1] and cabeza:
                    alternativas.append((cola + cabeza, cola[:-1] + cabeza))
            out += l                                   # enlace partido
        elif en_enlace and len(ultimo) > 55 and re.match(r"^[\w\-./?=&%#~+]{1,40}\.?$", l):
            out += l                                   # cola de enlace largo
        elif re.search(rf"[{MINUS}]-$", out) and re.match(rf"^[{MINUS}]", l):
            out = out[:-1] + l                         # palabra cortada con guion
        else:
            out += " " + l
    return re.sub(r"\s+", " ", out).strip()


def _es_ruido(l):
    s = l.strip()
    if re.fullmatch(r"\d{1,4}", s):                    # número de página
        return True
    if re.fullmatch(r"(p[aá]g(ina)?\.?|page)\s*\d{1,4}(\s*(de|of|/)\s*\d{1,4})?", s, re.I):
        return True
    return False


def _completa(buf):
    """¿El texto acumulado ya parece una referencia entera?"""
    t = _unir(buf)
    if len(t) < 25:
        return False
    if not (RE_ANIO.search(t) or RE_SIN_FECHA.search(t)):
        return False
    fin = t
    if re.search(r"(https?://\S+|10\.\d{4,9}/\S+)$", fin):
        return True
    if not re.search(r"[.)\]”\"’]$", fin):
        return False
    # Termina en una inicial suelta («…, & López, A.»): la lista de autores sigue.
    return not re.search(rf"(^|[\s(,])[{MAYUS}]\.$", fin)


def _par(lineas):
    """(texto unido, enlaces cortados con guion)"""
    alternativas = []
    return _unir(lineas, alternativas), alternativas


def _por_numeros(lineas):
    marcas = []
    esperado = None
    for i, l in enumerate(lineas):
        m = RE_NUMERADA.match(l)
        if not m:
            continue
        n = int(m.group(1) or m.group(2))
        if esperado is None:
            if n in (1, 2):
                marcas.append(i)
                esperado = n + 1
        elif n == esperado:
            marcas.append(i)
            esperado = n + 1
    if len(marcas) < 3:
        return None
    refs = []
    for k, i in enumerate(marcas):
        fin = marcas[k + 1] if k + 1 < len(marcas) else len(lineas)
        bloque = [x for x in lineas[i:fin] if x.strip()]
        bloque[0] = RE_NUMERADA.sub("", bloque[0], count=1)
        refs.append(_par(bloque))
    return refs


def _por_bloques(lineas):
    bloques, actual = [], []
    for l in lineas:
        if l.strip():
            actual.append(l)
        elif actual:
            bloques.append(actual)
            actual = []
    if actual:
        bloques.append(actual)
    if len(bloques) < 3:
        return None
    textos = [_par(b) for b in bloques]
    buenos = sum(1 for t, _ in textos if len(t) >= 40 and (RE_ANIO.search(t) or RE_SIN_FECHA.search(t)))
    if buenos / len(textos) < 0.8:
        return None
    return textos


def _por_autores(lineas):
    refs, buf, vacia_antes = [], [], False
    for l in lineas:
        if not l.strip():
            vacia_antes = True
            continue
        nueva = False
        if buf and RE_INICIO.match(l.strip()):
            nueva = _completa(buf) or (vacia_antes and len(" ".join(buf)) > 40)
        elif buf and vacia_antes and _completa(buf) and re.match(rf"^[{MAYUS}\"“¿¡\d]", l.strip()):
            nueva = True
        if nueva:
            refs.append(_par(buf))
            buf = []
        buf.append(l)
        vacia_antes = False
    if buf:
        refs.append(_par(buf))
    return refs


def separar_referencias(texto, de_pdf=False):
    """Lista de (texto, alternativas_de_enlace)."""
    lineas = [l for l in texto.replace("\r", "\n").replace("\x0c", "\n").split("\n") if not _es_ruido(l)]
    if de_pdf:
        # En un PDF las líneas en blanco dependen de la maquetación (sangría
        # francesa, saltos de página) y no separan referencias de forma fiable.
        lineas = [l for l in lineas if l.strip()]
        refs = _por_numeros(lineas) or _por_autores(lineas)
    else:
        refs = _por_numeros(lineas) or _por_bloques(lineas) or _por_autores(lineas)
    limpio = []
    for r, alternativas in refs:
        r = re.sub(r"^[•·▪◦\-–*]\s+", "", r).strip()
        if len(r) >= 25 and re.search(r"[A-Za-zÁ-ú]{3}", r):
            limpio.append((r, alternativas))
    return limpio[:MAX_REFERENCIAS]


# ─────────────────────────────────────────────
#  ANALIZAR UNA REFERENCIA
# ─────────────────────────────────────────────

def _segmentos(t):
    """Corta en oraciones sin romper iniciales (J. A.) ni abreviaturas cortas."""
    partes = re.split(rf"(?<=[{MINUS}\d)\]”\"’?!][{MINUS}\d)\]”\"’?!])[.?!]\s+(?=[{MAYUS}\"“«¿¡\d\[])", t)
    return [p.strip() for p in partes if p.strip()]


def _parece_autores(seg):
    if re.search(r"\bet al\b", seg, re.I):
        return True
    iniciales = len(re.findall(rf"\b[{MAYUS}]\.", seg)) + len(re.findall(rf"\b[{MAYUS}]{{1,3}}(?=,|$)", seg))
    palabras = len(seg.split())
    return iniciales >= 1 and iniciales * 3 >= palabras - 2


def _espaciar(t):
    """Agrega el espacio que falta tras un punto entre dos palabras
    («publishing.Tidsskrift»), sin tocar enlaces ni dominios."""
    return re.sub(rf"(?<=[{MINUS}]{{3}})\.(?=[{MAYUS}][{MINUS}])", ". ", t)


def _titulo_probable(raw):
    t = _espaciar(RE_URL.sub(" ", raw))
    t = re.sub(r"\b(doi:?\s*)?10\.\d{4,9}/\S+", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()

    # 1 · Título entre comillas
    m = re.search(r"[“\"«]([^”\"»]{15,300})[”\"»]", t)
    if m and len(m.group(1).split()) >= 3:
        return m.group(1).strip(" .,")

    # 2 · Autor (año). Título.   /   Autor. Año. Título.
    m = RE_ANIO_PAR.search(t) or RE_SIN_FECHA.search(t)
    resto = None
    if m and m.start() < len(t) * 0.6:
        resto = t[m.end():].lstrip(" .,:;")
    else:
        m2 = re.search(r"[.,]\s+(1[5-9]\d{2}|20\d{2})[a-z]?\.\s+", t)
        if m2 and m2.start() < len(t) * 0.5:
            resto = t[m2.end():]
    if resto:
        segs = _segmentos(resto)
        if segs:
            return segs[0].strip(" .,")

    # 3 · Vancouver: Apellido AB, Apellido C. Título. Revista. Año;vol:pp.
    t = RE_NUMERADA.sub("", t)
    m = re.match(rf"^(?:[{MAYUS}][\w'’\-]+(?:[ \-][{MAYUS}{MINUS}][\w'’\-]+)?\s+[{MAYUS}]{{1,3}}"
                 rf"(?:,\s+et al\.\s+|,\s+|\.\s+))+", t)
    if m and t[:m.end()].rstrip().endswith("."):
        segs = _segmentos(t[m.end():])
        if segs:
            return segs[0].strip(" .,")

    # 4 · ISO y otros: Autores. Título. Datos de publicación.
    segs = _segmentos(t)
    for i, seg in enumerate(segs):
        if i == 0 and (_parece_autores(seg) or len(segs) > 1):
            continue
        if len(seg.split()) >= 3 and not _parece_autores(seg):
            return seg.strip(" .,")
    return max(segs, key=len).strip(" .,") if segs else t


def _primer_apellido(raw):
    t = RE_NUMERADA.sub("", raw).strip()
    # Iniciales primero: «M. Hagve (2020)», «J. L. Borges»
    m = re.match(rf"^(?:[{MAYUS}]\.\s*(?:-\s*)?){{1,3}}((?:(?:de|del|de la|van|von)\s+)?[{MAYUS}][\w'’\-]+)", t)
    if m:
        return m.group(1)
    # Nombre y apellido antes del año: «Claudio Aspesi (2019)»
    m = re.match(rf"^[{MAYUS}][{MINUS}]+\s+([{MAYUS}][{MINUS}][\w'’\-]+)\s*\(", t)
    if m:
        return m.group(1)
    m = re.match(rf"^((?:(?:de|del|de la|da|dos|van|von|di|le|la)\s+)?[{MAYUS}][\w'’\-]+(?:[ \-][{MAYUS}{MINUS}][\w'’\-]+){{0,2}}?)"
                 rf"(?:,|\s+[{MAYUS}]{{1,3}}\b[,.]|\s+et al|\s*\(|\s+(?:y|and|&)\s)", t)
    if m:
        return m.group(1).strip()
    m = re.match(rf"^([{MAYUS}][\w'’\-]+)", t)
    return m.group(1) if m else ""


def analizar(raw, alternativas=()):
    """Datos reconocibles de una referencia en texto libre."""
    raw = re.sub(r"\s+", " ", raw or "").strip()
    # DOI partido por un espacio tras el prefijo: «10.1234/ abc»
    compacto = re.sub(r"(10\.\d{4,9}/)\s+(?=\S)", r"\1", raw)
    doi = ""
    m = RE_DOI.search(compacto)
    if m:
        doi = limpiar_doi(m.group(1))
    url = ""
    for u in RE_URL.findall(raw):
        u = _limpiar_url(u)
        if re.search(r"(^https?://(dx\.)?doi\.org/)", u, re.I):
            continue
        url = u
        break
    url_alt = ""
    for con, sin in alternativas or ():
        if url and con in url:
            url_alt = url.replace(con, sin)
            break
    sin_enlaces = re.sub(r"\b10\.\d{4,9}/\S+", " ", RE_URL.sub(" ", raw))
    m = RE_ANIO_PAR.search(sin_enlaces) or RE_ANIO.search(sin_enlaces)
    anio = m.group(1) if m else ""
    return {
        "raw": raw,
        "doi": doi,
        "url": url,
        "url_alt": url_alt,
        "anio": anio,
        "autor": _primer_apellido(raw),
        "titulo": _titulo_probable(raw),
    }


# ─────────────────────────────────────────────
#  BIBTEX Y RIS
# ─────────────────────────────────────────────

def _quitar_latex(s):
    s = re.sub(r"\\[`'^\"~=.uvHtcdbk]\s*\{?\\?([A-Za-z])\}?", r"\1", s)   # acentos LaTeX
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    return re.sub(r"\s+", " ", s.replace("{", "").replace("}", "").replace("~", " ")).strip()


def parse_bibtex(texto):
    refs = []
    for m in re.finditer(r"@(\w+)\s*\{", texto):
        tipo = m.group(1).lower()
        if tipo in ("comment", "string", "preamble"):
            continue
        i, nivel = m.end(), 1
        while i < len(texto) and nivel:
            nivel += {"{": 1, "}": -1}.get(texto[i], 0)
            i += 1
        cuerpo = texto[m.end():i - 1]
        campos = {}
        for c in re.finditer(r"(\w+)\s*=\s*", cuerpo):
            j = c.end()
            if j >= len(cuerpo):
                continue
            if cuerpo[j] == "{":
                k, nv = j + 1, 1
                while k < len(cuerpo) and nv:
                    nv += {"{": 1, "}": -1}.get(cuerpo[k], 0)
                    k += 1
                valor = cuerpo[j + 1:k - 1]
            elif cuerpo[j] == '"':
                k = cuerpo.find('"', j + 1)
                valor = cuerpo[j + 1:k if k > 0 else len(cuerpo)]
            else:
                valor = re.match(r"[^,\n]*", cuerpo[j:]).group(0)
            campos.setdefault(c.group(1).lower(), _quitar_latex(valor))
        if not campos.get("title"):
            continue
        autores = [a.strip() for a in re.split(r"\s+and\s+", campos.get("author") or campos.get("editor") or "") if a.strip()]
        refs.append(_desde_campos(
            autores, campos.get("year") or (campos.get("date") or "")[:4], campos["title"],
            campos.get("journal") or campos.get("journaltitle") or campos.get("booktitle") or campos.get("publisher") or "",
            campos.get("doi", ""), campos.get("url", "")))
    return refs[:MAX_REFERENCIAS]


def parse_ris(texto):
    refs, actual = [], None
    for linea in texto.replace("\r", "\n").split("\n"):
        m = re.match(r"^([A-Z][A-Z0-9])\s{1,2}-\s?(.*)$", linea.strip("\ufeff"))
        if not m:
            continue
        et, val = m.group(1), m.group(2).strip()
        if et == "TY":
            actual = {}
        elif et == "ER":
            if actual and (actual.get("TI") or actual.get("T1")):
                refs.append(_desde_campos(
                    actual.get("AU", []),
                    (actual.get("PY") or actual.get("Y1") or actual.get("DA") or [""])[0][:4],
                    (actual.get("TI") or actual.get("T1"))[0],
                    (actual.get("JO") or actual.get("JF") or actual.get("T2") or actual.get("PB") or [""])[0],
                    (actual.get("DO") or [""])[0],
                    (actual.get("UR") or [""])[0]))
            actual = None
        elif actual is not None and val:
            if et == "A1":
                et = "AU"
            actual.setdefault(et, []).append(val)
    return refs[:MAX_REFERENCIAS]


def _desde_campos(autores, anio, titulo, fuente, doi, url):
    doi = limpiar_doi(doi)
    if url and re.search(r"doi\.org/", url, re.I):
        doi = doi or limpiar_doi(url)
        url = ""
    nombres = "; ".join(autores[:6]) + ("; et al." if len(autores) > 6 else "")
    partes = [p for p in (nombres, f"({anio})" if anio else "", titulo.rstrip(".") + ".",
                          fuente + "." if fuente else "",
                          f"https://doi.org/{doi}" if doi else url) if p]
    primero = autores[0] if autores else ""
    apellido = primero.split(",")[0].strip() if "," in primero else (primero.split()[-1] if primero else "")
    return {"raw": " ".join(partes), "doi": doi, "url": url, "anio": anio if re.fullmatch(r"\d{4}", anio or "") else "",
            "autor": apellido, "titulo": titulo.strip()}


# ─────────────────────────────────────────────
#  ENTRADA GENERAL
# ─────────────────────────────────────────────

def extraer(texto=None, datos=None, nombre=""):
    """Devuelve {'referencias': [...], 'origen': str, 'aviso': str, 'paginas': str}."""
    nombre = (nombre or "").lower()
    aviso = ""
    if datos is not None:
        if datos[:5] == b"%PDF-" or nombre.endswith(".pdf"):
            completo, leidas, total = texto_de_pdf(datos)
            seccion, hallada = seccion_referencias(completo)
            if not hallada:
                aviso = ("No se encontró un encabezado de «Referencias» o «Bibliografía» en el PDF. "
                         "Se analizó el documento completo, revisá la lista con atención.")
            return {"referencias": [analizar(r, alt) for r, alt in separar_referencias(seccion, de_pdf=True)],
                    "origen": "pdf", "aviso": aviso,
                    "paginas": f"{leidas} de {total}"}
        try:
            texto = datos.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = datos.decode("latin-1", errors="replace")
    texto = texto or ""
    if nombre.endswith(".ris") or re.search(r"^TY\s{1,2}-\s", texto, re.M):
        return {"referencias": parse_ris(texto), "origen": "ris", "aviso": ""}
    if nombre.endswith((".bib", ".bibtex")) or re.search(r"^\s*@\w+\s*\{", texto, re.M):
        return {"referencias": parse_bibtex(texto), "origen": "bibtex", "aviso": ""}
    seccion, _ = seccion_referencias(texto)
    return {"referencias": [analizar(r, alt) for r, alt in separar_referencias(seccion)],
            "origen": "texto", "aviso": ""}
