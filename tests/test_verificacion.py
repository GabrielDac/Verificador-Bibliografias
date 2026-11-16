"""Pruebas del motor con respuestas simuladas de las bases (sin red)."""
import sys, os, re, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import verificacion as v
from extraccion import analizar

CR_LECUN = {"DOI": "10.1038/nature14539", "title": ["Deep learning"], "container-title": ["Nature"],
            "author": [{"family": "LeCun", "given": "Yann"}, {"family": "Bengio", "given": "Yoshua"}, {"family": "Hinton", "given": "Geoffrey"}],
            "issued": {"date-parts": [[2015, 5, 27]]}}
CR_OTRO = {"DOI": "10.1016/j.cell.2019.01.001", "title": ["A completely different paper about cell biology"],
           "author": [{"family": "Wong", "given": "A"}], "issued": {"date-parts": [[2019]]}, "container-title": ["Cell"]}
CR_VASWANI = {"DOI": "10.5555/3295222.3295349", "title": ["Attention is all you need"],
              "author": [{"family": "Vaswani", "given": "Ashish"}, {"family": "Shazeer", "given": "Noam"}],
              "issued": {"date-parts": [[2017]]}, "container-title": ["NIPS"]}
CR_RETR = {"DOI": "10.1016/S0140-6736(97)11096-0", "title": ["RETRACTED: Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children"],
           "author": [{"family": "Wakefield", "given": "AJ"}], "issued": {"date-parts": [[1998]]}, "container-title": ["The Lancet"],
           "updated-by": [{"type": "retraction", "DOI": "10.1016/x"}]}
OA_GP = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.14201/eks.31279",
         "display_name": "La percepción de la Inteligencia Artificial en contextos educativos tras el lanzamiento de ChatGPT: disrupción o pánico",
         "publication_year": 2023, "is_retracted": False,
         "authorships": [{"author": {"display_name": "Francisco José García‐Peñalvo"}}],
         "primary_location": {"source": {"display_name": "Education in the Knowledge Society"}}}

caidas = set()

def falso_http_json(url, timeout=9, headers=None):
    u = urllib.parse.unquote_plus(url)
    for c in caidas:
        if c in u:
            return 0, None
    if "api.crossref.org/works/" in u:
        if "10.1038/nature14539" in u: return 200, {"message": CR_LECUN}
        if "10.1016/j.cell.2019.01.001" in u: return 200, {"message": CR_OTRO}
        if "S0140-6736(97)11096-0" in u: return 200, {"message": CR_RETR}
        return 404, None
    if "api.crossref.org/works?" in u:
        q = u.lower()
        items = []
        if "attention is all you need" in q: items = [CR_OTRO, CR_VASWANI]
        if "deep learning" in q: items = [CR_LECUN]
        if "ileal" in q: items = [CR_RETR]
        return 200, {"message": {"items": items}}
    if "api.openalex.org/works/" in u:
        return 404, None
    if "api.openalex.org/works?" in u:
        return 200, {"results": [OA_GP] if "percepci" in u else []}
    if "semanticscholar" in u: return 429, None
    if "esearch" in u: return 200, {"esearchresult": {"idlist": []}}
    if "doaj.org" in u: return 200, {"results": []}
    if "openlibrary" in u:
        if "Ficciones" in u:
            return 200, {"docs": [{"key": "/works/OL1W", "title": "Ficciones", "author_name": ["Jorge Luis Borges"],
                                   "first_publish_year": 1944, "publish_year": [1944, 1956, 1997]}]}
        return 200, {"docs": []}
    if "api.datacite.org" in u: return 404, None
    if "doi.org/api/handles" in u: return 404, {"responseCode": 100}
    if "archive.org" in u: return 200, {"archived_snapshots": {"closest": {"available": True, "url": "http://web.archive.org/web/2020/http://x"}}}
    return 0, None

def falsa_pagina(url):
    if "viva" in url:
        return {"estado": "viva", "codigo": 200, "url_final": url, "tipo": "text/html",
                "texto": '<html><head><meta name="citation_title" content="Informe mundial sobre el envejecimiento y la salud"><title>OMS</title></head></html>'}
    if "muda" in url:
        return {"estado": "viva", "codigo": 200, "url_final": url, "tipo": "text/html", "texto": "<title>Inicio</title>"}
    return {"estado": "caida", "codigo": 404, "detalle": "la página devuelve error 404"}

