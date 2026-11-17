"""Tomas verticales (1080x1920) para Shorts y armado completo de un Short."""
import re, subprocess, os, json
from pathlib import Path
from . import motor
from .motor import starfield, planet, particles
from .config import RenderConfig

W, H = 1080, 1920
CX = W // 2

def cam(inner, kind='push', d=6):
    return f"<div class='abs' style='inset:0;animation:{kind} {d}s ease-out both'>{inner}</div>"

def kicker(text, top=260, size=104, delay=.15):
    top = max(top, 250) + 20
    return f"<div class='abs kick' style='left:50px;right:50px;top:{top}px;text-align:center;font-size:{size}px;line-height:1.02;animation:pop .55s {delay}s both'>{text}</div>"

def label(text, x, y, delay=.6, size=40):
    return f"<div class='abs lab' style='left:{x}px;top:{y}px;font-size:{size}px;animation:rise .5s {delay}s both'>{text}</div>"

MOON = ('#f4f1ea', '#c9c5bc', '#3a3832')
EARTH_HOT = ('#ffd090', '#c84a1c', '#2a0804')
THEIA = ('#f2c58a', '#9a6a3a', '#2a1a0c')
EARTH = ('#9fd0ff', '#2a6aa8', '#06142a')

def s_moon(text, d, seed=1, kind='push'):
    return starfield(W, H, seed=seed, dur=d) + cam(planet(CX, 1000, 380, *MOON, spin=14, seed=seed), kind, d) + kicker(text)

def s_number(num, sub, d, seed=2):
    return starfield(W, H, seed=seed, anim='driftR', dur=d) + f"""
<div class='abs serif gold' style='left:0;right:0;top:640px;text-align:center;font-size:250px;animation:pop .6s .1s both,pulse 2s .8s infinite'>{num}</div>
<div class='abs kick' style='left:60px;right:60px;top:960px;text-align:center;font-size:76px;animation:rise .5s .5s both'>{sub}</div>"""

def s_two_planets(d, text='', seed=3):
    p = planet(380, 1150, 300, *EARTH_HOT, spin=20, texture='lava', seed=seed)
    t = planet(860, 620, 150, *THEIA, spin=12, seed=seed+1)
    move = f"<div class='abs' style='inset:0;animation:approach {d}s ease-in both'>{t}</div><style>@keyframes approach{{from{{transform:translate(260px,-100px)}}to{{transform:translate(-60px,40px)}}}}</style>"
    return starfield(W, H, seed=seed, dur=d) + cam(p + move, 'push', d) + (kicker(text, top=180, size=90) if text else '') + label('Theia', 760, 830, .8)

def s_impact(d, text='', seed=4):
    p = planet(470, 1100, 330, *EARTH_HOT, spin=8, texture='lava', seed=seed)
    flash = "<div class='abs' style='left:180px;top:420px;width:900px;height:900px;border-radius:50%;background:radial-gradient(circle,#fffbe8 0,#ffd27a 20%,rgba(255,106,26,.55) 50%,rgba(255,48,0,0) 72%);animation:fadein .15s both,pulse 1.4s .2s infinite'></div>"
    white = f"<div class='abs' style='inset:0;background:#fff;animation:flash .7s both'></div>"
    body = particles(640, 850, 260, seed, '#ffb050', 1100, 3.2) + particles(640, 850, 120, seed+9, '#fff0c0', 700, 2.4)
    return starfield(W, H, seed=seed, dur=d) + f"<div class='abs' style='inset:0;animation:shake .5s 0s 3'>{cam(p + flash + body, 'pull', d)}</div>" + white + (kicker(text, top=200, size=100, delay=.5) if text else '')

def s_ring(d, text='', seed=5):
    import random, math
    r = random.Random(seed); dots = []
    for _ in range(420):
        a = r.uniform(0, 2*math.pi); rr = r.uniform(330, 520)
        x, y = 520 + rr*math.cos(a), 520 + rr*math.sin(a)
        sz = r.uniform(2, 7)
        dots.append(f"<div class='abs' style='left:{x:.0f}px;top:{y:.0f}px;width:{sz:.1f}px;height:{sz:.1f}px;border-radius:50%;background:#d8b08a;opacity:{r.uniform(.4,1):.2f}'></div>")
    ring = f"<div class='abs' style='left:{CX-520}px;top:{1000-520}px;width:1040px;height:1040px;transform:scaleY(.32)'><div class='abs' style='inset:0;animation:rot 9s linear infinite'>{''.join(dots)}</div></div>"
    moonlet = f"<div class='abs' style='inset:0;animation:pop 1.2s {d*0.45:.2f}s both'>{planet(900, 900, 60, *MOON, spin=6, seed=seed)}</div>"
    return starfield(W, H, seed=seed, dur=d) + cam(planet(CX, 1000, 250, *EARTH_HOT, spin=16, texture='lava', seed=seed) + ring + moonlet, 'push', d) + (kicker(text, top=220) if text else '')

