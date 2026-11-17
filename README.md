# Verificador Bibliográfico

Comprueba si las referencias de un trabajo corresponden a publicaciones
reales. Forma parte de la serie Bibliotecolog_IA junto con Biblioteca Virtual,
Clasificación Documental Total y Referencias Bibliográficas.

**© 2026 Gabriel Da Costa Porto Luzardo · Software libre bajo licencia
[GNU GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.es.html).**

## Qué hace

0. **Estado de las bases**: al abrir la página se comprueba cada fuente con un
   registro conocido. De paso despierta el servidor de Render si estaba en
   reposo. Mientras alguien usa la página, el navegador avisa al servidor cada
   10 minutos para que no vuelva a dormirse.
1. **Carga**: se arrastra un PDF, un archivo BibTeX (`.bib`) o RIS (`.ris`),
   se pega la lista de referencias o se cargan de a una. En un PDF se busca la
   sección «Referencias» o «Bibliografía» leyendo desde la última página hacia
   atrás.
2. **Revisión**: muestra las referencias detectadas para corregirlas, unirlas,
   quitarlas o agregar otras antes de verificar. La separación se hace con
   reglas, sin inteligencia artificial.
3. **Verificación** de cada referencia, en este orden:
   - **El enlace citado.** Si hay DOI se consulta en Crossref, OpenAlex y
     DataCite y se comparan título, autores y año. Si hay una dirección web
     se abre la página y se compara su título (si el enlace quedó cortado con
     un guion de fin de línea, se prueba también sin él). Si está caída se
     busca una copia en Internet Archive.
   - **Las bases de datos.** Si el enlace no alcanza, se busca el trabajo por
     título y autor en Crossref, OpenAlex, PubMed, DOAJ, OpenAIRE y Open
     Library (y Semantic Scholar si hay clave), todas a la vez.
4. **Resultado** por referencia: Verificada, Con observaciones, No encontrada,
   Retractada o Sin comprobar, con el registro hallado, las diferencias y
   enlaces para buscarla a mano. Barra de avance con tiempo restante,
   reintento automático si el servidor no responde y exportación (también
   parcial) a HTML, CSV o texto.

Los archivos se analizan en memoria y no se guardan.

## Uso local

```
pip install -r requirements.txt
python app.py
```

Abrí `http://127.0.0.1:5000` en el navegador.

## Despliegue en Render

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --workers 1 --threads 8 --timeout 120`

Variables de entorno, todas opcionales:

| Variable | Para qué sirve |
|---|---|
| `CONTACT_EMAIL` | Correo de contacto que se envía a Crossref, OpenAlex y NCBI. Da acceso a su servicio preferente, más rápido y estable. |
| `S2_API_KEY` | Clave gratuita de Semantic Scholar. Sin ella esa base no se consulta, porque el cupo público compartido casi nunca responde desde Render. |
| `NCBI_API_KEY` | Clave gratuita de NCBI. Sube el límite de consultas a PubMed. |

El panel «Estado de las bases», arriba de todo, consulta cada fuente con un
registro conocido (`/api/fuentes`). `/api/ping` responde al instante y sirve
para despertar el servidor.

## Estructura

```
app.py             Servidor Flask y rutas de la API
extraccion.py      PDF, texto, BibTeX y RIS → lista de referencias analizadas
verificacion.py    Enlace citado, búsqueda en bases, comparación y dictamen
templates/         Página única
static/            Estilos y lógica de la interfaz
tests/             Pruebas sin red (python tests/test_verificacion.py)
```

## Límites conocidos

- Las bases cubren sobre todo artículos. Un libro, una tesis o un informe
  pueden existir y figurar como «No encontrada» (o «Con observaciones» si el
  enlace citado está caído).
- Un PDF escaneado sin texto seleccionable no se puede leer.
- Bibliografías sin autor al comienzo de cada entrada pueden quedar mal
  separadas. Para eso está el paso de revisión.
- El resultado es una ayuda para la revisión y no un dictamen definitivo.
