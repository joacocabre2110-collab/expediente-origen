import json
import urllib.error
import urllib.parse

from canal.investigacion.imagenes import ClienteImagenes, ImagenLibre, creditos


class Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.data


def item(name, license, width=1200, ext="jpg", url=None):
    file_title = f"File:{name}.{ext}"
    return {"title": file_title, "imageinfo": [{
        "url": url or f"https://upload.wikimedia.org/{name}.{ext}",
        "thumburl": url or f"https://upload.wikimedia.org/{name}.{ext}",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/{file_title}",
        "width": width, "height": 900,
        "extmetadata": {"LicenseShortName": {"value": license}, "Artist": {"value": "Ana"},
                        "ObjectName": {"value": name}},
    }]}


def test_buscar_filtra_licencias_y_formatos_y_envia_parametros():
    payload = {"query": {"pages": [item("libre", "CC BY-SA 4.0"), item("zero", "CC0"),
        item("dominio", "Public domain"), item("nc", "CC BY-NC"), item("nd", "CC BY-ND"),
        item("sin", ""), item("pequena", "CC BY", 799), item("vector", "CC BY", ext="svg"),
        item("pdf", "CC BY", ext="pdf")]}}
    calls = []
    def abrir(req, timeout):
        calls.append(req)
        return Response(json.dumps(payload).encode())
    imgs = ClienteImagenes(abrir=abrir).buscar("tema")
    assert [i.titulo for i in imgs] == ["libre", "zero", "dominio"]
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(calls[0].full_url).query)
    assert parsed["generator"] == ["search"] and parsed["gsrnamespace"] == ["6"]
    assert parsed["iiurlwidth"] == ["1600"]
    assert calls[0].get_header("User-agent") == "ExpedienteOrigenBot/1.0"


def test_buscar_para_tema_deduplica_descarga_y_respeta_maximo(tmp_path):
    a = ImagenLibre("https://img/a.jpg", "A", "Ana", "CC BY", "https://src/a", 900, 700)
    b = ImagenLibre("https://img/b.png", "B", "Bea", "CC0", "https://src/b", 900, 700)
    class Buscador(ClienteImagenes):
        def buscar(self, consulta, max_resultados=6):
            return [a] if consulta == "Titulo" else [a, b]
    def abrir(req, timeout): return Response(b"bytes:" + req.full_url.encode())
    c = Buscador(abrir=abrir)
    imgs = c.buscar_para_tema("Titulo", "Alias", tmp_path, minimo=1, maximo=2)
    assert len(imgs) == 2 and all(__import__("pathlib").Path(i.url_local).is_file() for i in imgs)
    assert len({i.url_local for i in imgs}) == 2


def test_busca_consultas_extra_y_prioriza_resolucion(tmp_path):
    imgs = [
        ImagenLibre("https://img/low.jpg", "Baja", "A", "CC BY", "src", 900, 800),
        ImagenLibre("https://img/high.jpg", "Alta", "A", "CC BY", "src", 3000, 2000),
    ]
    class Buscador(ClienteImagenes):
        def __init__(self):
            super().__init__(abrir=lambda req, timeout: Response(b"ok"))
            self.consultas = []
        def buscar(self, consulta, max_resultados=6):
            self.consultas.append(consulta)
            return imgs if consulta == "Tema photograph" else [imgs[0]]
    c = Buscador()
    result = c.buscar_para_tema("Tema", ["Alias"], tmp_path, maximo=2, caso_id="caso_id")
    assert c.consultas[:2] == ["Tema", "Alias"]
    assert {"caso id", "caso_id", "Tema map", "Tema photograph"}.issubset(c.consultas)
    assert [i.titulo for i in result] == ["Alta", "Baja"]


def test_429_retry_after_y_creditos(tmp_path):
    calls, waits = [], []
    def abrir(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "busy", {"Retry-After": "7"}, None)
        return Response(b"ok")
    c = ClienteImagenes(abrir=abrir, sleep=waits.append)
    img = ImagenLibre("https://img/a.jpg", "Título", "Autora", "CC BY-SA 4.0", "https://src/a", 900, 700)
    assert c.descargar(img, tmp_path).read_bytes() == b"ok"
    assert waits == [7]
    assert creditos([img]) == "Imágenes: Título — Autora — CC BY-SA 4.0 — https://src/a"


def test_creditos_sin_html():
    from canal.investigacion.imagenes import creditos, ImagenLibre
    img = ImagenLibre("x.jpg", "Foto <b>x</b>", "<ul><li>Ana</li><li>derivative work: <a href=\"//c\">Beto</a></li></ul>", "CC BY 4.0", "https://c/x", 900, 600)
    out = creditos([img])
    assert "<" not in out and ">" not in out and "Ana" in out and "Beto" in out