def s_rocks(d, seed=6):
    rock = lambda x, c1, c2, delay: f"<div class='abs' style='left:{x}px;top:880px;width:300px;height:260px;background:radial-gradient(circle at 40% 35%,{c1},{c2});clip-path:polygon(10% 30%,35% 5%,70% 8%,95% 35%,90% 75%,62% 98%,25% 92%,4% 65%);animation:pop .6s {delay}s both'></div>"
    return starfield(W, H, seed=seed, dur=d) + kicker("MISIONES <span class=gold>APOLO</span>", top=330) + rock(110, '#c8c2b8', '#3a3630', .3) + rock(670, '#b8a890', '#33291e', .6) + \
        "<div class='abs serif gold' style='left:470px;top:880px;font-size:180px;animation:pop .5s 1s both'>≈</div>" + label('Luna', 200, 1200, .8) + label('Tierra', 760, 1200, 1.0)

def s_laser(d, seed=7):
    beam = f"<div class='abs' style='left:{CX-3}px;top:560px;width:6px;height:900px;background:linear-gradient(#ff3b3b,#ff9b9b);box-shadow:0 0 30px #ff2020;transform-origin:bottom;animation:laser 1.2s .3s infinite'></div><style>@keyframes laser{{0%{{transform:scaleY(0);opacity:1}}70%{{transform:scaleY(1);opacity:1}}100%{{transform:scaleY(1);opacity:0}}}}</style>"
    return starfield(W, H, seed=seed, dur=d) + cam(planet(CX, 430, 170, *MOON, spin=10, seed=seed) + beam + planet(CX, 1900, 560, *EARTH, spin=30, seed=seed+2), 'pull', d) + label('Espejos del Apolo', 330, 650, .5, 36)

def s_big_moon(d, text, seed=8):
    ground = "<div class='abs' style='left:0;right:0;top:1480px;bottom:0;background:linear-gradient(#1a1410,#050302);clip-path:polygon(0 8%,18% 0,36% 6%,55% 1%,75% 7%,100% 2%,100% 100%,0 100%)'></div>"
    return starfield(W, H, seed=seed, dur=d) + cam(planet(CX, 1150, 620, *MOON, spin=30, seed=seed), 'push', d) + ground + kicker(text, top=220)

def s_section(d, text='', seed=9):
    blob = lambda x, y, rot, delay: f"<div class='abs' style='left:{x}px;top:{y}px;width:170px;height:110px;border-radius:50% 50% 45% 55%;background:#8a68d0;box-shadow:0 0 40px #8a68d0;transform:rotate({rot}deg);animation:pop .7s {delay}s both,pulse 1.6s {delay+.7}s infinite'></div>"
    earth = f"""<div class='abs' style='left:{CX-470}px;top:{1050-470}px;width:940px;height:940px;border-radius:50%;background:#2a5a8a'></div>
<div class='abs' style='left:{CX-450}px;top:{1050-450}px;width:900px;height:900px;border-radius:50%;background:radial-gradient(circle,#e0602a 40%,#7a2a14)'></div>
<div class='abs' style='left:{CX-250}px;top:{1050-250}px;width:500px;height:500px;border-radius:50%;background:radial-gradient(circle,#fff0b0,#e07020)'></div>"""
    return starfield(W, H, seed=seed, dur=d) + cam(earth + blob(150, 1150, 30, .5) + blob(760, 760, -40, .9), 'push', d) + label('Bajo África', 90, 1340, 1.0) + label('Bajo el Pacífico', 600, 660, 1.3) + (kicker(text, top=180, size=92) if text else '')

def s_question(d, text, seed=10):
    return starfield(W, H, seed=seed, dur=d) + cam(planet(CX, 1050, 300, *THEIA, spin=10, seed=seed), 'pull', d) + \
        "<div class='abs serif gold' style='left:0;right:0;top:820px;text-align:center;font-size:360px;opacity:.9;animation:pop .6s .2s both,pulse 1.8s .8s infinite'>?</div>" + kicker(text, top=260)

# ---------- armado ----------
def ts(t):
    return f'{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}'

def chunks(text, maxc=16):
    words = text.split(); out = []; cur = ''
    for w in words:
        if len(cur) + len(w) + 1 > maxc and cur:
            out.append(cur); cur = w
        else:
            cur = (cur + ' ' + w).strip()
        if re.search(r'[.?!:,]$', w):
            out.append(cur); cur = ''
    if cur: out.append(cur)
    return out

