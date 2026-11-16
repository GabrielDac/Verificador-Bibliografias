# Verificador de Bibliografías — © 2026 Gabriel Da Costa Porto Luzardo — GPL-3.0
"""Servidor Flask.

  /                  Página única
  /api/extraer       PDF, BibTeX, RIS o texto pegado → lista de referencias
  /api/verificar     Una referencia → dictamen (enlace primero, luego bases)
  /api/fuentes       Estado de las bases consultadas
"""

import os

from flask import Flask, jsonify, render_template, request

import extraccion
import verificacion

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024      # 25 MB por archivo
app.json.ensure_ascii = False

MAX_TEXTO = 400_000       # caracteres de texto pegado
MAX_CITA = 2_500          # caracteres por referencia


@app.route("/")
def inicio():
    return render_template("index.html", fuentes=verificacion.FUENTES)


@app.errorhandler(413)
def muy_grande(_e):
    return jsonify(error="El archivo supera los 25 MB."), 413


@app.post("/api/extraer")
def api_extraer():
    try:
        if "archivo" in request.files:
            f = request.files["archivo"]
            datos = f.read()
            if not datos:
                return jsonify(error="El archivo está vacío."), 400
            res = extraccion.extraer(datos=datos, nombre=f.filename or "")
        else:
            cuerpo = request.get_json(silent=True) or {}
            texto = (cuerpo.get("texto") or "")[:MAX_TEXTO]
            if not texto.strip():
                return jsonify(error="No hay texto para analizar."), 400
            res = extraccion.extraer(texto=texto)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        return jsonify(error="No se pudo procesar el contenido."), 500
    if not res["referencias"]:
        return jsonify(error="No se reconoció ninguna referencia. Probá pegando solo la lista de referencias."), 422
    return jsonify(res)


@app.post("/api/verificar")
def api_verificar():
    cuerpo = request.get_json(silent=True) or {}
    raw = (cuerpo.get("raw") or "").strip()[:MAX_CITA]
    if len(raw) < 15:
        return jsonify(error="La referencia es demasiado corta."), 400
    if cuerpo.get("estructurada") and cuerpo.get("titulo"):
        # Viene de BibTeX o RIS: los campos ya están identificados.
        ref = {"raw": raw,
               "doi": extraccion.limpiar_doi(str(cuerpo.get("doi") or ""))[:200],
               "url": str(cuerpo.get("url") or "")[:600],
               "anio": str(cuerpo.get("anio") or "")[:4],
               "autor": str(cuerpo.get("autor") or "")[:120],
               "titulo": str(cuerpo.get("titulo") or "")[:500]}
    else:
        ref = extraccion.analizar(raw)
    try:
        res = verificacion.verificar(ref)
    except Exception:
        return jsonify(error="Falló la verificación de esta referencia."), 500
    res["analisis"] = {k: ref.get(k, "") for k in ("doi", "url", "anio", "autor", "titulo")}
    return jsonify(res)


@app.get("/api/fuentes")
def api_fuentes():
    return jsonify(verificacion.salud())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
