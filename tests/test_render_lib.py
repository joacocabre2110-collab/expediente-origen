from pathlib import Path

from canal.render import RenderConfig, build_short, chunks, page, particles, planet, starfield, ts


def test_config_defaults_are_portable():
    cfg = RenderConfig()
    assert cfg.fps == 30
    assert cfg.ffmpeg == "ffmpeg"
    assert cfg.ffprobe == "ffprobe"
    assert "home" not in str(cfg)


def test_ts_and_chunks():
    assert ts(3661.25) == "1:01:01.25"
    assert chunks("Una frase corta. Otra frase larga para dividir", 16) == [
        "Una frase corta.", "Otra frase larga", "para dividir"
    ]


def test_scene_html_strings_have_expected_dimensions():
    assert "left:0px" not in starfield(1080, 1920, n=0)
    p = planet(540, 960, 200, "#fff", "#888", "#000")
    assert "left:340px" in p and "width:400px" in p
    assert isinstance(particles(540, 960, 2, 1), str)
    html = page(1080, 1920, "body")
    assert isinstance(html, str)
    assert "width:1080px;height:1920px" in html


class FakeExecutor:
    def __init__(self):
        self.commands = []

    def check_output(self, args):
        self.commands.append(args)
        return b"2.0\n"

    def run(self, args, **kwargs):
        self.commands.append(args)
        Path(args[-1]).touch()
        return None


def test_build_short_composes_commands_without_running_tools(tmp_path):
    effects = tmp_path / "fx"
    effects.mkdir()
    (effects / "whoosh.wav").touch()
    (effects / "boom.wav").touch()
    wav = tmp_path / "voice.wav"
    wav.touch()
    fake = FakeExecutor()
    rendered = []

    def render_fn(shots, width, height, prefix, cfg):
        rendered.append((shots, width, height, prefix))
        return [f"{prefix}_00.mp4", f"{prefix}_01.mp4"]

    cfg = RenderConfig(dir_trabajo=tmp_path, ruta_sticker="brand.png", ruta_efectos=effects,
                       executor=fake)
    result, total = build_short(
        "demo", wav, ["Primera frase", "Segunda frase"],
        [lambda d: "shot one", lambda d: "shot two"], impact_index=0,
        cfg=cfg, render_fn=render_fn,
    )
    assert result == str(tmp_path / "demo.mp4")
    assert total == 3.15
    assert rendered[0][1:3] == (1080, 1920)
    assert len(fake.commands) == 5  # ffprobe y cuatro pasos ffmpeg
    assert fake.commands[0][0] == "ffprobe"
    assert all(args[0] == "ffmpeg" for args in fake.commands[1:])
    assert any("-filter_complex" in args for args in fake.commands)
    assert not any("shell" in args for args in fake.commands)
    assert (tmp_path / "demo_lista.txt").exists()
