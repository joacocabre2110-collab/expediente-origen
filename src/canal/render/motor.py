"""Motor de animación: cada toma es HTML con animaciones CSS.
Se filma cuadro por cuadro fijando el tiempo de todas las animaciones (Web Animations API),
así el resultado es determinista. Uso: render_shots(shots, W, H, salida_prefijo)."""
import asyncio, random, math, subprocess, os
from .config import RenderConfig

def _run(cfg, args, **kwargs):
    return (cfg.executor or subprocess).run(args, **kwargs)

BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:%(W)dpx;height:%(H)dpx;overflow:hidden;background:#03040a;font-family:Inter,sans-serif;color:#f3efe6}
.abs{position:absolute}
.bg{position:absolute;inset:-10%%;background:radial-gradient(ellipse at 60%% 40%%,#141d3a 0%%,#070912 55%%,#020308 100%%)}
.vig{position:absolute;inset:0;background:radial-gradient(ellipse at center,transparent 50%%,rgba(0,0,0,.8) 100%%);pointer-events:none}
.kick{font-weight:900;text-transform:uppercase;letter-spacing:-.01em;text-shadow:0 6px 0 #000,0 0 30px rgba(0,0,0,.9)}
.gold{color:#ffb547}
.serif{font-family:'GFS Baskerville',serif}
.lab{font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#ffb547}
@keyframes drift{from{transform:translate(0,0) scale(1.05)}to{transform:translate(-4%%,-2%%) scale(1.12)}}
@keyframes driftR{from{transform:translate(-4%%,0) scale(1.12)}to{transform:translate(0,-2%%) scale(1.05)}}
@keyframes tw{0%%,100%%{opacity:.25}50%%{opacity:1}}
@keyframes pop{0%%{transform:scale(.6);opacity:0}60%%{transform:scale(1.08);opacity:1}100%%{transform:scale(1);opacity:1}}
@keyframes rise{from{transform:translateY(40px);opacity:0}to{transform:translateY(0);opacity:1}}
@keyframes spin{from{transform:translateX(0)}to{transform:translateX(-50%%)}}
@keyframes rot{from{transform:rotate(0)}to{transform:rotate(360deg)}}
@keyframes pulse{0%%,100%%{transform:scale(1);opacity:.85}50%%{transform:scale(1.06);opacity:1}}
@keyframes push{from{transform:scale(1)}to{transform:scale(1.18)}}
@keyframes pull{from{transform:scale(1.18)}to{transform:scale(1)}}
@keyframes shake{0%%,100%%{transform:translate(0,0)}20%%{transform:translate(-14px,8px)}40%%{transform:translate(12px,-10px)}60%%{transform:translate(-8px,-6px)}80%%{transform:translate(6px,10px)}}
@keyframes flash{0%%{opacity:1}100%%{opacity:0}}
@keyframes fadein{from{opacity:0}to{opacity:1}}
"""

def starfield(W, H, n=260, seed=1, anim='drift', dur=8):
    r = random.Random(seed)
    s = []
    for _ in range(n):
        x, y = r.uniform(0, W*1.2), r.uniform(0, H*1.2)
        sz = r.choice([1, 1, 1.5, 2, 2, 3])
        d = r.uniform(1.5, 4); dl = r.uniform(0, 3)
        s.append(f"<div class='abs' style='left:{x:.0f}px;top:{y:.0f}px;width:{sz}px;height:{sz}px;border-radius:50%;background:#fff;animation:tw {d:.1f}s {-dl:.1f}s infinite'></div>")
    return f"<div class='bg'></div><div class='abs' style='inset:-10%;animation:{anim} {dur}s linear both'>{''.join(s)}</div>"

def planet(cx, cy, R, c1, c2, c3, spin=24, texture='craters', seed=3, extra_css=''):
    """Planeta que gira: una textura del doble de ancho se desliza dentro de un círculo."""
    r = random.Random(seed)
    spots = []
    for _ in range(26 if texture == 'craters' else 18):
        x, y = r.uniform(0, 4*R), r.uniform(0, 2*R)
        sr = r.uniform(.05, .16)*R
        if texture == 'craters':
            spots.append(f"<div class='abs' style='left:{x:.0f}px;top:{y:.0f}px;width:{2*sr:.0f}px;height:{2*sr:.0f}px;border-radius:50%;background:rgba(80,76,70,.45);box-shadow:inset 3px 3px 6px rgba(0,0,0,.35)'></div>")
        else:
            spots.append(f"<div class='abs' style='left:{x:.0f}px;top:{y:.0f}px;width:{2.6*sr:.0f}px;height:{.5*sr:.0f}px;border-radius:40%;background:rgba(255,180,70,.75);filter:blur(1px);transform:rotate({r.uniform(-40,40):.0f}deg)'></div>")
    tex = "".join(spots)
    return f"""<div class='abs' style='left:{cx-R}px;top:{cy-R}px;width:{2*R}px;height:{2*R}px;border-radius:50%;overflow:hidden;
background:radial-gradient(circle at 38% 35%,{c1},{c2} 55%,{c3});box-shadow:0 0 {R*.5:.0f}px rgba(200,210,255,.12);{extra_css}'>
<div class='abs' style='left:0;top:0;width:{4*R}px;height:{2*R}px;animation:spin {spin}s linear infinite'>{tex}{tex.replace("left:", "left:calc(" + str(2*R) + "px + ").replace("px;top", "px);top") if False else tex}</div>
<div class='abs' style='inset:0;border-radius:50%;background:radial-gradient(circle at 30% 30%,transparent 40%,rgba(0,0,0,.65) 85%)'></div></div>"""

def particles(cx, cy, n, seed, color='#ffb050', spread=900, dur=3, size=(2, 9), delay=0):
    r = random.Random(seed)
    out = []
    css = []
    for i in range(n):
        a = r.uniform(0, 2*math.pi); d = r.uniform(.2, 1)*spread
        dx, dy = d*math.cos(a), d*math.sin(a)
        sz = r.uniform(*size)
        name = f"p{seed}_{i}"
        css.append(f"@keyframes {name}{{0%{{transform:translate(0,0);opacity:1}}100%{{transform:translate({dx:.0f}px,{dy:.0f}px);opacity:0}}}}")
        out.append(f"<div class='abs' style='left:{cx}px;top:{cy}px;width:{sz:.1f}px;height:{sz:.1f}px;border-radius:50%;background:{color};animation:{name} {dur*r.uniform(.7,1.2):.2f}s {delay:.2f}s cubic-bezier(.1,.7,.3,1) both'></div>")
    return "<style>" + "".join(css) + "</style>" + "".join(out)

def page(W, H, body):
    return f"<html><head><meta charset='utf-8'><style>{BASE_CSS % {'W': W, 'H': H}}</style></head><body>{body}<div class='vig'></div></body></html>"

async def _film(html, dur, W, H, out, cfg=RenderConfig()):
    from playwright.async_api import async_playwright
    FPS = cfg.fps
    N = int(round(dur*FPS))
    tmp = out[:-4] + '._tmp.mp4'
    ff = (cfg.executor or subprocess).Popen([cfg.ffmpeg,'-y','-v','error','-f','image2pipe','-c:v','mjpeg','-framerate',str(FPS),'-i','-',
        '-vf',f'scale={W}:{H},format=yuv420p','-c:v','libx264','-crf','19','-preset','veryfast','-pix_fmt','yuv420p','-r',str(FPS),tmp], stdin=subprocess.PIPE)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': W, 'height': H})
        await pg.set_content(html)
        await pg.evaluate("document.fonts.ready")
        await pg.evaluate("document.getAnimations().forEach(a=>a.pause())")
        for f in range(N):
            await pg.evaluate(f"(()=>{{const t={f*1000/FPS};document.getAnimations().forEach(a=>{{a.currentTime=t}})}})()")
            ff.stdin.write(await pg.screenshot(type='jpeg', quality=92))
        await b.close()
    ff.stdin.close(); ff.wait()
    if ff.returncode != 0: raise RuntimeError('ffmpeg falló en ' + out)
    os.replace(tmp, out)

def render_shots(shots, W, H, prefix, cfg=RenderConfig()):
    """shots: lista de (html_body, duracion). Devuelve lista de archivos .mp4."""
    files = []
    async def go():
        for i, (body, d) in enumerate(shots):
            out = f"{prefix}_{i:02d}.mp4"
            await _film(page(W, H, body), d, W, H, out, cfg)
            files.append(out)
    asyncio.run(go())
    return files

def whoosh(path, d=0.45, cfg=RenderConfig()):
    _run(cfg,[cfg.ffmpeg,'-y','-v','error','-f','lavfi','-i',f'anoisesrc=c=pink:d={d}:a=0.6',
        '-af',f"bandpass=f=900:w=1400,afade=t=in:d={d*0.6:.2f},afade=t=out:st={d*0.6:.2f}:d={d*0.4:.2f},volume=0.5,aformat=channel_layouts=stereo,aresample=48000",
        '-c:a','pcm_s16le',str(path)], check=True)

def boom(path, d=2.2, cfg=RenderConfig()):
    _run(cfg,[cfg.ffmpeg,'-y','-v','error','-f','lavfi','-i',f'anoisesrc=c=brown:d={d}:a=1','-f','lavfi','-i',f'sine=f=42:d={d}',
        '-filter_complex',f"[0]lowpass=f=300[a];[1]volume=0.9[b];[a][b]amix=inputs=2:normalize=0,afade=t=out:st=0.1:d={d-0.1:.2f},volume=1.2,aformat=channel_layouts=stereo,aresample=48000",
        '-c:a','pcm_s16le',str(path)], check=True)

def music(path, total, pulse=True, cfg=RenderConfig()):
    pf = "[4]volume=0.5,tremolo=f=1.1:d=0.9[x4];" if pulse else ""
    inputs = ['-f','lavfi','-i',f'sine=f=55:d={total}','-f','lavfi','-i',f'sine=f=82.4:d={total}','-f','lavfi','-i',f'sine=f=110.3:d={total}',
              '-f','lavfi','-i',f'anoisesrc=c=brown:d={total}:a=0.5','-f','lavfi','-i',f'sine=f=41.2:d={total}']
    mix = "[x0][x1][x2][x3][x4]amix=inputs=5" if pulse else "[x0][x1][x2][x3]amix=inputs=4"
    _run(cfg,[cfg.ffmpeg,'-y','-v','error',*inputs,'-filter_complex',
        f"[0]volume=0.5[x0];[1]volume=0.32,tremolo=f=0.15:d=0.6[x1];[2]volume=0.18,tremolo=f=0.1:d=0.7[x2];[3]lowpass=f=220,volume=0.35[x3];{pf}{mix}:normalize=0,lowpass=f=900,aecho=0.8:0.7:900:0.35,volume=0.22,afade=t=in:d=2,afade=t=out:st={max(total-3,0)}:d=3,aformat=channel_layouts=stereo,aresample=48000[m]",
        '-map','[m]','-c:a','pcm_s16le',str(path)], check=True)
