import pytest

from canal.render import Escena, renderizar_cuerpo


DATOS = {
    "portada": {"expediente": "07", "titulo": "La señal", "subtitulo": "Una historia"},
    "texto_clave": {"frase": "Una **señal** en el cielo"},
    "numero": {"cifra": "42", "leyenda": "Una cifra"},
    "pregunta": {"pregunta": "¿Qué ocurrió?"},
    "linea_tiempo": {"hitos": [{"fecha": "Año 1", "texto": "Inicio"}, {"fecha": "Año 2", "texto": "Hallazgo"}, {"texto": "Hoy"}]},
    "pistas": {"evidencias": [{"texto": "Rastro uno"}, {"texto": "Rastro dos"}]},
    "cierre": {"frase": "Una última idea", "adelanto": "El siguiente caso"},
}


@pytest.mark.parametrize("formato,dim", [("short", "1080px;height:1920px"), ("largo", "1920px;height:1080px")])
@pytest.mark.parametrize("tipo", DATOS)
def test_tipos_y_dimensiones(tipo, formato, dim):
    html = renderizar_cuerpo(Escena(tipo, DATOS[tipo], 5, formato=formato))
    assert dim in html
    assert "<script" not in html and "http" not in html


def test_reproducibilidad_y_variacion_de_fondo():
    for tipo in ("numero", "pregunta"):
        a = renderizar_cuerpo(Escena(tipo, DATOS[tipo], 5, seed=11))
        assert a == renderizar_cuerpo(Escena(tipo, DATOS[tipo], 5, seed=11))
        assert a != renderizar_cuerpo(Escena(tipo, DATOS[tipo], 5, seed=12))


def test_escape_y_resaltado():
    html = renderizar_cuerpo(Escena("texto_clave", {"frase": '<script>alert("x")</script> **clave**'}, 4))
    assert "&lt;script&gt;" in html and "&quot;x&quot;" in html
    assert '<span class="gold">clave</span>' in html
    assert "<script" not in html


@pytest.mark.parametrize("escena", [
    Escena("otro", {}, 3), Escena("portada", {"titulo": "x"}, 3),
    Escena("numero", {"cifra": "", "leyenda": "x"}, 3),
    Escena("pistas", {"evidencias": [{"texto": "uno"}]}, 3),
    Escena("texto_clave", {"frase": "x" * 101}, 3),
])
def test_errores_validacion(escena):
    with pytest.raises(ValueError):
        renderizar_cuerpo(escena)


def test_fondo_forzado():
    a = renderizar_cuerpo(Escena("numero", {**DATOS["numero"], "fondo": "nebulosa"}, 5))
    assert "radial-gradient(ellipse at 25% 38%" in a


@pytest.mark.parametrize("tipo,key", [("linea_tiempo", "hitos"), ("pistas", "evidencias")])
def test_listas_en_columna_con_etiqueta_previa_y_minimos(tipo, key):
    html = renderizar_cuerpo(Escena(tipo, DATOS[tipo], 5))
    assert "flex-direction:column;align-items:center;gap:28px" in html
    assert html.index("LÍNEA DE TIEMPO" if tipo == "linea_tiempo" else "LAS PISTAS") < html.index(DATOS[tipo][key][0]["texto"])
    assert f"font-size:{46 if tipo == 'linea_tiempo' else 46}px" in html
    assert "color:#e8be78" in html


def test_minimos_tipograficos_y_animaciones():
    portada = renderizar_cuerpo(Escena("portada", DATOS["portada"], 5))
    assert "font-size:138px" in portada and "font-size:48px" in portada
    assert "font-size:36px;letter-spacing:.24em;color:#e8be78" in portada
    assert "animation:pop" in portada
    numero = renderizar_cuerpo(Escena("numero", DATOS["numero"], 5))
    assert "font-size:54px" in numero and "@keyframes p13_0" in numero
    pregunta = renderizar_cuerpo(Escena("pregunta", DATOS["pregunta"], 5))
    assert "animation:pulse" in pregunta and "@keyframes p31_0" in pregunta
    cierre = renderizar_cuerpo(Escena("cierre", DATOS["cierre"], 5))
    assert "font-size:54px" in cierre and "@keyframes p51_0" in cierre


