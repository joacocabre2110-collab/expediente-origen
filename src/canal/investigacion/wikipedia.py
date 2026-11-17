"""Cliente pequeño para la API pública de Wikipedia (urllib, sin dependencias)."""
from __future__ import annotations
from dataclasses import dataclass
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

@dataclass(frozen=True)
class Fuente:
    titulo: str
    idioma: str
    url: str
    texto: str

class ErrorWikipedia(RuntimeError):
    pass

class ClienteWikipedia:
    def __init__(self, abrir=urllib.request.urlopen, pausa_min_s=2.0, idiomas=("es", "en"),
                 user_agent="ExpedienteOrigenBot/0.1 (documentary research; personal project)",
                 sleep=time.sleep, reintentos=3, retry_after_max_s=120, jitter=None):
        if pausa_min_s < 0 or reintentos < 0: raise ValueError("pausa/reintentos no pueden ser negativos")
        if retry_after_max_s < 0: raise ValueError("retry_after_max_s no puede ser negativo")
        self.abrir, self.pausa_min_s, self.idiomas = abrir, pausa_min_s, tuple(idiomas)
        self.user_agent, self.sleep, self.reintentos, self._ultima = user_agent, sleep, reintentos, None
        self.retry_after_max_s = retry_after_max_s
        self.jitter = jitter or (lambda techo: random.uniform(0, techo))

    def _get(self, idioma, params):
        if idioma not in self.idiomas: raise ErrorWikipedia("Idioma no habilitado")
        params = {**params, "format": "json", "formatversion": 2}
        url = f"https://{idioma}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
        for intento in range(self.reintentos + 1):
            if self._ultima is not None:
                espera = self.pausa_min_s - (time.monotonic() - self._ultima)
                if espera > 0: self.sleep(espera)
            self._ultima = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            try:
                with self.abrir(req, timeout=15) as r: return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if not (e.code == 429 or 500 <= e.code <= 599) or intento >= self.reintentos:
                    raise ErrorWikipedia(f"Wikipedia respondió HTTP {e.code}") from None
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if retry_after is not None:
                    try:
                        espera_reintento = min(self.retry_after_max_s, max(0.0, float(retry_after)))
                    except (TypeError, ValueError):
                        espera_reintento = min(8, 2 ** intento) + self.jitter(1.0)
                else:
                    espera_reintento = min(8, 2 ** intento) + self.jitter(1.0)
                self.sleep(espera_reintento)
            except (TimeoutError, urllib.error.URLError) as e:
                if isinstance(e, urllib.error.URLError) and not isinstance(e.reason, TimeoutError):
                    raise ErrorWikipedia("No se pudo conectar con Wikipedia") from None
                if intento >= self.reintentos: raise ErrorWikipedia("Wikipedia agotó los reintentos de conexión/timeout") from None
                self.sleep(min(8, 2 ** intento) + self.jitter(1.0))
            except (ValueError, UnicodeError) as e: raise ErrorWikipedia("Respuesta JSON inválida de Wikipedia") from None

    def buscar(self, consulta, idioma=None):
        resultados = []
        for lang in ((idioma,) if idioma else self.idiomas):
            payload = self._get(lang, {"action":"query", "list":"search", "srsearch":consulta, "srlimit":5})
            for item in payload.get("query", {}).get("search", []):
                titulo = item.get("title", "")
                if titulo: resultados.append(Fuente(titulo, lang, f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(titulo.replace(' ', '_'))}", ""))
        return resultados

    def extracto(self, titulo, idioma=None):
        idiomas = (idioma,) if idioma else self.idiomas
        for lang in idiomas:
            payload = self._get(lang, {"action":"query", "prop":"extracts", "explaintext":1, "exsectionformat":"plain", "titles":titulo})
            pages = payload.get("query", {}).get("pages", [])
            if isinstance(pages, dict): pages = list(pages.values())
            for p in pages:
                text = p.get("extract", "")
                title = p.get("title", titulo)
                if text.strip(): return Fuente(title, lang, f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}", text.strip())
        return Fuente(titulo, idiomas[0], "", "")
