import json
import urllib.error

import pytest

from canal.investigacion.wikipedia import ClienteWikipedia, ErrorWikipedia
from canal.investigacion.brief import BriefInsuficiente, construir_brief
from canal.pipeline.etapas import Tema


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.payload).encode()


def test_wikipedia_search_extract_and_user_agent():
    requests = []
    def abrir(req, timeout):
        requests.append((req, timeout))
        if "list%22%3A+%22search" in req.full_url or "list=search" in req.full_url:
            return Response({"query": {"search": [{"title": "Caso"}]}})
        return Response({"query": {"pages": [{"title": "Caso", "extract": "Texto completo."}]}})
    wiki = ClienteWikipedia(abrir=abrir, pausa_min_s=0, idiomas=("es",))
    assert wiki.buscar("caso")[0].titulo == "Caso"
    assert wiki.extracto("Caso").texto == "Texto completo."
    assert all(r[0].get_header("User-agent") == "ExpedienteOrigenBot/0.1 (documentary research; personal project)" and r[1] == 15 for r in requests)


def test_wikipedia_retries_rate_limit():
    calls, waits = [], []
    def abrir(req, timeout):
        calls.append(req)
        if len(calls) == 1: raise urllib.error.HTTPError(req.full_url, 429, "busy", {"Retry-After": "31", "x-envoy-ratelimited": "true"}, None)
        return Response({"query": {"search": []}})
    wiki = ClienteWikipedia(abrir=abrir, pausa_min_s=0, idiomas=("es",), sleep=waits.append)
    assert wiki.buscar("x") == []
    assert waits == [31]


def test_wikipedia_retry_after_is_capped_and_exhaustion_is_clear():
    calls, waits = [], []
    def abrir(req, timeout):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {"Retry-After": "999"}, None)
    wiki = ClienteWikipedia(abrir=abrir, pausa_min_s=0, idiomas=("es",), sleep=waits.append,
                            reintentos=2, retry_after_max_s=120)
    with pytest.raises(ErrorWikipedia, match="HTTP 503"):
        wiki.buscar("x")
    assert len(calls) == 3
    assert waits == [120, 120]


def test_wikipedia_does_not_retry_404():
    calls = []
    def abrir(req, timeout):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 404, "missing", {}, None)
    wiki = ClienteWikipedia(abrir=abrir, pausa_min_s=0, idiomas=("es",), sleep=lambda _: None)
    with pytest.raises(ErrorWikipedia, match="HTTP 404"):
        wiki.buscar("x")
    assert len(calls) == 1


def test_brief_splits_deduplicates_and_fails_if_insufficient():
    class Wiki:
        def buscar(self, consulta, idioma=None): return [type("H", (), {"idioma":"es", "titulo":"Caso"})()]
        def extracto(self, titulo, idioma):
            return type("F", (), {"texto": "Uno. Dos. Tres. Cuatro. Cinco. Seis. Siete. Ocho.", "url":"https://es.wikipedia.org/wiki/Caso", "titulo":titulo})()
    with pytest.raises(BriefInsuficiente):
        construir_brief(Tema("Caso", "c1", "tierra", ["Caso"]), Wiki(), max_fragmentos=8, min_fragmentos=2)


class WikiFalsa:
    idiomas = ("es", "en")
    def __init__(self, resultados): self.resultados = resultados; self.consultas = []
    def buscar(self, consulta, idioma=None):
        self.consultas.append((consulta, idioma))
        return [type("H", (), {"idioma": idioma, "titulo": t})() for t in self.resultados.get((consulta, idioma), [])]
    def extracto(self, titulo, idioma):
        texto = (titulo + " documenta el incidente y sus antecedentes. ") * 12
        return type("F", (), {"texto": texto, "url": f"https://{idioma}.wikipedia.org/wiki/{titulo}", "titulo": titulo})()


def tema_varginha():
    return Tema("Expediente 1: El Incidente Varginha: El Encuentro Biológico en Brasil",
                "incidente-varginha-1996", "sobrenatural",
                ["El Roswell Brasileño", "Caso Varginha", "Incidente de Varginha"])


def test_brief_prefiere_articulo_relevante_a_resultado_fecha():
    wiki = WikiFalsa({("El Roswell Brasileño", "es"): ["2 de julio", "Incidente de Varginha"],
                      ("El Roswell Brasileño", "en"): []})
    brief = construir_brief(tema_varginha(), wiki, max_fragmentos=4, min_fragmentos=1)
    assert brief.fragmentos[0].fuente_titulo == "Incidente de Varginha"


def test_brief_descarta_resultado_fecha_y_falla_sin_articulo_relevante():
    wiki = WikiFalsa({("El Roswell Brasileño", "es"): ["2 de julio"]})
    with pytest.raises(BriefInsuficiente):
        construir_brief(tema_varginha(), wiki, max_fragmentos=4, min_fragmentos=1)


def test_brief_limpia_titulo_para_consultas():
    wiki = WikiFalsa({})
    with pytest.raises(BriefInsuficiente):
        construir_brief(tema_varginha(), wiki, max_fragmentos=4, min_fragmentos=1)
    assert ("El Incidente Varginha", "es") in wiki.consultas
    assert not any("Expediente" in consulta for consulta, _ in wiki.consultas)
