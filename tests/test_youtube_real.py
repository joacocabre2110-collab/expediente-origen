from datetime import datetime, timezone

import pytest
from googleapiclient.errors import HttpError
from canal.youtube import (ClienteSeguro, ClienteYouTubeReal, CuotaYouTubeAgotada,
                           PublicacionBloqueada, SolicitudSubida, subir_idempotente)


def solicitud(**overrides):
    fields = dict(video_key="k1", titulo="Título", descripcion="Desc", etiquetas=["x"],
                  ruta_video="video.mp4", ruta_miniatura="mini.jpg", privacy_status="private",
                  publish_at=None, es_short=False)
    fields.update(overrides)
    return SolicitudSubida(**fields)


class Req:
    def __init__(self, fn): self.fn = fn
    def execute(self): return self.fn()


class FakeService:
    def __init__(self, *, fail_insert=0, quota=False, existing=None):
        self.fail_insert, self.quota, self.existing = fail_insert, quota, existing
        self.insert_calls = self.chunks = self.thumb_calls = 0
        self.videos_data = []

    def channels(self):
        return type("C", (), {"list": lambda _, **kw: Req(lambda: {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]})})()
    def playlistItems(self):
        return type("P", (), {"list": lambda _, **kw: Req(lambda: {"items": ([{"snippet": {"description": "ID-interno: k1"}, "contentDetails": {"videoId": "old-id"}}] if self.existing else [])})})()
    def videos(self):
        service = self
        class V:
            def insert(_, **kw):
                service.insert_calls += 1
                class Upload:
                    def next_chunk(inner):
                        service.chunks += 1
                        if service.quota:
                            raise HttpError(type("R", (), {"status": 403, "reason": "Forbidden"})(), b'{"reason":"quotaExceeded"}')
                        if service.fail_insert:
                            service.fail_insert -= 1
                            raise TimeoutError("timeout")
                        return None, {"id": "new-id"}
                return Upload()
            def list(_, **kw): return Req(lambda: {"items": []})
            def delete(_, **kw): return Req(lambda: {})
        return V()
    def thumbnails(self):
        return type("T", (), {"set": lambda _, **kw: Req(lambda: setattr(self, "thumb_calls", self.thumb_calls + 1) or {})})()


def test_resumable_reintenta_timeout_y_cuenta_cuota(monkeypatch, tmp_path):
    import canal.youtube.client as module
    class Media:
        def __init__(self, path, **kw): self.kw = kw
    monkeypatch.setattr(module, "MediaFileUpload", Media)
    service = FakeService(fail_insert=1)
    sleeps = []
    client = ClienteYouTubeReal(service, sleep=sleeps.append, random_fn=lambda: 0)
    assert client.subir(solicitud()) == "new-id"
    assert service.chunks == 2 and sleeps == [1]
    assert client.unidades_cuota_consumidas == 1650


def test_quota_exceeded_es_especifico_y_no_reintenta(monkeypatch):
    import canal.youtube.client as module
    monkeypatch.setattr(module, "MediaFileUpload", lambda *a, **k: object())
    service = FakeService(quota=True)
    client = ClienteYouTubeReal(service, sleep=lambda _: None)
    with pytest.raises(CuotaYouTubeAgotada):
        client.subir(solicitud())
    assert service.chunks == 1


def test_idempotencia_usa_playlist_y_evitar_subida():
    service = FakeService(existing=True)
    client = ClienteYouTubeReal(service)
    class Store:
        def registrar_publicacion(self, key, video_id): self.saved = (key, video_id)
    store = Store()
    assert subir_idempotente(client, store, solicitud()) == "old-id"
    assert service.insert_calls == 0 and store.saved == ("k1", "old-id")


@pytest.mark.parametrize("values", [
    {"privacy_status": "public"},
    {"publish_at": datetime(2030, 1, 1, tzinfo=timezone.utc)},
])
def test_cliente_seguro_bloquea_publicacion_y_programacion(values, monkeypatch):
    import canal.youtube.client as module
    monkeypatch.setattr(module, "MediaFileUpload", lambda *a, **k: object())
    service = FakeService()
    with pytest.raises(PublicacionBloqueada):
        ClienteSeguro(ClienteYouTubeReal(service)).subir(solicitud(**values))
    assert service.insert_calls == 0
