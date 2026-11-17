from datetime import date, datetime, time, timedelta, timezone

from canal.quota import (CuotaDiaria, Video, dias_de_reserva, necesita_reponer,
                         planificar_subidas, Publicacion)


def test_dia_completo_cabe_en_cuota_y_respeta_margen():
    inicio = date(2026, 11, 10)
    videos = [Video("l", "largo")] + [Video(f"s{i}", "short") for i in range(3)]
    plan = planificar_subidas(videos, inicio, reserva_dias=(5, 7), margen_unidades=1500,
                              ahora=datetime(2026, 11, 9, tzinfo=timezone.utc))
    assert len(plan.publicaciones) == 4
    assert all(p.dia_de_subida == inicio for p in plan.publicaciones)


def test_cuota_se_reinicia_a_medianoche_pacifico():
    reloj = lambda: datetime(2026, 1, 1, 7, 59, tzinfo=timezone.utc)
    cuota = CuotaDiaria(reloj=reloj)
    cuota.registrar("lectura", 8)
    assert cuota.usadas(date(2025, 12, 31)) == 8
    assert cuota.usadas(date(2026, 1, 1)) == 0
    reloj2 = lambda: datetime(2026, 1, 1, 8, 1, tzinfo=timezone.utc)
    cuota.reloj = reloj2
    cuota.registrar("lectura", 2)
    assert cuota.usadas(date(2026, 1, 1)) == 2


def test_difiere_si_no_cabe_y_omite_horarios_pasados():
    videos = [Video("l", "largo")] + [Video(f"s{i}", "short") for i in range(3)]
    plan = planificar_subidas(videos, date(2026, 11, 10), margen_unidades=4000,
                              ahora=datetime(2026, 11, 10, 20, tzinfo=timezone.utc))
    assert any("difiere" in aviso for aviso in plan.avisos)
    assert all(p.fecha_publicacion > datetime(2026, 11, 10, 20, tzinfo=timezone.utc) for p in plan.publicaciones)


def test_horas_de_publicacion_correctas_y_reserva():
    videos = [Video("l", "largo")] + [Video(f"s{i}", "short") for i in range(3)]
    plan = planificar_subidas(videos, date(2026, 11, 10), reserva_dias=(5, 7),
                              ahora=datetime(2026, 11, 9, tzinfo=timezone.utc))
    horas = {p.video_key: p.fecha_publicacion.strftime("%H:%M") for p in plan.publicaciones}
    assert horas == {"l": "18:00", "s0": "12:00", "s1": "18:00", "s2": "21:00"}
    assert all(date(2026, 11, 10) <= p.dia_de_subida <= date(2026, 11, 17) for p in plan.publicaciones)


def test_propiedades_lote_de_14_dias_y_gasto_de_subida():
    videos = [Video(f"l{i}", "largo") for i in range(14)] + [Video(f"s{i}", "short") for i in range(42)]
    margen = 1500
    hoy = date(2026, 11, 9)
    plan = planificar_subidas(videos, hoy, reserva_dias=(5, 14), margen_unidades=margen,
                              ahora=datetime(2026, 11, 9, tzinfo=timezone.utc))
    tipos = {v.video_key: v.tipo for v in videos}
    por_pub = {}
    por_subida = {}
    for p in plan.publicaciones:
        assert p.fecha_publicacion.date() >= hoy
        assert p.dia_de_subida <= p.fecha_publicacion.date()
        por_pub.setdefault(p.fecha_publicacion.date(), []).append(tipos[p.video_key])
        por_subida[p.dia_de_subida] = por_subida.get(p.dia_de_subida, 0) + 1650
    assert all(dia.count("largo") <= 1 and dia.count("short") <= 3 for dia in por_pub.values())
    assert all(gasto <= 10_000 - margen for gasto in por_subida.values())


def test_dias_de_reserva_y_reponer():
    hoy = date(2026, 11, 9)
    for dias in (3, 5, 7):
        pubs = [Publicacion(f"{d}-{i}", datetime.combine(hoy + timedelta(days=d), time(12), tzinfo=timezone.utc), hoy)
                for d in range(1, dias + 1) for i in range(4)]
        assert dias_de_reserva(pubs, hoy) == dias
        assert necesita_reponer(pubs, hoy) is (dias < 5)


def test_capacidad_insuficiente_difiere_con_aviso():
    videos = [Video("l", "largo"), Video("s", "short")]
    plan = planificar_subidas(videos, date(2026, 11, 10), reserva_dias=(0, 0), margen_unidades=9000,
                              ahora=datetime(2026, 11, 9, tzinfo=timezone.utc))
    assert not plan.publicaciones
    assert any("capacidad insuficiente" in aviso for aviso in plan.avisos)
