import json
import urllib.error

import pytest

from datetime import datetime

from canal.llm.gemini import ClienteGemini, CuotaAgotada, ErrorGemini, ServicioGeminiNoDisponible
from canal.llm.generadores import VerificadorLLM
from canal.pipeline.etapas import ContextoVideo, Guion, Tema
from canal.investigacion.brief import Brief, Fragmento

BRIEF = Brief("Caso", (Fragmento("F1", "Texto fuente suficientemente amplio para apoyar o rechazar cualquier afirmación concreta.", "https://es.wikipedia.org/wiki/Caso", "Caso"),))


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.payload).encode()


def test_retries_429_then_succeeds_and_records_usage(tmp_path):
    key = tmp_path / "key"; key.write_text("secret-token")
    calls, waits, usage = [], [], []
    def open_(req, timeout):
        calls.append(req)
        if len(calls) == 1: raise urllib.error.HTTPError(req.full_url, 429, "busy", {}, None)
        return Response({"candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                         "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2}})
    c = ClienteGemini(key, {"guion": "gemini-test"}, pausa_min_s=0, sleep=waits.append,
                      abrir=open_, registrar_uso=lambda *x: usage.append(x), jitter=lambda _: 0)
    assert c.generar("guion", "hola", max_tokens=10, temperatura=0, json=True) == "ok"
    assert waits == [1]
    assert calls[0].get_header("X-goog-api-key") == "secret-token"
    assert usage == [("gemini-test", 4, 2)]


def test_minimum_pause_between_calls(tmp_path):
    key = tmp_path / "key"; key.write_text("k")
    now = [0.0]; waits = []
    def sleep(seconds): waits.append(seconds); now[0] += seconds
    def open_(*args, **kwargs):
        now[0] += 1
        return Response({"candidates": [{"content": {"parts": [{"text": "x"}]}}]})
    c = ClienteGemini(key, {"m": "model"}, pausa_min_s=7, sleep=sleep, abrir=open_, reloj=lambda: now[0])
    c.generar("m", "x"); c.generar("m", "x")
    assert waits == [6]


def test_never_leaks_key_on_http_error(tmp_path):
    key = tmp_path / "key"; key.write_text("secret-token")
    def open_(*args, **kwargs): raise urllib.error.HTTPError("url", 401, "secret-token", {}, None)
    c = ClienteGemini(key, {"m": "model"}, pausa_min_s=0, abrir=open_)
    with pytest.raises(ErrorGemini) as exc: c.generar("m", "x")
    assert "secret-token" not in str(exc.value)


