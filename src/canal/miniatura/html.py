"""Miniaturas 1280×720 compuestas en HTML y capturadas con Playwright."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import re
from pathlib import Path
import os
from typing import Any

from canal.pipeline.etapas import ContextoVideo, Guion, Miniatura, Render, ResultadoQA, Tema
from canal.render.motor import planet, starfield

ANCHO, ALTO = 1280, 720
MAX_BYTES = 2 * 1024 * 1024
_STOP = {
    "a", "al", "algo", "con", "de", "del", "desde", "el", "ella", "en", "entre", "era",
    "es", "esta", "este", "la", "las", "lo", "los", "más", "mientras", "no", "o", "para",
    "por", "que", "se", "sobre", "su", "un", "una", "y", "como", "cuando", "hacia",
}


def texto_miniatura(tema: Tema, guion: Guion) -> str:
    """Extrae hasta cuatro palabras con contenido presentes literalmente en tema/guion."""
    fuente = f"{tema.titulo} {guion.gancho} {guion.intro}"
    palabras = re.findall(r"[\wÁÉÍÓÚÜÑáéíóúüñ]+", fuente, flags=re.UNICODE)
    elegidas: list[str] = []
    vistos: set[str] = set()
    for palabra in palabras:
        clave = palabra.casefold()
        if len(palabra) < 3 or clave in _STOP or clave in vistos:
            continue
        vistos.add(clave)
        elegidas.append(palabra)
        if len(elegidas) == 4:
            break
    # En títulos mínimos conservamos dos palabras textuales sin añadir información.
    if len(elegidas) < 2:
        for palabra in palabras:
            if palabra.casefold() not in vistos:
                elegidas.append(palabra)
                vistos.add(palabra.casefold())
                if len(elegidas) == 2:
                    break
    return " ".join(elegidas[:4]).upper()


class GeneradorMiniaturaHTML:
    """Genera una miniatura PNG. ``browser`` permite inyectar un navegador falso."""

    def __init__(self, browser: Any = None, ruta_sticker: str | Path | None = None) -> None:
        self.browser = browser
        self.ruta_sticker = Path(ruta_sticker) if ruta_sticker else (
            Path(os.environ.get("CANAL_ASSETS_DIR", Path(__file__).resolve().parents[3] / "assets/original/canal_youtube")) / "imagenes/avatar_recorte_cara.png"
        )

    def generar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                render: Render, qa: ResultadoQA) -> Miniatura:
        del render, qa
        salida = Path(contexto.directorio_trabajo) / "miniatura.png"
        salida.parent.mkdir(parents=True, exist_ok=True)
        texto = texto_miniatura(tema, guion)
        seed = int.from_bytes(hashlib.sha256(contexto.video_key.encode("utf-8")).digest()[:4], "big")
        sticker = ""
        if self.ruta_sticker.is_file():
            data = base64.b64encode(self.ruta_sticker.read_bytes()).decode("ascii")
            sticker = f'<img alt="" src="data:image/png;base64,{data}">'
        safe_title = html.escape(texto)
        safe_tag = html.escape(f"{tema.pilar} · EXPEDIENTE {contexto.video_key}")
        html_doc = _documento(safe_title, safe_tag, sticker, seed)
        asyncio.run(self._capturar(html_doc, salida))
        raw = salida.read_bytes()
        if len(raw) > MAX_BYTES:
            salida.unlink(missing_ok=True)
            raise ValueError("La miniatura supera 2 MB")
        if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
            salida.unlink(missing_ok=True)
            raise ValueError("Playwright no produjo un PNG válido")
        ancho = int.from_bytes(raw[16:20], "big")
        alto = int.from_bytes(raw[20:24], "big")
        if (ancho, alto) != (ANCHO, ALTO):
            salida.unlink(missing_ok=True)
            raise ValueError(f"Dimensiones PNG inválidas: {ancho}x{alto}")
        return Miniatura(salida, 0.0)

    async def _capturar(self, documento: str, salida: Path) -> None:
        if self.browser is not None:
            await _pagina(self.browser, documento, salida)
            return
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                await _pagina(browser, documento, salida)
            finally:
                await browser.close()


async def _pagina(browser: Any, documento: str, salida: Path) -> None:
    page = await browser.new_page(viewport={"width": ANCHO, "height": ALTO}, device_scale_factor=1)
    try:
        await page.set_content(documento)
        await page.evaluate("document.fonts.ready")
        medidas = await page.evaluate("""() => {
          const e = document.querySelector('.titulo');
          const r = e.getBoundingClientRect();
          return {scroll: e.scrollWidth, client: e.clientWidth,
            scrollHeight: e.scrollHeight, clientHeight: e.clientHeight,
            left:r.left, right:r.right, top:r.top, bottom:r.bottom};
        }""")
        if (medidas["scroll"] > medidas["client"] + 1 or medidas["scrollHeight"] > medidas["clientHeight"] + 1 or medidas["left"] < 0 or
                medidas["right"] > ANCHO or medidas["top"] < 0 or medidas["bottom"] > ALTO):
            raise ValueError("El texto de la miniatura desborda su caja")
        await page.screenshot(path=str(salida), type="png")
    finally:
        close = getattr(page, "close", None)
        if close:
            await close()


def _documento(titulo: str, etiqueta: str, sticker: str, seed: int) -> str:
    # Acentúa una palabra estable con el seed, manteniendo el texto enteramente escapado.
    palabras = titulo.split(" ")
    if len(palabras) > 1:
        idx = seed % len(palabras)
        palabras[idx] = f'<span class="ambar">{palabras[idx]}</span>'
    titulo_html = " ".join(palabras)
    fondo = starfield(ANCHO, ALTO, n=180, seed=seed)
    esfera = planet(925, 355, 235, "#fff3ce", "#99948c", "#34313a", seed=seed)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}html,body{{margin:0;width:{ANCHO}px;height:{ALTO}px;overflow:hidden;background:#03040a;color:#f3efe6;font-family:Inter,Arial,sans-serif}}.abs{{position:absolute}}.bg{{position:absolute;inset:-10%;background:radial-gradient(ellipse at 60% 40%,#141d3a 0%,#070912 55%,#020308 100%)}}
.fondo{{position:absolute;inset:0;background:radial-gradient(ellipse at 72% 44%,#141d3a 0%,#070912 54%,#020308 100%)}}
.titulo{{position:absolute;z-index:3;left:54px;top:115px;width:730px;height:340px;overflow:hidden;font-size:92px;line-height:.98;font-weight:900;letter-spacing:-3px;text-transform:uppercase;text-shadow:0 6px 0 #000,0 0 30px #000}}
.ambar{{color:#ffb547}}.etiqueta{{position:absolute;z-index:4;left:58px;bottom:60px;max-width:850px;background:#ffb547;color:#120a00;padding:12px 20px;border-radius:8px;font-size:25px;font-weight:800;letter-spacing:.05em;text-transform:uppercase}}
.sticker{{position:absolute;z-index:4;right:42px;bottom:34px;width:190px;height:190px;border:7px solid #ffb547;border-radius:50%;overflow:hidden;background:#17192a;box-shadow:0 8px 34px #000}}
.sticker img{{width:100%;height:100%;object-fit:cover;image-rendering:pixelated}}.brillo{{position:absolute;inset:0;background:radial-gradient(circle at 72% 48%,transparent 40%,rgba(0,0,0,.65) 100%);pointer-events:none}}
</style></head><body><div class="fondo"></div>{fondo}{esfera}<div class="titulo">{titulo_html}</div><div class="etiqueta">{etiqueta}</div><div class="sticker">{sticker}</div><div class="brillo"></div></body></html>"""