def test_planeta_paletas_por_seed_y_textos_maximos():
    planets = [renderizar_cuerpo(Escena("portada", {**DATOS["portada"], "fondo": "planeta"}, 5, seed=i, formato="short")) for i in range(4)]
    colors = [next(part for part in html.split("background:")[1:] if "radial-gradient(circle" in part).split(")", 1)[0] for html in planets]
    assert len(set(colors)) == 4
    for formato in ("short", "largo"):
        html = renderizar_cuerpo(Escena("portada", {"expediente": "X"*16, "titulo": "T"*160, "subtitulo": "S"*180}, 5, formato=formato))
        assert "overflow-wrap:anywhere" in html and "<h1" in html and "</h1>" in html

@pytest.mark.parametrize("formato,center,radius", [("short", 88, 18), ("largo", 90, 18)])
def test_planeta_fuera_de_zona_de_texto(formato, center, radius):
    html = renderizar_cuerpo(Escena("numero", {**DATOS["numero"], "fondo": "planeta"}, 5, formato=formato))
    assert "data-role='texto'" in html
    if formato == "short":
        assert f"top:{center-radius}%" not in html  # centro y radio se expresan en px
        assert "left:22px;top:1495px" in html
        assert "top:20%;height:50%" in html
    else:
        assert "left:1534px;top:346px" in html
        assert "left:8%;right:32%" in html  # caja de texto de 60% del ancho


@pytest.mark.parametrize("tipo,key", [("texto_clave", "frase"), ("pregunta", "pregunta"), ("cierre", "frase")])
def test_titulares_con_tres_tamanos_y_reduccion(tipo, key):
    for formato, base in (("short", 104), ("largo", 124)):
        short = formato == "short"
        data = dict(DATOS[tipo])
        data[key] = "Idea breve"
        html = renderizar_cuerpo(Escena(tipo, data, 5, formato=formato))
        assert f"font-size:{base}px" in html
        data[key] = "Texto largo " * (4 if short else 5)
        reduced = renderizar_cuerpo(Escena(tipo, data, 5, formato=formato))
        assert f"font-size:{88 if short else 104}px" in reduced
        data[key] = "Texto largo " * 8
        longest = renderizar_cuerpo(Escena(tipo, data, 5, formato=formato))
        assert f"font-size:{72 if short else 84}px" in longest


def test_minimos_leyenda_y_adelanto():
    for formato, minimum in (("short", 52), ("largo", 54)):
        for tipo, field in (("numero", "leyenda"), ("cierre", "adelanto")):
            data = dict(DATOS[tipo])
            data[field] = "x" * 180
            html = renderizar_cuerpo(Escena(tipo, data, 5, formato=formato))
            assert f"font-size:{minimum}px" in html or (minimum == 52 and "font-size:54px" in html)


def test_paletas_helada_y_volcanica_sin_crateres():
    for seed in (2, 3):
        html = renderizar_cuerpo(Escena("portada", {**DATOS["portada"], "fondo": "planeta"}, 5, seed=seed))
        assert "rgba(80,76,70,.45)" not in html
    assert "repeating-linear-gradient" in renderizar_cuerpo(Escena("portada", {**DATOS["portada"], "fondo": "planeta"}, 5, seed=2))


def test_imagen_fondo_y_marco(tmp_path):
    # PNG mínimo válido (1x1) para no depender de PIL ni de red.
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")
    path = tmp_path / "foto.png"
    path.write_bytes(png)
    bg = renderizar_cuerpo(Escena("portada", {**DATOS["portada"], "imagen": str(path)}, 5, seed=4))
    assert "data-role='imagen-fondo'" in bg and "data:image/png;base64," in bg
    assert "kenburns 5s" in bg and "EXPEDIENTE" in bg
    assert "<h1 class='serif'" in bg and "<h1 class='serif' style='font-size:138px" in bg
    marco = renderizar_cuerpo(Escena("texto_clave", {"frase": "La foto", "imagen": str(path), "imagen_modo": "marco"}, 5))
    assert "data-role='imagen-marco'" in marco and "top:60%;height:32%" in marco


def test_imagen_invalida_falla(tmp_path):
    path = tmp_path / "foto.gif"
    path.write_bytes(b"GIF89a")
    with pytest.raises(ValueError, match="jpg, png o webp"):
        renderizar_cuerpo(Escena("texto_clave", {"frase": "Foto", "imagen": str(path)}, 5))
