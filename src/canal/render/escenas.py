"""Escenas genéricas para guiones, con HTML seguro y animado."""
from dataclasses import dataclass
import base64
from html import escape
import mimetypes
from pathlib import Path
import random
import re

from .motor import particles, planet, starfield


@dataclass(frozen=True)
class Escena:
    tipo: str
    datos: dict
    duracion: float
    seed: int = 0
    formato: str = "short"


W_BY_FORMAT = {"short": (1080, 1920), "largo": (1920, 1080)}
MOVIMIENTOS = ("push", "pull", "push")
FONDOS = ("estrellas", "nebulosa", "planeta", "montanas")
TIPOS = {
    "portada": {"campos": {"expediente": 16, "titulo": 160, "subtitulo": 180}, "obligatorios": ("expediente", "titulo", "subtitulo")},
    "texto_clave": {"campos": {"frase": 100}, "obligatorios": ("frase",)},
    "numero": {"campos": {"cifra": 18, "leyenda": 180}, "obligatorios": ("cifra", "leyenda")},
    "pregunta": {"campos": {"pregunta": 180}, "obligatorios": ("pregunta",)},
    "linea_tiempo": {"campos": {"hitos": 180}, "obligatorios": ("hitos",), "rango": (3, 5)},
    "pistas": {"campos": {"evidencias": 180}, "obligatorios": ("evidencias",), "rango": (2, 5)},
    "cierre": {"campos": {"frase": 180, "adelanto": 180}, "obligatorios": ("frase", "adelanto")},
}

_MARK = re.compile(r"\*\*(.+?)\*\*")


def _text(value, limit, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} debe ser texto no vacío")
    if len(value) > limit:
        raise ValueError(f"{field} excede {limit} caracteres")
    out, pos = [], 0
    for match in _MARK.finditer(value):
        out.append(escape(value[pos:match.start()], quote=True))
        word = match.group(1)
        if not word.strip() or "**" in word:
            raise ValueError(f"marcado inválido en {field}")
        out.append('<span class="gold">' + escape(word, quote=True) + "</span>")
        pos = match.end()
    out.append(escape(value[pos:], quote=True))
    return "".join(out)


def _fit(value, base, floor, width, factor=0.56):
    """Reduce tipografía según longitud para textos máximos previsibles."""
    size = max(floor, min(base, int(width / max(1, len(value) * factor))))
    return f"font-size:{size}px;overflow-wrap:anywhere;word-break:normal"


def _headline_fit(value, short, width):
    sizes = (104, 88, 72) if short else (124, 104, 84)
    tier = 0 if len(value) <= 38 else 1 if len(value) <= 85 else 2
    return _fit(value, sizes[tier], sizes[2], width, .12)


def _background(kind, w, h, seed, duration):
    rng = random.Random(seed)
    anim = MOVIMIENTOS[rng.randrange(len(MOVIMIENTOS))]
    if kind == "estrellas":
        bg = starfield(w, h, n=110, seed=seed, anim=anim, dur=max(duration, .1))
    elif kind == "nebulosa":
        stars = starfield(w, h, n=90, seed=seed+71, dur=max(duration,.1)).split("</div>", 1)[1]
        bg = (f"<div class='abs' style=\"inset:-12%;background:radial-gradient(ellipse at 25% 38%,#26345b 0%,#11172f 35%,#080a17 68%,#03040a 100%);animation:drift {max(duration,.1)}s linear both\"></div>"
              f"<div class='abs' style='inset:0'>{stars}")
    elif kind == "planeta":
        palettes = (("#aaa9a2", "#626775", "#171b28", "craters"), ("#d88762", "#823d35", "#261820", "craters"), ("#c5e9f2", "#5688aa", "#10243c", "ice"), ("#ffb04d", "#b52b20", "#321119", "lava"))
        c1, c2, c3, texture = palettes[seed % len(palettes)]
        radius = int(min(w, h) * .18)
        cx, cy = (int(w * (.2 + (seed % 4) * .2)), int(h * .88)) if h > w else (int(w * .9), int(h * .5))
        extra = "background:repeating-linear-gradient(12deg,transparent 0 30px,rgba(210,245,255,.22) 32px,transparent 35px);" if texture == "ice" else ("background:repeating-linear-gradient(145deg,transparent 0 22px,rgba(255,90,25,.75) 24px,transparent 29px);" if texture == "lava" else "")
        bg = "<div class='bg'></div>" + planet(cx, cy, radius, c1, c2, c3, spin=max(duration,1), seed=seed, texture=texture, extra_css=extra)
    else:
        bg = ("<div class='bg'></div>" +
              '<div class="abs" style="left:-8%;right:-8%;bottom:-3%;height:42%;background:linear-gradient(165deg,transparent 0 13%,#293452 14% 16%,transparent 17%),linear-gradient(154deg,transparent 0 25%,#19233c 26% 43%,#0d1529 44%);filter:drop-shadow(0 -12px 30px #51658c)"></div>' +
              "<div class='abs' style='left:-5%;right:-5%;bottom:-4%;height:28%;background:linear-gradient(165deg,transparent 0 21%,#111a30 22% 42%,#080d1c 43%)'></div>" +
              "<div class='abs' style='left:-5%;right:-5%;bottom:24%;height:2px;background:#91a3ce;opacity:.25;filter:blur(9px)'></div>")
    return f"<div class='abs' style='inset:0;animation:{anim} {max(duration,.1)}s ease-in-out both'>{bg}</div>"


