import json

import pytest

from canal.director.planificador import PlanificadorEscenasLLM
from canal.pipeline.etapas import ContextoVideo, Guion, Tema


class Cliente:
    def __init__(self, respuestas): self.respuestas, self.llamadas = list(respuestas), []
    def generar(self, rol, prompt, **kwargs):
        self.llamadas.append((rol, prompt, kwargs))
        return self.respuestas.pop(0)


def setup_guion():
    return (ContextoVideo("x", "largo", "2026-01-01", "."), Tema("Caso", "caso", "espacio", []),
            Guion("La sonda llegó a Marte. Envió tres imágenes.", "Gancho visual", "", "cronologica", "espacio"))


def salida():
    return {"segmentos": [
        {"oraciones": [1], "escena": {"tipo": "portada", "datos": {"expediente": "EXP 01", "titulo": "La llegada a Marte", "subtitulo": "Una sonda en el planeta"}}, "impacto": False},
        {"oraciones": [2], "escena": {"tipo": "cierre", "datos": {"frase": "Tres imágenes llegaron.", "adelanto": "El próximo misterio"}}, "impacto": True},
    ]}


def test_planificador_genera_json_validado_y_usa_rol_guion():
    cliente = Cliente([json.dumps(salida())])
    contexto, tema, guion = setup_guion()
    result = PlanificadorEscenasLLM(cliente).planificar(contexto, tema, guion)
    assert len(result) == 2
    assert cliente.llamadas[0][0] == "guion"
    assert "S1: La sonda llegó a Marte." in cliente.llamadas[0][1]
    assert "S2: Envió tres imágenes." in cliente.llamadas[0][1]
    assert [s["texto"] for s in result] == ["La sonda llegó a Marte.", "Envió tres imágenes."]


def test_planificador_reintenta_una_vez_y_falla_controlado():
    bad = salida(); bad["segmentos"][0]["oraciones"] = [2]
    cliente = Cliente([json.dumps(bad), json.dumps(bad)])
    contexto, tema, guion = setup_guion()
    with pytest.raises(ValueError, match="reintento"):
        PlanificadorEscenasLLM(cliente).planificar(contexto, tema, guion)
    assert len(cliente.llamadas) == 2


def test_planificador_completa_hueco_despues_de_reintentar():
    contexto, tema, _ = setup_guion()
    guion = Guion("La sonda llegó a Marte. Envió tres imágenes. Después regresó.", "Gancho", "", "cronologica", "espacio")
    incompleto = {"segmentos": [
        {"oraciones": [1], "escena": {"tipo": "portada", "datos": {"expediente": "EXP 01", "titulo": "La llegada a Marte", "subtitulo": "Una sonda en el planeta"}}, "impacto": False},
        {"oraciones": [3], "escena": {"tipo": "cierre", "datos": {"frase": "Después regresó.", "adelanto": "La sonda regresó"}}, "impacto": True},
    ]}
    cliente = Cliente([json.dumps(incompleto), json.dumps(incompleto)])
    result = PlanificadorEscenasLLM(cliente).planificar(contexto, tema, guion)
    assert len(cliente.llamadas) == 2
    assert [s["texto"] for s in result] == ["La sonda llegó a Marte.", "Envió tres imágenes.", "Después regresó."]
    assert result[1]["escena"] == {"tipo": "texto_clave", "datos": {"frase": "Envió tres imágenes."}}


def test_el_modelo_no_puede_reescribir_texto_del_segmento():
    cliente = Cliente([json.dumps(salida())])
    contexto, tema, guion = setup_guion()
    result = PlanificadorEscenasLLM(cliente).planificar(contexto, tema, guion)
    assert '"texto"' not in json.dumps(salida()["segmentos"])
    assert result[0]["texto"] == guion.texto.split(" Envió", 1)[0]


def test_imagenes_se_listan_y_se_mapean_a_ruta_local(tmp_path):
    from types import SimpleNamespace
    data = salida()
    data["segmentos"][0]["imagen"] = 1
    cliente = Cliente([json.dumps(data)])
    contexto, tema, guion = setup_guion()
    path = tmp_path / "marte.jpg"
    path.write_bytes(bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9"))
    imagen = SimpleNamespace(titulo="Marte rojo", autor="NASA", url_local=str(path))
    result = PlanificadorEscenasLLM(cliente).planificar(contexto, tema, guion, [imagen])
    assert "[I1] Marte rojo — NASA" in cliente.llamadas[0][1]
    assert result[0]["escena"]["datos"]["imagen"] == str(path)


def test_asigna_imagenes_de_respaldo_hasta_cobertura_y_no_repite_consecutivas():
    from types import SimpleNamespace
    contexto, tema, _ = setup_guion()
    guion = Guion("Uno. Dos. Tres. Cuatro. Cinco. Seis.", "Gancho", "", "cronologica", "espacio")
    items = [
        {"oraciones": [1], "escena": {"tipo": "portada", "datos": {"expediente": "E", "titulo": "T", "subtitulo": "S"}}, "impacto": False},
        {"oraciones": [2], "escena": {"tipo": "numero", "datos": {"cifra": "2", "leyenda": "Dos"}}, "impacto": False},
        {"oraciones": [3], "escena": {"tipo": "pregunta", "datos": {"pregunta": "¿Tres?"}}, "impacto": False},
        {"oraciones": [4], "escena": {"tipo": "pistas", "datos": {"evidencias": [{"texto": "Cuatro"}, {"texto": "Cuatro"}]}}, "impacto": False},
        {"oraciones": [5], "escena": {"tipo": "texto_clave", "datos": {"frase": "Cinco"}}, "impacto": False},
        {"oraciones": [6], "escena": {"tipo": "cierre", "datos": {"frase": "Seis", "adelanto": "Fin"}}, "impacto": False},
    ]
    imgs = [SimpleNamespace(titulo=f"Imagen {i}", autor="", url_local=f"/img/{i}") for i in range(3)]
    result = PlanificadorEscenasLLM(Cliente([json.dumps({"segmentos": items})])).planificar(contexto, tema, guion, imgs)
    rutas = [s["escena"]["datos"].get("imagen") for s in result]
    assert sum(r is not None for r in rutas) >= 4
    assert all(a is None or b is None or a != b for a, b in zip(rutas, rutas[1:]))
    assert any(s["escena"]["datos"].get("imagen_modo") == "marco" for s in result)


def test_rechaza_misma_imagen_en_segmentos_consecutivos():
    from types import SimpleNamespace
    contexto, tema, guion = setup_guion()
    data = salida()
    data["segmentos"][0]["imagen"] = 1
    data["segmentos"][1]["imagen"] = 1
    img = SimpleNamespace(titulo="Marte", autor="", url_local="/img/marte")
    cliente = Cliente([json.dumps(data), json.dumps(data)])
    with pytest.raises(ValueError, match="reintento"):
        PlanificadorEscenasLLM(cliente).planificar(contexto, tema, guion, [img])
