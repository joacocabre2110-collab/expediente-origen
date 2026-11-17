from pathlib import Path

import pytest

from canal.miniatura import GeneradorMiniaturaHTML, texto_miniatura
from canal.pipeline.etapas import ContextoVideo, Guion, Render, ResultadoQA, Tema


class PaginaFalsa:
    def __init__(self, texto_desborda=False):
        self.texto_desborda = texto_desborda
        self.documento = ""

    async def set_content(self, documento):
        self.documento = documento

    async def evaluate(self, script):
        if "document.fonts.ready" in script:
            return None
        return {"scroll": 751 if self.texto_desborda else 700, "client": 730,
                "scrollHeight": 300, "clientHeight": 340,
                "left": 54, "right": 784, "top": 115, "bottom": 455}

    async def screenshot(self, path, type):
        assert type == "png"
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 +
                              (1280).to_bytes(4, "big") + (720).to_bytes(4, "big") + b"x")

    async def close(self):
        pass


class NavegadorFalso:
    def __init__(self, texto_desborda=False):
        self.page = PaginaFalsa(texto_desborda)

    async def new_page(self, **kwargs):
        assert kwargs["viewport"] == {"width": 1280, "height": 720}
        return self.page


def datos(tmp_path, key="video-01"):
    contexto = ContextoVideo(key, "largo", "2026-11-07", tmp_path)
    tema = Tema("Theia y el origen de la Luna", "01", "espacio", [])
    guion = Guion("", "¿Qué chocó con la Tierra?", "El impacto formó la Luna", "", "espacio")
    return contexto, tema, guion, Render(tmp_path / "video.mp4", 0), ResultadoQA(True, [])


def test_texto_miniatura_extrae_palabras_de_fuente_y_limita_cantidad():
    contexto, tema, guion, _, _ = datos(Path("."))
    texto = texto_miniatura(tema, guion)
    assert 2 <= len(texto.split()) <= 4
    assert all(palabra.casefold() in (tema.titulo + " " + guion.gancho + " " + guion.intro).casefold()
               for palabra in texto.split())


def test_genera_png_con_dimensiones_y_escapa_texto(tmp_path):
    datos_video = list(datos(tmp_path))
    datos_video[1] = Tema('<script>alert("x")</script> Luna choque', "01", "espacio", [])
    browser = NavegadorFalso()
    miniatura = GeneradorMiniaturaHTML(browser=browser, ruta_sticker=tmp_path / "ausente.png").generar(*datos_video)
    assert miniatura.ruta.name == "miniatura.png"
    assert miniatura.ruta.read_bytes()[16:24] == (1280).to_bytes(4, "big") + (720).to_bytes(4, "big")
    assert "<script>" not in browser.page.documento
    assert "ALERT" in browser.page.documento
    assert "<script>alert" not in browser.page.documento


def test_seed_cambia_diseno_y_desborde_falla(tmp_path):
    c1, tema, guion, render, qa = datos(tmp_path, "uno")
    c2, *_ = datos(tmp_path, "dos")
    a = NavegadorFalso()
    b = NavegadorFalso()
    GeneradorMiniaturaHTML(a).generar(c1, tema, guion, render, qa)
    GeneradorMiniaturaHTML(b).generar(c2, tema, guion, render, qa)
    assert a.page.documento != b.page.documento
    with pytest.raises(ValueError, match="desborda"):
        GeneradorMiniaturaHTML(NavegadorFalso(texto_desborda=True)).generar(c1, tema, guion, render, qa)


def test_rechaza_png_mayor_a_dos_mb(tmp_path):
    class Grande(PaginaFalsa):
        async def screenshot(self, path, type):
            super().screenshot  # fixture funcional: escribir un PNG nominal grande
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 +
                                   (1280).to_bytes(4, "big") + (720).to_bytes(4, "big") + b"x" * (2 * 1024 * 1024))

    class BrowserGrande(NavegadorFalso):
        def __init__(self):
            self.page = Grande()

    with pytest.raises(ValueError, match="2 MB"):
        GeneradorMiniaturaHTML(BrowserGrande()).generar(*datos(tmp_path))