def renderizar_cuerpo(escena):
    if not isinstance(escena, Escena) or escena.tipo not in TIPOS:
        raise ValueError("tipo de escena desconocido")
    if escena.formato not in W_BY_FORMAT:
        raise ValueError("formato debe ser short o largo")
    if not isinstance(escena.datos, dict):
        raise ValueError("datos debe ser un dict")
    spec = TIPOS[escena.tipo]
    missing = [k for k in spec["obligatorios"] if k not in escena.datos]
    if missing:
        raise ValueError("faltan datos: " + ", ".join(missing))
    w, h = W_BY_FORMAT[escena.formato]
    data = escena.datos
    imagen_html = ""
    imagen = data.get("imagen")
    modo_imagen = data.get("imagen_modo", "fondo")
    if modo_imagen not in ("fondo", "marco"):
        raise ValueError("imagen_modo debe ser fondo o marco")
    if imagen is not None:
        ruta_imagen = Path(imagen)
        if not ruta_imagen.is_file() or ruta_imagen.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            raise ValueError("imagen debe ser un archivo jpg, png o webp existente")
        mime = mimetypes.guess_type(ruta_imagen.name)[0] or "image/jpeg"
        uri = "data:" + mime + ";base64," + base64.b64encode(ruta_imagen.read_bytes()).decode("ascii")
        if modo_imagen == "fondo":
            rng = random.Random(escena.seed)
            direction = "reverse" if escena.seed % 2 else "normal"
            imagen_html = (f"<img data-role='imagen-fondo' src='{uri}' style='position:absolute;inset:-6%;width:112%;height:112%;object-fit:cover;"
                           f"animation:kenburns{'-reverse' if direction == 'reverse' else ''} {max(escena.duracion,.1)}s ease-in-out both'>"
                           "<div data-role='velo-imagen' style='position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.68),transparent 34%,transparent 62%,rgba(0,0,0,.75));z-index:0'></div>")
        else:
            imagen_html = (f"<div data-role='imagen-marco' style='position:absolute;left:8%;right:8%;top:8%;height:48%;border:8px solid #e8be78;"
                           f"box-shadow:0 12px 48px #000b;z-index:1;overflow:hidden'><img src='{uri}' style='width:100%;height:100%;object-fit:cover'></div>")
    fondo = data.get("fondo")
    if fondo is not None and fondo not in FONDOS:
        raise ValueError("fondo desconocido")
    fondo = fondo or FONDOS[escena.seed % len(FONDOS)]
    for key, limit in spec["campos"].items():
        if key not in data:
            continue
        if key in ("hitos", "evidencias"):
            items = data[key]
            lo, hi = spec["rango"]
            if not isinstance(items, (list, tuple)) or not lo <= len(items) <= hi:
                raise ValueError(f"{key} requiere entre {lo} y {hi} elementos")
            for item in items:
                if not isinstance(item, dict) or set(item) - {"texto", "fecha"} or "texto" not in item:
                    raise ValueError(f"elemento inválido en {key}")
                _text(item["texto"], limit, key)
                if "fecha" in item:
                    _text(item["fecha"], 24, key)
        else:
            _text(data[key], limit, key)
    if not isinstance(escena.seed, int) or isinstance(escena.seed, bool):
        raise ValueError("seed debe ser entero")
    if not isinstance(escena.duracion, (int, float)) or not 0 < escena.duracion <= 120:
        raise ValueError("duracion debe estar entre 0 y 120")

    short = escena.formato == "short"
    body = _background(fondo, w, h, escena.seed, escena.duracion)
    if imagen_html and modo_imagen == "fondo":
        body += imagen_html
    elif imagen_html:
        body += imagen_html
    # El marco cae dentro de la zona segura de ambas relaciones de aspecto.
    top, height = ("20%", "50%") if short else ("20%", "58%")
    if imagen is not None and modo_imagen == "marco":
        top, height = ("60%", "32%") if short else ("61%", "30%")
    right = "32%" if not short and fondo == "planeta" else "8%"
    body += f"<div class='abs' data-role='texto' style='left:8%;right:{right};top:{top};height:{height};display:flex;align-items:center;justify-content:center;text-align:center;overflow:hidden;padding:2%;animation:{MOVIMIENTOS[escena.seed % 3]} {escena.duracion}s ease-in-out both'>"
    body += "<div class='abs' data-role='velo' style='inset:-8%;pointer-events:none;background:radial-gradient(ellipse at center,rgba(3,4,10,.55) 0%,rgba(3,4,10,0) 72%);z-index:0'></div>"
    def enter(html, index=0):
        return f"<div style='animation:pop .75s {index*.2:.2f}s both;overflow-wrap:anywhere'>{html}</div>"

    typ = escena.tipo
    if typ == "portada":
        title_size = 138 if short else 166
        subtitle_size = 48 if short else 58
        portada_enter = (lambda html, index=0: f"<div style='overflow-wrap:anywhere'>{html}</div>") if imagen is not None else enter
        sello = re.sub(r"^(?:EXPEDIENTE|EXP)\s*", "", data["expediente"], flags=re.I) if imagen is not None else data["expediente"]
        content = "<div style='width:100%'>" + portada_enter(f"<div class='lab' style='font-size:36px;letter-spacing:.24em;color:#e8be78;border:2px solid #e8be78;display:inline-block;padding:10px 18px'>EXPEDIENTE {_text(sello,16,'expediente')}</div>")
        content += portada_enter(f"<h1 class='serif' style='{_fit(data['titulo'],title_size,120 if short else 150,w*.78,.62)}'>{_text(data['titulo'],160,'titulo')}</h1>",1)
        content += enter(f"<p style='{_fit(data['subtitulo'],subtitle_size,44 if short else 52,w*.78,.54)}'>{_text(data['subtitulo'],180,'subtitulo')}</p>",2) + "</div>"
    elif typ == "texto_clave":
        content = enter(f"<div class='serif' style='{_headline_fit(data['frase'],short,w*(.54 if not short and fondo == 'planeta' else .78))}'>{_text(data['frase'],180,'frase')}</div>")
    elif typ == "numero":
        content = "<div style='width:100%'>" + enter(f"<div class='serif gold' style='font-size:{190 if short else 220}px;animation:pulse 2.4s .8s infinite'>{_text(data['cifra'],18,'cifra')}</div>") + enter(f"<p style='{_fit(data['leyenda'],54 if short else 58,52 if short else 54,w*.78,.54)}'>{_text(data['leyenda'],180,'leyenda')}</p>",1) + "</div>"
        body += particles(w//2,h//2,26,escena.seed+13,spread=min(w,h)*.38,dur=max(escena.duracion,1))
    elif typ == "pregunta":
        content = "<div style='width:100%'>" + enter("<div class='serif gold' style='font-size:220px;animation:pulse 2s .4s infinite'>?</div>") + enter(f"<div class='serif' style='{_headline_fit(data['pregunta'],short,w*(.54 if not short and fondo == 'planeta' else .78))}'>{_text(data['pregunta'],180,'pregunta')}</div>",1) + "</div>"
        body += particles(w//2,h//2,24,escena.seed+31,spread=min(w,h)*.35,dur=max(escena.duracion,1))
    elif typ in ("linea_tiempo", "pistas"):
        key = "hitos" if typ == "linea_tiempo" else "evidencias"
        heading = "LÍNEA DE TIEMPO" if typ == "linea_tiempo" else "LAS PISTAS"
        rows = []
        base = 46 if short else 58
        for i, item in enumerate(data[key]):
            txt = (_text(item.get("fecha", ""),24,"fecha") + " · ") if typ == "linea_tiempo" and item.get("fecha") else ""
            txt += _text(item["texto"],spec["campos"][key],typ)
            rows.append(f"<div style='display:flex;align-items:baseline;gap:20px;text-align:left;animation:rise .7s {(.25+i*.24):.2f}s both;{_fit(item['texto'],base,base,w*.68,.48)}'><span style='color:#e8be78;font-size:.9em;flex:none'>{'—' if typ=='linea_tiempo' else '•'}</span><span>{txt}</span></div>")
        content = f"<div style='width:100%;display:flex;flex-direction:column;align-items:center;gap:28px'><div class='lab' style='font-size:32px;animation:pop .7s both'>{heading}</div><div style='display:flex;flex-direction:column;align-items:stretch;gap:14px;width:min(100%,1000px);font-size:{base}px;line-height:1.25'>{''.join(rows)}</div></div>"
    else:
        content = "<div style='width:100%'>" + enter(f"<div class='serif' style='{_headline_fit(data['frase'],short,w*(.54 if not short and fondo == 'planeta' else .78))}'>{_text(data['frase'],180,'frase')}</div>") + enter("<div class='lab' style='margin-top:32px'>PRÓXIMO EXPEDIENTE</div>",1) + enter(f"<div style='{_fit(data['adelanto'],54 if short else 58,54,w*.78,.54)}'>{_text(data['adelanto'],180,'adelanto')}</div>",2) + "</div>"
        body += particles(w//2,h//2,26,escena.seed+51,spread=min(w,h)*.38,dur=max(escena.duracion,1))
    body += "<div style='position:relative;z-index:1;width:100%'>" + content + "</div></div><div class='abs' style='inset:0;pointer-events:none;background:radial-gradient(ellipse at center,transparent 45%,rgba(0,0,0,.55))'></div>"
    keyframes = "<style>@keyframes kenburns{from{transform:scale(1)}to{transform:scale(1.12)}}@keyframes kenburns-reverse{from{transform:scale(1.12)}to{transform:scale(1)}}</style>" if imagen is not None and modo_imagen == "fondo" else ""
    return f"{keyframes}<div style='position:absolute;inset:0;width:{w}px;height:{h}px;overflow:hidden'>{body}</div>"
