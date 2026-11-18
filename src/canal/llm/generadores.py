"""Adaptadores Gemini para las etapas de texto del pipeline."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from canal.pipeline.etapas import (
    ContextoVideo, Guion, Metadatos, Miniatura, Render, ResultadoVerificacion, Tema,
)
from canal.investigacion.brief import construir_brief
from canal.dedupe.temas import tema_repetido, siguiente_numero_expediente


_ROOT = Path(__file__).parent
_IDENTIDAD = Path(os.environ.get("CANAL_ASSETS_DIR", Path(__file__).parents[3] / "assets/original/canal_youtube")) / "CANAL_YOUTUBE.md"


def _sistema() -> str:
    try:
        texto = _IDENTIDAD.read_text(encoding="utf-8")
    except OSError:
        texto = ""
    lineas = [l.strip(" -*") for l in texto.splitlines() if l.strip() and not l.startswith("|")]
    selec = [l for l in lineas if any(k in l.lower() for k in
             ("misterio", "documental", "evidencia", "leyenda", "español", "expediente"))]
    resumen = " ".join(selec[:5])[:500]
    return ("Respondé en español rioplatense neutro, con tono documental, grave y claro. "
            "Separá evidencia, hipótesis y leyenda; no presentes lo incierto como hecho. " + resumen)


class _Plantilla(str):
    """Plantilla que sustituye solo {variables} dadas; el resto de llaves (JSON de ejemplo) queda intacto."""
    def format(self, **kw):  # type: ignore[override]
        return re.sub(r"\{(\w+)\}", lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), str(self))


def _plantilla(nombre: str) -> str:
    return _Plantilla((_ROOT / "prompts" / nombre).read_text(encoding="utf-8"))


def _json(cliente: Any, rol: str, prompt: str, sistema: str, validar):
    ultimo = None
    for intento in range(2):
        pedido = prompt if ultimo is None else prompt + "\n\nLa salida anterior fue inválida: " + ultimo + ". Corregila y devolvé solo JSON válido."
        raw = cliente.generar(rol, pedido, sistema=sistema, max_tokens=(16384 if rol == "guion" else 8192), temperatura=0.4, json=True)
        try:
            obj = json.loads(raw)
            validar(obj)
            return obj
        except (ValueError, TypeError, KeyError) as exc:
            ultimo = str(exc)[:300] or "esquema incorrecto"
    raise ValueError(f"Respuesta LLM inválida tras un reintento: {ultimo}")


def _obj(obj: Any, keys: set[str]) -> dict:
    if not isinstance(obj, dict) or set(obj) != keys:
        raise ValueError(f"se esperaba objeto con campos {sorted(keys)}")
    return obj


def _texto(obj: dict, key: str, minimo: int, maximo: int) -> str:
    val = obj[key]
    if not isinstance(val, str) or not minimo <= len(val.strip()) <= maximo:
        raise ValueError(f"{key}: longitud debe estar entre {minimo} y {maximo}")
    return val.strip()


def _lista(obj: dict, key: str, minimo: int, maximo: int, largo: int) -> list[str]:
    val = obj[key]
    if not isinstance(val, list) or not minimo <= len(val) <= maximo or any(
            not isinstance(x, str) or not 1 <= len(x.strip()) <= largo for x in val):
        raise ValueError(f"{key}: lista o longitudes inválidas")
    return [x.strip() for x in val]


class GeneradorTemaLLM:
    def __init__(self, cliente: Any, cliente_wiki: Any = None, registro_temas: Any = (), max_intentos: int = 3, min_fragmentos: int | None = None) -> None:
        self.cliente, self.cliente_wiki, self.registro_temas = cliente, cliente_wiki, registro_temas
        self.max_intentos, self.min_fragmentos = max_intentos, min_fragmentos
    def generar(self, contexto: ContextoVideo) -> Tema:
        prompt = _plantilla("tema.txt").format(tipo=contexto.tipo, video_key=contexto.video_key)
        def validar(o):
            _obj(o, {"titulo", "caso_id", "pilar", "alias"})
            _texto(o, "titulo", 5, 100); _texto(o, "caso_id", 3, 60)
            if o["pilar"] not in ("espacio", "tierra", "sobrenatural"): raise ValueError("pilar inválido")
            _lista(o, "alias", 1, 5, 80)
        for _ in range(self.max_intentos):
            o = _json(self.cliente, "tema", prompt, _sistema(), validar)
            tema = Tema(o["titulo"].strip(), o["caso_id"].strip(), o["pilar"], _lista(o, "alias", 1, 5, 80))
            if self.cliente_wiki is None:
                n = siguiente_numero_expediente(self.registro_temas)
                return Tema(f"Expediente {n}: {tema.titulo}", tema.caso_id, tema.pilar, tema.alias)
            try: brief = construir_brief(tema, self.cliente_wiki, max_fragmentos=8 if contexto.tipo == "largo" else 4, min_fragmentos=self.min_fragmentos)
            except RuntimeError: continue
            if not tema_repetido(tema.titulo, tema.alias, self.registro_temas, caso_id=tema.caso_id).aprobado: continue
            n = siguiente_numero_expediente(self.registro_temas)
            return Tema(f"Expediente {n}: {tema.titulo}", tema.caso_id, tema.pilar, tema.alias)
        raise ValueError("No se encontró un tema no repetido con evidencia suficiente en Wikipedia")


class GeneradorGuionLLM:
    def __init__(self, cliente: Any, cliente_wiki: Any = None, min_fragmentos: int | None = None) -> None:
        self.cliente, self.cliente_wiki, self.min_fragmentos = cliente, cliente_wiki, min_fragmentos
        self._brief = None
    def generar(self, contexto: ContextoVideo, tema: Tema, brief: Any = None) -> Guion:
        if brief is None and self.cliente_wiki is not None:
            brief = construir_brief(tema, self.cliente_wiki, max_fragmentos=8 if contexto.tipo == "largo" else 4, min_fragmentos=self.min_fragmentos)
        if brief is None: raise ValueError("Se requiere un Brief para redactar un guion factual")
        self._brief = brief
        fuentes = "\n".join(f"[{f.id}] {f.texto}" for f in brief.fragmentos)
        prompt = _plantilla("guion.txt").format(tema=json.dumps(tema.__dict__, ensure_ascii=False), tipo=contexto.tipo, fragmentos=fuentes)
        ids = {f.id for f in brief.fragmentos}
        def validar(o):
            _obj(o, {"texto", "gancho", "intro", "estructura", "pilar", "afirmaciones"})
            _texto(o, "texto", 80, 12000); _texto(o, "gancho", 8, 180); _texto(o, "intro", 8, 500)
            if not isinstance(o["afirmaciones"], list): raise ValueError("afirmaciones debe ser lista")
            for a in o["afirmaciones"]:
                if not isinstance(a, dict) or set(a) != {"texto", "citas"} or not isinstance(a["texto"], str) or not isinstance(a["citas"], list) or not a["citas"] or any(x not in ids for x in a["citas"]): raise ValueError("afirmación con citas inexistentes o inválidas")
            if o["estructura"] not in ("cronologica", "misterio", "causa_consecuencia", "comparacion", "investigacion", "giro_final"):
                raise ValueError("estructura inválida")
            if o["pilar"] != tema.pilar: raise ValueError("pilar debe coincidir con el tema")
        o = _json(self.cliente, "guion", prompt, _sistema(), validar)
        return Guion(*(_texto(o, k, 1, 12000 if k == "texto" else 500) for k in ("texto", "gancho", "intro")), o["estructura"], o["pilar"], o["afirmaciones"])


class VerificadorLLM:
    def __init__(self, cliente: Any, cliente_wiki: Any = None) -> None: self.cliente, self.cliente_wiki = cliente, cliente_wiki
    def verificar(self, contexto: ContextoVideo, tema: Tema, guion: Guion, brief: Any = None) -> ResultadoVerificacion:
        if brief is None and self.cliente_wiki is not None: brief = construir_brief(tema, self.cliente_wiki, max_fragmentos=8 if contexto.tipo == "largo" else 4)
        if brief is None: raise ValueError("Se requiere un Brief para verificar afirmaciones")
        ids = {f.id for f in brief.fragmentos}
        for afirmacion in (guion.afirmaciones or []):
            if not isinstance(afirmacion, dict) or not afirmacion.get("citas") or any(i not in ids for i in afirmacion["citas"]):
                return ResultadoVerificacion(False, ["Afirmación con citas ausentes o ids de fragmento inválidos"])
        fuentes = "\n".join(f"[{f.id}] {f.texto}" for f in brief.fragmentos)
        prompt = _plantilla("verificacion.txt").format(tema=json.dumps(tema.__dict__, ensure_ascii=False), guion=guion.texto, fragmentos=fuentes, afirmaciones=json.dumps(guion.afirmaciones or [], ensure_ascii=False))
        def validar(o):
            _obj(o, {"afirmaciones", "dudosas", "motivos"})
            # Tolerancia: se recorta lo que el modelo deje demasiado largo en vez de rechazar la respuesta.
            for clave, cuantos, largo in (("afirmaciones", 80, 500), ("dudosas", 80, 500), ("motivos", 20, 300)):
                if isinstance(o.get(clave), list):
                    o[clave] = [x.strip()[:largo] for x in o[clave] if isinstance(x, str) and x.strip()][:cuantos]
            _lista(o, "afirmaciones", 0, 80, 500); _lista(o, "dudosas", 0, 80, 500); _lista(o, "motivos", 0, 20, 300)
        o = _json(self.cliente, "verificacion", prompt, _sistema(), validar)
        dudas = _lista(o, "dudosas", 0, 80, 500)
        motivos = _lista(o, "motivos", 0, 20, 300)
        return ResultadoVerificacion(not dudas, motivos if not dudas else motivos + ["Afirmaciones dudosas o no verificables: " + "; ".join(dudas[:5])])


class GeneradorMetadatosLLM:
    def __init__(self, cliente: Any) -> None: self.cliente = cliente
    def generar(self, contexto: ContextoVideo, tema: Tema, guion: Guion,
                render: Render, miniatura: Miniatura) -> Metadatos:
        prompt = _plantilla("metadatos.txt").format(tema=tema.titulo, guion=guion.texto, tipo=contexto.tipo)
        def validar(o):
            _obj(o, {"titulo", "descripcion", "etiquetas"})
            _texto(o, "titulo", 5, 100); _texto(o, "descripcion", 40, 3000); _lista(o, "etiquetas", 3, 20, 50)
        o = _json(self.cliente, "metadatos", prompt, _sistema(), validar)
        return Metadatos(o["titulo"].strip(), o["descripcion"].strip(), _lista(o, "etiquetas", 3, 20, 50))
