"""Convierte guiones en segmentos visuales con validación estricta."""
from __future__ import annotations

import json
from pathlib import Path
import re
import math
from typing import Any

from canal.render.escenas import Escena, TIPOS, renderizar_cuerpo

_PROMPT = Path(__file__).parent / "prompts" / "escenas.txt"


def _sustituir(template: str, values: dict[str, str]) -> str:
    # Solo sustituye identificadores declarados. Las llaves JSON del prompt quedan intactas.
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template)


def _oraciones(texto: str) -> list[str]:
    partes = re.findall(r".+?(?:[.!?…]+(?:[\"'”’)]*)?(?=\s|$)|$)", texto.strip(), re.S)
    return [p.strip() for p in partes if p.strip()]


def _hechos_cita(guion: Any) -> str:
    afirmaciones = getattr(guion, "afirmaciones", None) or []
    return json.dumps(afirmaciones, ensure_ascii=False)


class PlanificadorEscenasLLM:
    def __init__(self, cliente_gemini: Any):
        self.cliente = cliente_gemini

    def planificar(self, contexto, tema, guion, imagenes=None):
        texto = guion.texto.strip()
        formato = contexto.tipo
        if not texto:
            raise ValueError("El guion está vacío")
        oraciones = _oraciones(texto)
        guion_numerado = "\n".join(f"S{i}: {oracion}" for i, oracion in enumerate(oraciones, 1))
        lista_imagenes = "\n".join(f"[I{i}] {img.titulo} — {img.autor}" for i, img in enumerate(imagenes or [], 1))
        prompt = _sustituir(_PROMPT.read_text(encoding="utf-8"), {
            "tipo": formato, "guion": guion_numerado, "citas": _hechos_cita(guion),
            "gancho": getattr(guion, "gancho", ""),
            "imagenes": lista_imagenes or "(sin imágenes disponibles)",
        })
        error = "respuesta inválida"
        for intento in range(2):
            pedido = prompt if intento == 0 else prompt + "\nLa respuesta anterior fue inválida (" + error[:240] + "). Corregí el JSON y devolvé solo JSON."
            raw = self.cliente.generar("guion", pedido, max_tokens=8192, temperatura=.3, json=True)
            try:
                segmentos = self._validar(json.loads(raw), texto, formato, completar_huecos=intento == 1, imagenes=imagenes or [])
                return segmentos
            except (ValueError, TypeError, KeyError) as exc:
                error = str(exc)
        raise ValueError(f"Plan de escenas inválido tras un reintento: {error}")

    def generar(self, contexto, tema, guion):
        return self.planificar(contexto, tema, guion)

    @staticmethod
    def _validar(obj, guion, formato, completar_huecos=False, imagenes=None):
        imagenes = imagenes or []
        if not isinstance(obj, dict) or set(obj) != {"segmentos"} or not isinstance(obj["segmentos"], list) or not obj["segmentos"]:
            raise ValueError("se esperaba objeto con lista segmentos")
        oraciones = _oraciones(guion)
        segmentos, cubiertos = [], []
        ultima_imagen = None
        for i, item in enumerate(obj["segmentos"]):
            if not isinstance(item, dict) or set(item) not in ({"oraciones", "escena", "impacto"}, {"oraciones", "escena", "impacto", "imagen"}):
                raise ValueError("segmento debe tener oraciones, escena e impacto")
            indice_imagen = item.get("imagen")
            if indice_imagen is not None and (not isinstance(indice_imagen, int) or isinstance(indice_imagen, bool)):
                raise ValueError("imagen debe ser índice entero o null")
            if indice_imagen is not None and not 1 <= indice_imagen <= len(imagenes):
                raise ValueError("índice de imagen fuera de rango")
            if indice_imagen is not None and indice_imagen - 1 == ultima_imagen:
                raise ValueError("no se permite la misma imagen en segmentos consecutivos")
            indices = item["oraciones"]
            if (not isinstance(indices, list) or not 1 <= len(indices) <= 2
                    or any(not isinstance(n, int) or isinstance(n, bool) for n in indices)
                    or indices != list(range(len(cubiertos) + 1, len(cubiertos) + len(indices) + 1))):
                if completar_huecos and isinstance(indices, list) and 1 <= len(indices) <= 2 and all(isinstance(n, int) and not isinstance(n, bool) for n in indices):
                    pass
                else:
                    raise ValueError("los índices deben ser consecutivos, estar en orden y no repetirse")
            if indices[0] < 1 or indices[-1] > len(oraciones) or indices != list(range(indices[0], indices[0] + len(indices))):
                raise ValueError("índices de oraciones inválidos")
            if indices[0] <= len(cubiertos):
                raise ValueError("índices de oraciones repetidos o desordenados")
            if indices[0] != len(cubiertos) + 1 and not completar_huecos:
                raise ValueError("faltan índices de oraciones")
            if not isinstance(item["impacto"], bool):
                raise ValueError("impacto inválido")
            while len(cubiertos) < indices[0] - 1:
                n = len(cubiertos) + 1
                segmentos.append({"texto": oraciones[n - 1], "escena": {"tipo": "texto_clave", "datos": {"frase": oraciones[n - 1][:100]}}, "impacto": False})
                cubiertos.append(n)
            texto = " ".join(oraciones[n - 1] for n in indices)
            escena = item["escena"]
            if not isinstance(escena, dict) or set(escena) != {"tipo", "datos"} or escena["tipo"] not in TIPOS:
                raise ValueError("escena o tipo inválido")
            if i == 0 and escena["tipo"] != "portada":
                raise ValueError("la primera escena debe ser portada")
            if i == 0 and indices[0] != 1:
                raise ValueError("faltan índices antes de la portada")
            if i == len(obj["segmentos"]) - 1 and (escena["tipo"] != "cierre" or indices[-1] != len(oraciones)):
                raise ValueError("la última escena debe ser cierre y cubrir el final")
            datos = escena["datos"]
            if indice_imagen is not None:
                datos = dict(datos)
                datos["imagen"] = imagenes[indice_imagen - 1].url_local
                ultima_imagen = indice_imagen - 1
            else:
                ultima_imagen = None
            # El esquema de TIPOS y la validación de contenido pertenecen a escenas.py.
            renderizar_cuerpo(Escena(escena["tipo"], datos, 1.0, seed=i, formato=formato))
            cubiertos.extend(indices)
            segmentos.append({"texto": texto, "escena": {"tipo": escena["tipo"], "datos": datos}, "impacto": item["impacto"]})
        if len(cubiertos) < len(oraciones):
            if not completar_huecos:
                raise ValueError("el guion no está cubierto completo y en orden")
            while len(cubiertos) < len(oraciones):
                n = len(cubiertos) + 1
                cubiertos.append(n)
                segmentos.append({"texto": oraciones[n - 1], "escena": {"tipo": "texto_clave", "datos": {"frase": oraciones[n - 1][:100]}}, "impacto": False})
        tipos = [s["escena"]["tipo"] for s in segmentos]
        if tipos[0] != "portada" or tipos[-1] != "cierre":
            raise ValueError("la primera escena debe ser portada y la última cierre")
        if any(tipos[j] == tipos[j-1] == tipos[j-2] for j in range(2, len(tipos))):
            raise ValueError("no se permite repetir tipo más de dos veces")
        if cubiertos != list(range(1, len(oraciones) + 1)):
            raise ValueError("el guion no está cubierto completo y en orden")
        if imagenes:
            _asignar_imagenes(segmentos, imagenes)
        return segmentos