v.http_json = falso_http_json
v.abrir_pagina = falsa_pagina

CASOS = [
 ("DOI correcto", "LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436–444. https://doi.org/10.1038/nature14539", "verificada"),
 ("DOI de otro trabajo, artículo real", "Vaswani, A., Shazeer, N. (2017). Attention is all you need. Advances in Neural Information Processing Systems, 30. https://doi.org/10.1016/j.cell.2019.01.001", "observaciones"),
 ("Sin enlace, se halla por título", "Vaswani, A., Shazeer, N., Parmar, N. (2017). Attention is all you need. Advances in Neural Information Processing Systems, 30, 5998–6008.", "verificada"),
 ("Autores inventados sobre título real", "Fernández, R., & Olivera, T. (2017). Attention is all you need. Revista X, 3, 1-9.", "observaciones"),
 ("Año muy distinto", "Vaswani, A., Shazeer, N. (2009). Attention is all you need. NIPS.", "observaciones"),
 ("Inventada con DOI inexistente", "Pérez, J. M., y Rodríguez, L. (2021). Bibliotecas cuánticas rioplatenses: un modelo imaginario de catalogación. Revista Inventada de Bibliotecología, 12(3), 45–67. https://doi.org/10.9999/rib.2021.123", "no_encontrada"),
 ("Inventada sin enlace", "Smith AB, Jones CD. Imaginary outcomes of a study that does not exist. J Nonexistent Med. 2019;4(2):11-9.", "no_encontrada"),
 ("Solo en OpenAlex, apellido compuesto", "García-Peñalvo, F. J. (2023). La percepción de la Inteligencia Artificial en contextos educativos tras el lanzamiento de ChatGPT: disrupción o pánico. Education in the Knowledge Society, 24, e31279.", "verificada"),
 ("Página viva con título", "Organización Mundial de la Salud. (2020). Informe mundial sobre el envejecimiento y la salud. OMS. https://viva.example.org/informe", "verificada"),
 ("Página viva sin título", "Intendencia de Montevideo. (2022). Plan de bibliotecas barriales. https://muda.example.org/plan", "observaciones"),
 ("Enlace caído, hallada en bases", "Vaswani, A., Shazeer, N. (2017). Attention is all you need. https://caida.example.org/paper.pdf", "verificada"),
 ("Enlace caído, no hallada", "Gómez, P. (2018). Un documento perdido de la web institucional. https://caida.example.org/x", "no_encontrada"),
 ("Libro en Open Library", "Borges, J. L. (1944). Ficciones. Sur.", "verificada"),
 ("Título corto sin autor coincidente", "Martínez, Q. (2020). Deep learning. Editorial Z.", "no_encontrada"),
 ("Retractada", "Wakefield AJ, et al. Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children. Lancet. 1998;351:637-41. doi:10.1016/S0140-6736(97)11096-0", "retractada"),
]

def test_casos():
    fallos = 0
    for nombre, cita, esperado in CASOS:
        r = v.verificar(analizar(cita))
        ok = r["estado"] == esperado
        fallos += not ok
        print(("OK   " if ok else "FALLA"), nombre, "→", r["estado"], "|", r["resumen"])
        for n in r["notas"]: print("        ·", n[:140])
        if r["enlace"]: print("        enlace:", r["enlace"].get("estado"), "-", r["enlace"].get("detalle", "")[:110])
    assert not fallos

def test_bases_caidas():
    caidas.update({"crossref", "openalex", "doaj"})
    r = v.verificar(analizar("Smith AB, Jones CD. Imaginary outcomes of a study that does not exist. J Nonexistent Med. 2019;4(2):11-9."))
    caidas.clear()
    print("Bases caídas →", r["estado"], [f["nombre"] + ":" + f["estado"] for f in r["fuentes"]])
    assert r["estado"] == "sin_comprobar"

if __name__ == "__main__":
    test_casos(); test_bases_caidas(); print("TODO BIEN")
