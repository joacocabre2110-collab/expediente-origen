"""Construcción determinista de evidencia desde artículos de Wikipedia."""
from __future__ import annotations
from dataclasses import dataclass
import re
import unicodedata

@dataclass(frozen=True)
class Fragmento:
    id: str
    texto: str
    fuente_url: str
    fuente_titulo: str

@dataclass(frozen=True)
class Brief:
    tema: str
    fragmentos: tuple[Fragmento, ...]

class BriefInsuficiente(RuntimeError):
    pass

def construir_brief(tema, cliente_wiki, max_fragmentos=8, min_fragmentos=None):
    min_fragmentos = min_fragmentos if min_fragmentos is not None else (4 if max_fragmentos <= 4 else 8)
    titulo = getattr(tema, "titulo", str(tema))
    titulo_limpio = re.sub(r"^\s*Expediente\s+\d+\s*:\s*", "", titulo, flags=re.I)
    titulo_limpio = re.split(r"\s*[:\-–—]\s*", titulo_limpio, maxsplit=1)[0].strip()
    alias = getattr(tema, "alias", ())
    caso_id = getattr(tema, "caso_id", "")
    consultas = []
    for original in [*(alias or ()), caso_id, titulo_limpio]:
        consulta = re.sub(r"\b(?:19|20)\d{2}\b", " ", str(original or "").replace("-", " "))
        consulta = " ".join(consulta.split())
        if consulta and consulta.casefold() not in {x.casefold() for x in consultas}:
            consultas.append(consulta)
    idioma = getattr(cliente_wiki, "idiomas", ("es", "en"))
    idiomas = ("es", "en") if set(idioma) >= {"es", "en"} else tuple(idioma)
    consultas_por_campo = [alias or (), (caso_id,), (titulo_limpio,)]
    referencias = []
    for grupo in consultas_por_campo:
        for texto in grupo:
            limpio = re.sub(r"\b(?:19|20)\d{2}\b", " ", str(texto or "").replace("-", " "))
            limpio = " ".join(limpio.split())
            if limpio:
                referencias.append(limpio)
    fuentes, vistos = [], set()
    candidatos = {}
    for consulta in consultas:
        for lang in idiomas:
            for hallada in cliente_wiki.buscar(consulta, lang):
                clave = (hallada.idioma, hallada.titulo.casefold())
                if clave not in candidatos:
                    candidatos[clave] = hallada
    stopwords = set("el la los las de del en y o un una por para con al the a an of in and case incident caso".split())
    def tokens(s):
        s = unicodedata.normalize("NFD", s.casefold())
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return {t for t in re.findall(r"[a-z0-9]+", s) if t not in stopwords and len(t) > 1}
    objetivos = [tokens(x) for x in referencias]
    for clave, hallada in candidatos.items():
        titulo_articulo = hallada.titulo
        if re.match(r"^Anexo\s*:", titulo_articulo, re.I) or "(desambiguación)" in titulo_articulo.casefold():
            continue
        if re.fullmatch(r"(?:\d{1,2}\s+de\s+)?[\wáéíóúñ]+(?:\s+de\s+\d{4})?|\d{4}", titulo_articulo, re.I):
            continue
        titulo_tokens = tokens(titulo_articulo)
        score = max((len(titulo_tokens & objetivo) for objetivo in objetivos), default=0)
        if score < 1: continue
        fuente = cliente_wiki.extracto(titulo_articulo, hallada.idioma)
        if len(fuente.texto) < 200 or not any(tokens(fuente.texto) & objetivo & titulo_tokens for objetivo in objetivos):
            continue
        fuentes.append((score, fuente))
    fuentes.sort(key=lambda par: par[0], reverse=True)
    fuentes = [f for _, f in fuentes]
    fragmentos, textos = [], set()
    for fuente in fuentes:
        partes = re.split(r"(?<=[.!?])\s+|\n+", fuente.texto)
        bloque = ""
        for parte in partes:
            parte = " ".join(parte.split())
            if not parte: continue
            if len(parte) > 600:
                partes_largas = [parte[i:i+600] for i in range(0, len(parte), 600)]
            else: partes_largas = [parte]
            for trozo in partes_largas:
                if len(bloque) + len(trozo) + 1 > 600:
                    if len(bloque) >= 60 and bloque.casefold() not in textos:
                        textos.add(bloque.casefold()); fragmentos.append((fuente, bloque))
                    bloque = ""
                bloque = (bloque + " " + trozo).strip()
        if len(bloque) >= 60 and bloque.casefold() not in textos:
            textos.add(bloque.casefold()); fragmentos.append((fuente, bloque))
    fragmentos = tuple(Fragmento(f"F{i+1}", t, f.url, f.titulo) for i, (f,t) in enumerate(fragmentos[:max_fragmentos]))
    if len(fragmentos) < min_fragmentos: raise BriefInsuficiente(f"Se requieren {min_fragmentos} fragmentos y solo se encontraron {len(fragmentos)} para {getattr(tema, 'titulo', tema)}")
    return Brief(titulo, fragmentos)
