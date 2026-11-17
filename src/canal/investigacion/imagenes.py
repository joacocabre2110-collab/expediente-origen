"""Búsqueda y descarga de imágenes con licencias libres desde Wikimedia Commons."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


@dataclass(frozen=True)
class ImagenLibre:
    url_local: str
    titulo: str
    autor: str
    licencia: str
    url_fuente: str
    ancho: int
    alto: int


class ErrorImagenes(RuntimeError):
    pass


class ClienteImagenes:
    API = "https://commons.wikimedia.org/w/api.php"
    USER_AGENT = "ExpedienteOrigenBot/1.0"

    def __init__(self, abrir=urllib.request.urlopen, sleep=time.sleep, reintentos=3,
                 retry_after_max_s=120, jitter=None):
        if reintentos < 0 or retry_after_max_s < 0:
            raise ValueError("reintentos y retry_after_max_s no pueden ser negativos")
        self.abrir, self.sleep = abrir, sleep
        self.reintentos, self.retry_after_max_s = reintentos, retry_after_max_s
        self.jitter = jitter or (lambda techo: random.uniform(0, techo))

    def _solicitar(self, url, accept="application/json"):
        for intento in range(self.reintentos + 1):
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT, "Accept": accept})
            try:
                with self.abrir(req, timeout=15) as respuesta:
                    return respuesta.read()
            except urllib.error.HTTPError as e:
                if not (e.code == 429 or 500 <= e.code <= 599) or intento >= self.reintentos:
                    raise ErrorImagenes(f"Wikimedia Commons respondió HTTP {e.code}") from None
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if retry_after is not None:
                    try:
                        espera = min(self.retry_after_max_s, max(0.0, float(retry_after)))
                    except (TypeError, ValueError):
                        espera = min(8, 2 ** intento) + self.jitter(1.0)
                else:
                    espera = min(8, 2 ** intento) + self.jitter(1.0)
                self.sleep(espera)
            except (TimeoutError, urllib.error.URLError) as e:
                if isinstance(e, urllib.error.URLError) and not isinstance(e.reason, TimeoutError):
                    raise ErrorImagenes("No se pudo conectar con Wikimedia Commons") from None
                if intento >= self.reintentos:
                    raise ErrorImagenes("Wikimedia Commons agotó los reintentos de conexión/timeout") from None
                self.sleep(min(8, 2 ** intento) + self.jitter(1.0))
        raise ErrorImagenes("Solicitud agotó reintentos")

    @staticmethod
    def _texto(meta, campo, defecto=""):
        valor = meta.get(campo, {}) if meta else {}
        return str(valor.get("value", defecto)).strip() if isinstance(valor, dict) else str(valor).strip()

    @staticmethod
    def _licencia_libre(licencia):
        s = licencia.casefold()
        if any(x in s for x in ("nc", "nd", "noncommercial", "non-commercial", "noderivatives", "no derivatives", "fair use")):
            return False
        return ("public domain" in s or "cc0" in s or "creative commons zero" in s or
                bool(re.search(r"\bcc\s*(?:by|attribution)(?:\s*[- ]?sa|\s*[- ]?share alike)?\b", s)) or
                "cc-by" in s or "cc-by-sa" in s or "cc by-sa" in s)

    def buscar(self, consulta: str, max_resultados=6) -> list[ImagenLibre]:
        params = {"action": "query", "generator": "search", "gsrsearch": consulta,
                  "gsrnamespace": 6, "gsrlimit": max(0, min(50, int(max_resultados))),
                  "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1600,
                  "format": "json", "formatversion": 2}
        url = self.API + "?" + urllib.parse.urlencode(params)
        try:
            payload = json.loads(self._solicitar(url).decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ErrorImagenes("Respuesta JSON inválida de Wikimedia Commons") from None
        encontrados = payload.get("query", {}).get("pages", [])
        if isinstance(encontrados, dict):
            encontrados = list(encontrados.values())
        imagenes = []
        for page in encontrados:
            infos = page.get("imageinfo", [])
            if not infos:
                continue
            info = infos[0]
            url_imagen = info.get("thumburl") or info.get("url", "")
            extension = Path(urllib.parse.urlparse(url_imagen).path).suffix.lower()
            ancho, alto = info.get("width", 0), info.get("height", 0)
            if extension not in (".jpg", ".jpeg", ".png", ".webp") or ancho < 800:
                continue
            meta = info.get("extmetadata", {})
            licencia = self._texto(meta, "LicenseShortName")
            if not self._licencia_libre(licencia):
                continue
            titulo = self._texto(meta, "ObjectName") or page.get("title", "")
            autor = self._texto(meta, "Artist", "Desconocido") or "Desconocido"
            fuente = self._texto(meta, "ImageDescription")
            # La página de archivo es una atribución estable; ImageDescription suele ser HTML.
            fuente = info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(page.get('title', '').replace(' ', '_'))}"
            if url_imagen:
                imagenes.append(ImagenLibre(url_imagen, titulo, autor, licencia, fuente, ancho, alto))
        return imagenes

    def descargar(self, img: ImagenLibre, dir_destino) -> Path:
        destino = Path(dir_destino)
        destino.mkdir(parents=True, exist_ok=True)
        ext = Path(urllib.parse.urlparse(img.url_local).path).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        nombre = hashlib.sha256(img.url_local.encode("utf-8")).hexdigest() + ext
        ruta = destino / nombre
        if ruta.is_file():
            return ruta
        contenido = self._solicitar(img.url_local, "image/*")
        ruta.write_bytes(contenido)
        return ruta

    def buscar_para_tema(self, titulo, alias, dir_destino, minimo=5, maximo=16, caso_id=None) -> list[ImagenLibre]:
        aliases = [alias] if isinstance(alias, str) else list(alias or [])
        consultas = [titulo, *aliases]
        if caso_id:
            caso = caso_id.replace("_", " ")
            consultas.extend([caso, caso_id, f"{caso} map", f"{caso} mapa", f"{caso} photograph", f"{caso} fotografía"])
        consultas.extend([f"{titulo} map", f"{titulo} mapa", f"{titulo} photograph", f"{titulo} fotografía"])
        consultas = list(dict.fromkeys(q.strip() for q in consultas if q and q.strip()))
        encontrados, vistos = [], set()
        for consulta in consultas:
            for img in self.buscar(consulta, max_resultados=maximo):
                if img.url_local in vistos:
                    continue
                vistos.add(img.url_local)
                encontrados.append(img)
        # Examina resultados de todas las consultas y prioriza originales de mayor resolución.
        encontrados.sort(key=lambda img: (img.ancho * img.alto, img.ancho), reverse=True)
        resultado = []
        for img in encontrados:
            try:
                ruta = self.descargar(img, dir_destino)
            except (ErrorImagenes, OSError):
                continue
            resultado.append(ImagenLibre(str(ruta), img.titulo, img.autor, img.licencia,
                                         img.url_fuente, img.ancho, img.alto))
            if len(resultado) >= maximo:
                return resultado
        return resultado


def _limpio(texto: str, largo: int = 80) -> str:
    """Sin HTML ni '<' '>' (YouTube rechaza descripciones con esos caracteres)."""
    import html as _h
    t = re.sub(r"<[^>]*>", " ", str(texto))
    t = _h.unescape(t).replace("<", "").replace(">", "")
    t = re.sub(r"\s+", " ", t).strip()
    return (t[:largo].rstrip() + "…") if len(t) > largo else (t or "Desconocido")


def creditos(imagenes) -> str:
    lineas = [f"{_limpio(i.titulo, 100)} — {_limpio(i.autor)} — {_limpio(i.licencia, 40)} — {_limpio(i.url_fuente, 300)}" for i in imagenes]
    return "Imágenes: " + "; ".join(lineas) if lineas else ""