def build_short(name, wav, sentences, shot_fns, sticker=None, impact_index=None, workdir='.', *, cfg=None, render_fn=None):
    """sentences: lista de frases narradas (en orden); shot_fns: una función f(d)->html por frase."""
    cfg = cfg or RenderConfig(dir_trabajo=workdir, ruta_sticker=sticker or 'sticker.png')
    runner = cfg.executor or subprocess
    root = Path(cfg.dir_trabajo)
    root.mkdir(parents=True, exist_ok=True)
    wav = Path(wav)
    if not wav.is_absolute(): wav = root / wav
    sticker = Path(sticker or cfg.ruta_sticker)
    if not sticker.is_absolute(): sticker = root / sticker
    def file(suffix): return root / f'{name}{suffix}'
    dur = float(runner.check_output([cfg.ffprobe,'-v','error','-show_entries','format=duration','-of','csv=p=0',str(wav)]).decode())
    LEAD, TAIL = 0.25, 0.9
    tot_chars = sum(len(s) for s in sentences)
    ds = [dur * len(s) / tot_chars for s in sentences]
    ds[0] += LEAD; ds[-1] += TAIL
    shots = [(fn(d), d) for fn, d in zip(shot_fns, ds)]
    render = render_fn or motor.render_shots
    files = render(shots, W, H, str(root / f'{name}_toma'), cfg)
    lista = file('_lista.txt')
    lista.write_text('\n'.join(f"file '{f}'" for f in files))
    runner.run([cfg.ffmpeg,'-y','-v','error','-f','concat','-safe','0','-i',str(lista),'-c','copy',str(file('_v.mp4'))], check=True)
    total = sum(ds)
    # sonido: narración + música con pulso + whoosh en cada corte + golpe en el impacto
    motor.music(file('_m.wav'), total, pulse=True, cfg=cfg)
    whoosh_path, boom_path = cfg.ruta_efectos / 'whoosh.wav', cfg.ruta_efectos / 'boom.wav'
    if not whoosh_path.exists(): motor.whoosh(whoosh_path, cfg=cfg); motor.boom(boom_path, cfg=cfg)
    cuts = []; t = 0
    for d in ds[:-1]:
        t += d; cuts.append(t)
    inputs = ['-i', str(wav), '-i', str(file('_m.wav'))]
    fx = []; k = 2
    for c in cuts:
        inputs += ['-i', str(whoosh_path)]; fx.append(f'[{k}]adelay={int((c-0.3)*1000)}|{int((c-0.3)*1000)}[f{k}]'); k += 1
    if impact_index is not None:
        st = sum(ds[:impact_index])
        inputs += ['-i', str(boom_path)]; fx.append(f'[{k}]adelay={int(st*1000)}|{int(st*1000)}[f{k}]'); k += 1
    mix = f"[0]aresample=48000,aformat=channel_layouts=stereo,adelay={int(LEAD*1000)}|{int(LEAD*1000)},apad=pad_dur={TAIL}[n];[1]volume=0.6[m];" + ';'.join(fx) + ';' + \
        '[n][m]' + ''.join(f'[f{i}]' for i in range(2, k)) + f'amix=inputs={k}:normalize=0:duration=first,alimiter=limit=0.89[a]'
    runner.run([cfg.ffmpeg,'-y','-v','error',*inputs,'-filter_complex',mix,'-map','[a]','-c:a','aac','-b:a','160k',str(file('_a.m4a'))], check=True)
    # subtítulos grandes al centro
    ev = []; t0 = LEAD
    for i, s in enumerate(sentences):
        d = dur * len(s) / tot_chars
        cs = chunks(s); tc = sum(len(c) for c in cs); t = t0
        for c in cs:
            cd = d * len(c) / tc
            ev.append(f'Dialogue: 0,{ts(t)},{ts(t+cd-0.03)},Sub,,0,0,0,,{{\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)}}{c.upper()}')
            t += cd
        t0 += d
    ass = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Inter Black,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,7,3,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + '\n'.join(e.replace(',Sub,,0,0,0,,', ',Sub,,0,0,0,,{\\pos(540,1480)}') for e in ev) + '\n'
    ass_path = file('.ass'); ass_path.write_text(ass)
    tmp = file('_tmp.mp4')
    runner.run([cfg.ffmpeg,'-y','-v','error','-i',str(file('_v.mp4')),'-i',str(sticker),'-i',str(file('_a.m4a')),'-filter_complex',
        f"[1]scale=150:-1[st];[0][st]overlay=(W-w)/2:70,ass={ass_path}[v]",'-map','[v]','-map','2:a',
        '-c:v','libx264','-crf','23','-preset','veryfast','-maxrate','1600k','-bufsize','3200k','-pix_fmt','yuv420p','-c:a','copy','-shortest','-movflags','+faststart',str(tmp)], check=True)
    os.replace(tmp, file('.mp4'))
    return str(file('.mp4')), total
