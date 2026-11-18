

def test_verificador_recorta_textos_largos():
    import json
    from canal.llm.generadores import VerificadorLLM
    from canal.pipeline.etapas import ContextoVideo, Tema, Guion
    from types import SimpleNamespace as NS
    larga = "x" * 900
    class C:
        def generar(self, *a, **k):
            return json.dumps({"afirmaciones": [larga], "dudosas": [], "motivos": []})
    brief = NS(fragmentos=[NS(id="F1", texto="t")])
    g = Guion("texto " * 30, "gancho de prueba", "intro de prueba", "misterio", "tierra", [{"texto": "a", "citas": ["F1"]}])
    r = VerificadorLLM(C()).verificar(ContextoVideo("short-x", "short", "/tmp") if False else NS(tipo="short", video_key="k"), Tema("t", "c", "tierra", ["a"]), g, brief)
    assert r.aprobado
