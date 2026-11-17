import urllib.error

import pytest

from canal.narracion.speko import ClienteSpeko, ErrorSpeko, NarradorSpeko, dividir_guion
from canal.pipeline.etapas import ContextoVideo, Guion, ResultadoVerificacion, Tema


class Response:
    headers = {"Content-Type": "application/octet-stream", "X-Speko-Audio-Format": "audio/mpeg"}
    def __init__(self, payload=b"audio"): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.payload


def test_divide_on_sentence_boundaries_and_respects_limit():
    text = ("Primera oración. " * 300) + ("Final muy largo " * 400)
    pieces = dividir_guion(text, 4500)
    assert len(pieces) > 1
    assert all(len(piece) <= 4500 for piece in pieces)
    assert pieces[0].endswith(".")


def test_cache_uses_text_and_voice_and_never_calls_twice(tmp_path):
    key = tmp_path / "key"; key.write_text("secret-token")
    calls = []
    client = ClienteSpeko(key, abrir=lambda req, timeout: calls.append(req) or Response(), sleep=lambda _: None)
    cache = tmp_path / "cache"
    first = client.sintetizar("hola", cache)
    second = client.sintetizar("hola", cache)
    assert first == second and len(calls) == 1 and client.ultima_cache
    assert calls[0].get_header("Authorization") == "Bearer secret-token"
    assert calls[0].get_header("Idempotency-key")


def test_retries_transient_errors_but_does_not_leak_key(tmp_path):
    key = tmp_path / "key"; key.write_text("very-secret")
    calls, waits = [], []
    def opening(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "very-secret", {}, None)
        return Response()
    client = ClienteSpeko(key, abrir=opening, sleep=waits.append, pausa_min_s=0)
    client.sintetizar("hola", tmp_path / "cache")
    assert len(calls) == 2 and waits == [1]
    assert calls[0].get_header("Idempotency-key") == calls[1].get_header("Idempotency-key")
    def unauthorized(*args, **kwargs): raise urllib.error.HTTPError("url", 401, "very-secret", {}, None)
    client = ClienteSpeko(key, abrir=unauthorized, sleep=lambda _: None)
    with pytest.raises(ErrorSpeko) as exc: client.sintetizar("otro", tmp_path / "cache")
    assert "very-secret" not in str(exc.value)


class FakeExecutor:
    def __init__(self): self.commands = []
    def run(self, args, **kwargs): self.commands.append(args); return None
    def check_output(self, args): return b"60.0"


def test_limit_aborts_before_reading_key_or_calling(tmp_path):
    key = tmp_path / "missing-key"
    calls = []
    client = ClienteSpeko(key, abrir=lambda *a, **k: calls.append(1))
    narrator = NarradorSpeko(client)
    ctx = ContextoVideo("v", "short", "hoy", tmp_path)
    script = Guion("x" * 3001, "", "", "", "")
    with pytest.raises(ErrorSpeko, match="máximo"):
        narrator.narrar(ctx, Tema("", "", "", []), script, ResultadoVerificacion(True, []))
    assert calls == [] and not key.exists()


def test_registers_cost_from_new_audio_duration_only(tmp_path):
    key = tmp_path / "key"; key.write_text("secret")
    costs, calls = [], []
    client = ClienteSpeko(key, abrir=lambda req, timeout: calls.append(req) or Response(), sleep=lambda _: None,
                         registrar_uso=costs.append)
    executor = FakeExecutor()
    narrator = NarradorSpeko(client, ejecutor=executor)
    ctx = ContextoVideo("video", "short", "hoy", tmp_path)
    script = Guion("Hola mundo.", "", "", "", "")
    result = narrator.narrar(ctx, Tema("", "", "", []), script, ResultadoVerificacion(True, []))
    assert result.duracion == 60
    assert result.costo_usd == pytest.approx(.045) and costs == [.045]
    narrator.narrar(ctx, Tema("", "", "", []), script, ResultadoVerificacion(True, []))
    assert len(calls) == 1 and costs[-1] == 0