def test_daily_quota_falls_back_and_persists_state(tmp_path):
    key = tmp_path / "key"; key.write_text("k")
    state = tmp_path / "gemini_uso.json"
    calls = []
    def open_(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, __import__("io").BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"daily quota"}}'))
        return Response({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
    c = ClienteGemini(key, {"guion": ["m1", "m2"]}, pausa_min_s=0, reintentos=0,
                      abrir=open_, ruta_estado=state,
                      reloj_fecha=lambda: datetime.fromisoformat("2026-11-13T10:00:00-08:00"))
    assert c.generar("guion", "x") == "ok"
    saved = json.loads(state.read_text())
    assert saved["agotados"]["m1"].startswith("2026-11-14T00:00:00")
    assert saved["requests"]["2026-11-13"] == {"m1": 1, "m2": 1}


def test_all_marked_models_raise_daily_quota_until_reset(tmp_path):
    key = tmp_path / "key"; key.write_text("k")
    state = tmp_path / "gemini_uso.json"
    state.write_text(json.dumps({"agotados": {"m1": "2026-11-14T00:00:00-08:00", "m2": "2026-11-14T00:00:00-08:00"}}))
    c = ClienteGemini(key, {"guion": ["m1", "m2"]}, ruta_estado=state,
                      reloj_fecha=lambda: datetime.fromisoformat("2026-11-13T10:00:00-08:00"))
    with pytest.raises(CuotaAgotada, match="2026-11-14"):
        c.generar("guion", "x")


def test_expired_model_state_resets_and_minute_429_retries(tmp_path):
    key = tmp_path / "key"; key.write_text("k")
    state = tmp_path / "gemini_uso.json"
    state.write_text(json.dumps({"agotados": {"m": "2026-11-13T00:00:00-08:00"}}))
    calls, waits = [], []
    def open_(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, __import__("io").BytesIO(b'{"message":"per minute rate limit"}'))
        return Response({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
    c = ClienteGemini(key, {"guion": "m"}, pausa_min_s=0, reintentos=1,
                      abrir=open_, sleep=waits.append, ruta_estado=state, jitter=lambda _: 0,
                      reloj_fecha=lambda: datetime.fromisoformat("2026-11-13T10:00:00-08:00"))
    assert c.generar("guion", "x") == "ok"
    assert waits == [1]
    assert len(calls) == 2
    assert "m" not in json.loads(state.read_text())["agotados"]


def test_503_falls_back_and_marks_model_degraded(tmp_path):
    key = tmp_path / "key"; key.write_text("k")
    state = tmp_path / "gemini_uso.json"
    ahora = datetime.fromisoformat("2026-11-13T10:00:00+00:00")
    calls, waits = [], []
    def open_(req, timeout):
        calls.append(req.full_url)
        if "/models/m1:" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 503, "down", {}, None)
        return Response({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
    c = ClienteGemini(key, {"guion": ["m1", "m2"]}, pausa_min_s=0, reintentos=2,
                      abrir=open_, sleep=waits.append, jitter=lambda _: 0,
                      ruta_estado=state, reloj_fecha=lambda: ahora)
    assert c.generar("guion", "x") == "ok"
    assert len(calls) == 4 and calls[-1].split("/models/")[1].startswith("m2:")
    assert json.loads(state.read_text())["degradados"]["m1"] == "2026-11-13T10:10:00+00:00"


def test_all_models_degraded_raise_transient_with_retry_time(tmp_path):
    key = tmp_path / "key"; key.write_text("k")
    state = tmp_path / "gemini_uso.json"
    state.write_text(json.dumps({"degradados": {"m1": "2026-11-13T10:10:00+00:00", "m2": "2026-11-13T10:12:00+00:00"}}))
    c = ClienteGemini(key, {"guion": ["m1", "m2"]}, ruta_estado=state,
                      reloj_fecha=lambda: datetime.fromisoformat("2026-11-13T10:00:00+00:00"))
    with pytest.raises(ServicioGeminiNoDisponible, match="2026-11-13T10:10:00"):
        c.generar("guion", "x")


class FakeClient:
    def __init__(self, outputs): self.outputs, self.prompts = list(outputs), []
    def generar(self, *args, **kwargs):
        self.prompts.append(args[1])
        return self.outputs.pop(0)


def test_invalid_json_retries_once_then_fails_controlled():
    client = FakeClient(["no-json", "still no-json"])
    gen = VerificadorLLM(client)
    ctx = ContextoVideo("v", "largo", "hoy", ".")
    tema = Tema("Caso sin evidencia", "caso-1", "espacio", ["caso"])
    guion = Guion("Hay agua en Marte desde 1990.", "¿Qué pasó?", "Veamos", "misterio", "espacio")
    with pytest.raises(ValueError, match="tras un reintento"):
        gen.verificar(ctx, tema, guion, BRIEF)
    assert len(client.prompts) == 2
    assert "La salida anterior fue inválida" in client.prompts[1]


def test_verifier_rejects_dubious_claim():
    client = FakeClient([json.dumps({"afirmaciones": ["Hay agua en Marte desde 1990"],
                                     "dudosas": ["Hay agua en Marte desde 1990"], "motivos": []})])
    ctx = ContextoVideo("v", "largo", "hoy", ".")
    tema = Tema("Caso", "caso-1", "espacio", ["caso"])
    guion = Guion("Hay agua en Marte desde 1990.", "¿Qué pasó?", "Veamos", "misterio", "espacio")
    resultado = VerificadorLLM(client).verificar(ctx, tema, guion, BRIEF)
    assert resultado.aprobado is False
    assert "dudosas" in resultado.motivos[0].lower()
