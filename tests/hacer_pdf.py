"""Genera un PDF de prueba con cuerpo, sección de referencias y anexo."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import muestras
def hacer(ruta):
    st = getSampleStyleSheet()
    fr = ParagraphStyle("fr", parent=st["Normal"], leftIndent=28, firstLineIndent=-28, spaceAfter=6, fontSize=10.5, leading=14)
    d = SimpleDocTemplate(ruta, pagesize=A4)
    f = [Paragraph("Índice", st["Heading2"]), Paragraph("Introducción .... 2", st["Normal"]), Paragraph("Referencias .... 9", st["Normal"]), PageBreak(),
         Paragraph("La inteligencia artificial en las bibliotecas", st["Title"])]
    for i in range(14):
        f.append(Paragraph("Como señalan LeCun et al. (2015), el aprendizaje profundo cambió el campo. " * 6, st["Normal"])); f.append(Spacer(1, 8))
    f.append(Paragraph("Referencias", st["Heading2"]))
    cuerpo = muestras.APA.split("Referencias\n\n")[1].split("\n\nAnexo")[0].replace("Pro-\ncessing", "Processing").replace("item/\n9789241565042", "item/9789241565042").replace("\n12\n", "\n")
    import re
    for ref in re.split(r"\n(?=[A-ZÁÉÍÓÚ][\w\-áéíóúñ ]+[,.] )", cuerpo):
        if ref.strip(): f.append(Paragraph(ref.replace("\n", " ").replace("&", "&amp;"), fr))
    f += [PageBreak(), Paragraph("Anexo 1. Cuestionario", st["Heading2"]), Paragraph("Pregunta uno. ¿Usó la biblioteca en 2020?", st["Normal"])]
    def pie(c, doc):
        c.setFont("Helvetica", 9); c.drawCentredString(A4[0] / 2, 30, str(doc.page))
    d.build(f, onFirstPage=pie, onLaterPages=pie)
if __name__ == "__main__":
    hacer(sys.argv[1])