def _asignar_imagenes(segmentos, imagenes):
    """Asegura cobertura visual sin repetir archivo en segmentos consecutivos."""
    conteos = [0] * len(imagenes)
    asignadas = []
    for segmento in segmentos:
        ruta = segmento["escena"]["datos"].get("imagen")
        indice = next((i for i, img in enumerate(imagenes) if img.url_local == ruta), None)
        asignadas.append(indice)
        if indice is not None:
            conteos[indice] += 1
    objetivo = math.ceil(len(segmentos) * .8)
    cobertura = sum(i is not None for i in asignadas)
    for pos, segmento in enumerate(segmentos):
        tipo = segmento["escena"]["tipo"]
        if cobertura >= objetivo:
            break
        if asignadas[pos] is not None or tipo in ("numero", "pregunta"):
            continue
        anterior = asignadas[pos - 1] if pos else None
        candidatos = [i for i in range(len(imagenes)) if i != anterior]
        prefiere_mapa = tipo in ("linea_tiempo", "numero")
        if prefiere_mapa:
            mapas = [i for i in candidatos if "map" in imagenes[i].titulo.casefold() or "mapa" in imagenes[i].titulo.casefold()]
            if mapas:
                candidatos = mapas
        if not candidatos:
            continue
        elegido = min(candidatos, key=lambda i: (conteos[i], i))
        datos = segmento["escena"]["datos"]
        datos["imagen"] = imagenes[elegido].url_local
        # Alterna presentación cuando el archivo vuelve a aparecer.
        if conteos[elegido]:
            datos["imagen_modo"] = "marco" if conteos[elegido] % 2 else "fondo"
        asignadas[pos] = elegido
        conteos[elegido] += 1
        cobertura += 1
