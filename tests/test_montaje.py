import json
import re
import struct
import shutil
import wave
import zlib
from pathlib import Path
from types import SimpleNamespace

from canal.render import (Escena, PlanVideo, RenderConfig, Segmento, montar,
                          narrar_falso, repartir_en_tomas, verificar_salida)


class Fake:
    def __init__(self, durations=None, probe=None):
        self.durations = durations or {}
        self.probe = probe
        self.commands = []

    def check_output(self, args, **kwargs):
        return str(self.durations.get(str(args[-1]), 5.0)).encode()

    def run(self, args, **kwargs):
        self.commands.append(args)
        if "-show_streams" in args:
            return SimpleNamespace(stdout=json.dumps(self.probe), stderr="")
        if any("loudnorm=" in str(a) for a in args):
            return SimpleNamespace(stdout="", stderr='{"input_i":"-16.0"}')
        return SimpleNamespace(stdout="", stderr="")


def test_repartir_en_tomas_duracion_y_limites(tmp_path):
    audio = tmp_path / "n.wav"
    fake = Fake({str(audio): 17.0})
    seg = Segmento("una frase", audio, Escena("texto_clave", {"frase": "Idea"}, 17, seed=8))
    tomas = repartir_en_tomas([seg], max_toma=7, min_toma=4, ejecutor=fake)
    assert len(tomas) == 3
    assert all(4 <= t.duracion <= 7 for t in tomas)
    assert sum(t.duracion for t in tomas) == 17
    assert len({t.seed for t in tomas}) == 3
    assert len({t.camara for t in tomas}) > 1


def test_narracion_falsa_wav_valido(tmp_path):
    out = narrar_falso("abcdefghij", tmp_path / "voz.wav", caracteres_por_segundo=10)
    with wave.open(str(out), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 8000
        assert abs(wav.getnframes() / wav.getframerate() - 1.0) < .001


def test_montar_genera_comandos_por_formato_y_eventos(tmp_path):
    for formato, dims, size, pos in [("largo", (1920,1080), "230", "W-w-34:30"),
                                     ("short", (1080,1920), "150", "(W-w)/2:70")]:
        wav = tmp_path / f"{formato}.wav"
        narrar_falso("Esta es una frase bastante corta", wav, caracteres_por_segundo=7)
        sticker = tmp_path / "sticker.png"
        def png(path):
            raw = b"\x00\xff\xff\xff\xff"
            def chunk(kind, data): return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
            path.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">2I5B",1,1,8,6,0,0,0))+chunk(b"IDAT",zlib.compress(raw))+chunk(b"IEND",b""))
        png(sticker)
        escena = Escena("texto_clave", {"frase": "Una idea clara"}, 5, formato=formato)
        segs = [Segmento("una frase para subtítulos grandes", wav, escena),
                Segmento("impacto final", wav, escena, True)]
        plan = PlanVideo(formato, segs, tmp_path/"musica.wav", tmp_path/"whoosh.wav",
                         tmp_path/"boom.wav", sticker, "interno")
        fake = Fake({str(wav): 5.0})
        captured = []
        def renderer(shots, w, h, prefix, cfg):
            assert (w,h) == dims
            captured.extend(shots)
            return [str(tmp_path / f"{formato}_{i}.mp4") for i in range(len(shots))]
        cfg = RenderConfig(ffmpeg="ffmpeg-finto", ffprobe="ffprobe-finto")
        montar(plan, cfg, tmp_path/f"{formato}.mp4", renderizador=renderer, ejecutor=fake)
        final = next(c for c in fake.commands if "-filter_complex" in c and "-map" in c)
        graph = final[final.index("-filter_complex")+1]
        assert not any(token in graph for token in ("ass=", "drawtext", "geq", "overlay"))
        assert f"width:{size}px" in captured[0][0]
        assert "top:70px;left:50%" in captured[0][0] if formato == "short" else "top:30px;right:34px" in captured[0][0]
        assert "animation-delay" not in captured[0][0]
        assert "font:900 96px 'Inter'" in captured[0][0] if formato == "short" else "font:600 56px 'Inter'" in captured[0][0]
        html = captured[0][0]
        match = re.search(r'<div data-layer="subtitulos" style="([^"]+)"', html)
        assert match
        box = match.group(1)
        top = int(re.search(r"top:(\d+)px", box).group(1))
        height = int(re.search(r"height:(\d+)px", box).group(1))
        canvas_h = dims[1]
        low, high = ((.62, .74) if formato == "short" else (.80, .92))
        assert top >= canvas_h * low
        assert top + height <= canvas_h * high
        assert "text-align:center" in box and "line-height:1.05" in box
        assert html.index('data-layer="overlays"') > html.index("data-role='texto'")
        assert 'data-layer="subtitulos"' in html and 'data-layer="sticker"' in html
        assert "loudnorm=I=-16:TP=-1.5:LRA=11" in graph
        assert "drawtext" not in montar.__doc__
        if formato == "short": assert final[final.index("-maxrate")+1].endswith("k")
        assert sum("adelay=" in f and "volume=.55" in f for f in graph.split(";")) >= 1
        assert sum("volume=.8" in f for f in graph.split(";")) == 1
        assert ("-maxrate" in final and "-bufsize" in final) == (formato == "short")
        assert "sidechaincompress" in graph


def _probe(w=1080,h=1920,duration=20,size=2_000_000):
    return {"streams":[{"codec_type":"video","codec_name":"h264","width":w,"height":h,"avg_frame_rate":"30/1"},
                       {"codec_type":"audio","codec_name":"aac"}],
            "format":{"duration":str(duration),"size":str(size)}}


def test_verificar_salida_ok_y_fallas(tmp_path):
    fake = Fake(probe=_probe())
    ok = verificar_salida(tmp_path/"ok.mp4", "short", ejecutor=fake)
    assert ok.correcto and ok.lufs == -16
    fake.probe = _probe(w=640,h=480,duration=8,size=11_000_000)
    bad = verificar_salida(tmp_path/"bad.mp4", "short", ejecutor=fake)
    assert not bad.correcto
    assert any("Resolución" in m for m in bad.motivos)
    assert any("10 MB" in m for m in bad.motivos)
    assert any("Duración" in m for m in bad.motivos)
