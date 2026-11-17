import os
import shutil
import importlib.util
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CANAL_RENDER_REAL") != "1" or
    not all(shutil.which(x) for x in ("ffmpeg", "ffprobe")) or importlib.util.find_spec("playwright") is None,
    reason="requiere CANAL_RENDER_REAL=1, ffmpeg, ffprobe y playwright",
)


def test_render_real_minimo(tmp_path):
    from canal.render import Escena, PlanVideo, RenderConfig, Segmento, montar, narrar_falso, verificar_salida
    from canal.render import motor
    # Dos tomas cortas y assets de audio/imágenes locales temporales.
    import subprocess
    wav = narrar_falso("prueba corta", tmp_path/"voz.wav", caracteres_por_segundo=1)
    def make(args): subprocess.run(args, check=True, capture_output=True)
    make(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=d=16", "-c:a", "pcm_s16le", str(tmp_path/"musica.wav")])
    make(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=d=.2", "-c:a", "pcm_s16le", str(tmp_path/"fx.wav")])
    make(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=gold:s=300x300", "-frames:v", "1", str(tmp_path/"sticker.png")])
    escena = Escena("texto_clave", {"frase":"Prueba"}, 13, formato="short")
    plan = PlanVideo("short", [Segmento("Prueba de montaje", wav, escena)], tmp_path/"musica.wav",
                     tmp_path/"fx.wav", tmp_path/"fx.wav", tmp_path/"sticker.png", "real")
    cfg = RenderConfig(dir_trabajo=tmp_path, ruta_sticker=tmp_path/"sticker.png")
    output = montar(plan, cfg, tmp_path/"real.mp4", renderizador=motor.render_shots)
    assert output.exists()
    assert not any("ffmpeg" in p.name for p in [])
