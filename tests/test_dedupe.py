from canal.dedupe import Guion, Historial, evaluar, proxima_estructura, similitud


def guion(**cambios):
    datos = dict(video_key="v", pilar="espacio", estructura="s1",
                 gancho="Una señal extraña aparece sobre Marte",
                 intro="Hoy investigamos una señal del espacio profundo",
                 texto="Una señal extraña aparece sobre Marte y cambia todo lo que sabemos.")
    datos.update(cambios)
    return Guion(**datos)


def test_texto_identico_rechazado():
    previo = guion()
    assert not evaluar(previo, [previo]).aprobado


def test_texto_distinto_aprobado():
    previo = guion()
    nuevo = guion(video_key="nuevo", pilar="tierra", estructura="s2",
                  gancho="El bosque guarda un misterio antiguo",
                  intro="Viajamos a una isla remota para observar sus animales",
                  texto="En las montañas, una especie desconocida construye refugios bajo tierra.")
    assert evaluar(nuevo, [previo]).aprobado


def test_gancho_repetido():
    previo = guion()
    nuevo = guion(texto="Contenido completamente nuevo sobre volcanes y océanos.",
                  pilar="tierra", estructura="s2")
    assert "gancho_repetido" in evaluar(nuevo, [previo]).motivos


def test_pilar_repetido_tres_veces_seguidas():
    historial = [guion(video_key=str(i), estructura=f"s{i}") for i in range(2)]
    nuevo = guion(video_key="3", estructura="s3", texto="Tema nuevo: una montaña revela fósiles antiguos.")
    assert "pilar_repetido" in evaluar(nuevo, historial).motivos


def test_estructura_repetida_en_ventana():
    historial = [guion(estructura=f"s{i}", pilar="tierra") for i in range(5)]
    nuevo = guion(estructura="s1", pilar="sobrenatural",
                  texto="Un nuevo relato de luces cruza el cielo nocturno.")
    assert "estructura_repetida" in evaluar(nuevo, historial).motivos


def test_rotacion_estructuras():
    historial = [guion(estructura="a"), guion(estructura="b"), guion(estructura="a")]
    assert proxima_estructura(historial, ["a", "b", "c"]) == "c"


def test_normalizacion_tildes_y_puntuacion():
    assert similitud("Árboles, bajo el cielo estrellado.", "arboles bajo el cielo estrellado") == 1.0
