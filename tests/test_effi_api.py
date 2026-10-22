from datetime import date

import pytest

from effi_api.client import EffiClient, EffiError, EscrituraBloqueada
from effi_api.config import EffiConfig, cargar_env
from effi_api.fechas import fecha_local, rango_mensual, utc_a_bogota
from effi_api.modelos import a_decimal, a_int

from .falsos import RespuestaFalsa, SesionFalsa, ok

KEY = "k" * 36


def cliente(*respuestas, escritura=False):
    sesion = SesionFalsa(*respuestas)
    esperas = []
    c = EffiClient(EffiConfig(api_key=KEY, permitir_escritura=escritura), session=sesion, dormir=esperas.append)
    return c, sesion, esperas


def test_envia_la_key_como_bearer_y_no_la_imprime():
    c, s, _ = cliente(ok([]))
    c.listar("proveedor")
    assert s.pedidos[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert s.pedidos[0]["url"] == "https://effi.com.co/api/proveedor"
    assert KEY not in repr(c.config)


def test_recorre_todas_las_paginas_de_100():
    c, s, _ = cliente(ok([{"id": "1"}], 1, 3), ok([{"id": "2"}], 2, 3), ok([{"id": "3"}], 3, 3))
    assert [r["id"] for r in c.listar_todo("proveedor")] == ["1", "2", "3"]
    assert [p["params"]["pagina"] for p in s.pedidos] == [1, 2, 3]
    assert all(p["params"]["por_pagina"] == 100 for p in s.pedidos)


def test_no_envia_filtros_vacios_y_agrega_vigente_en_transacciones():
    c, s, _ = cliente(ok([]), ok([]))
    c.listar("factura_c", desde=date(2026, 9, 1), hasta="2026-09-30", total_desde="", total_hasta=None)
    assert s.pedidos[0]["params"] == {"desde": "2026-09-01", "hasta": "2026-09-30", "vigente": 1}
    c.listar("proveedor", nombre=" ")
    assert s.pedidos[1]["params"] == {}   # los maestros no llevan vigente


def test_respeta_vigente_cero_para_las_anuladas():
    c, s, _ = cliente(ok([]))
    c.listar("nomina", vigente=0)
    assert s.pedidos[0]["params"]["vigente"] == 0


def test_factura_v_exige_desde_y_hasta():
    c, s, _ = cliente()
    with pytest.raises(ValueError, match="desde y hasta"):
        c.listar("factura_v", desde="2026-09-01")
    assert s.pedidos == []


def test_buzon_exige_desde_y_maximo_31_dias():
    c, _, _ = cliente(ok([]))
    with pytest.raises(ValueError, match="exige desde"):
        c.listar("documento_ebill_proveedor")
    with pytest.raises(ValueError, match="31 días"):
        c.listar("documento_ebill_proveedor", desde="2026-08-01", hasta="2026-09-01")
    c.listar("documento_ebill_proveedor", desde="2026-08-01", hasta="2026-08-31")


def test_429_espera_retry_after_y_reintenta_los_get():
    c, s, esperas = cliente(RespuestaFalsa(429, {"ok": False, "mensaje": "límite"}, {"Retry-After": "7"}), ok([{"id": "1"}]))
    assert c.listar("cliente").data == [{"id": "1"}]
    assert esperas == [7.0] and len(s.pedidos) == 2


def test_429_se_rinde_despues_de_3_reintentos():
    c, s, esperas = cliente(*[RespuestaFalsa(429, {"ok": False, "mensaje": "límite"}, {"Retry-After": "1"})] * 4)
    with pytest.raises(EffiError) as e:
        c.listar("cliente")
    assert e.value.status == 429 and len(esperas) == 3 and len(s.pedidos) == 4


def test_un_post_sin_idempotency_key_no_se_reintenta():
    c, s, esperas = cliente(RespuestaFalsa(429, {"ok": False, "mensaje": "límite"}, {"Retry-After": "1"}), escritura=True)
    with pytest.raises(EffiError):
        c.crear("proveedor", {"id": "900111222"})
    assert len(s.pedidos) == 1 and esperas == []


def test_un_post_con_idempotency_key_si_se_reintenta():
    c, s, _ = cliente(RespuestaFalsa(429, {"ok": False}, {"Retry-After": "1"}), RespuestaFalsa(201, {"ok": True, "data": {"id": "5"}}), escritura=True)
    assert c.crear("factura_v", {"cliente": "10"}, idempotency_key="pedido-web-123") == {"id": "5"}
    assert s.pedidos[1]["json"]["idempotency_key"] == "pedido-web-123"


def test_401_y_403_en_espanol():
    c, _, _ = cliente(RespuestaFalsa(401, {"ok": False, "mensaje": "Unauthorized"}), RespuestaFalsa(403, {"ok": False, "mensaje": "Sin permiso sobre Nóminas"}))
    with pytest.raises(EffiError, match="renuévela en Administración → Usuarios"):
        c.listar("cliente")
    with pytest.raises(EffiError, match="Sin permiso sobre Nóminas"):
        c.listar("cliente")


def test_error_de_validacion_trae_el_mensaje_de_effi():
    c, _, _ = cliente(RespuestaFalsa(400, {"ok": False, "mensaje": "El campo t_regimen_iva es obligatorio"}))
    with pytest.raises(EffiError, match="t_regimen_iva"):
        c.listar("proveedor")


def test_la_escritura_esta_bloqueada_por_defecto():
    c, s, _ = cliente()
    for f in (lambda: c.crear("proveedor", {}), lambda: c.modificar("cliente", {}), lambda: c.anular("factura_v", {"observacion_anular": "x"})):
        with pytest.raises(EscrituraBloqueada):
            f()
    assert s.pedidos == []


def test_transacciones_exigen_idempotency_key_y_observacion_al_anular():
    c, _, _ = cliente(escritura=True)
    with pytest.raises(ValueError, match="8 a 36"):
        c.crear("factura_v", {}, idempotency_key="corta")
    with pytest.raises(ValueError, match="observacion_anular"):
        c.anular("nomina", {"id": "3"}, idempotency_key="anular-nomina-3")


def test_resumen_solo_para_facturas():
    c, s, _ = cliente(ok([{"cliente": "A", "total": "10"}]))
    assert c.resumen("factura_c", "proveedor", desde="2026-09-01")[0]["cliente"] == "A"
    assert s.pedidos[0]["params"]["agrupar_por"] == "proveedor"
    with pytest.raises(ValueError):
        c.resumen("nomina", "empleado")


def test_rango_mensual_en_tramos_de_31_dias():
    tramos = list(rango_mensual("2026-01-01", "2026-03-15"))
    assert tramos[0] == (date(2026, 1, 1), date(2026, 1, 31))
    assert tramos[-1][1] == date(2026, 3, 15)
    assert all((fin - ini).days < 31 for ini, fin in tramos)
    assert [t for t in rango_mensual("2026-09-01", "2026-09-01")] == [(date(2026, 9, 1), date(2026, 9, 1))]


def test_fechas_utc_a_colombia():
    assert fecha_local("2026-10-01 03:00:00") == date(2026, 9, 30)   # 22:00 del 30 en Bogotá
    assert utc_a_bogota("2026-10-01T15:00:00Z").hour == 10
    assert fecha_local(None) is None and fecha_local("no es fecha") is None


def test_textos_a_numeros():
    assert a_decimal("357000.0000") == 357000 and a_decimal("") == 0 and a_int("22") == 22 and a_int(None) is None


def test_config_desde_env(tmp_path, monkeypatch):
    for k in ("EFFI_API_KEY", "EFFI_PERMITIR_ESCRITURA", "EFFI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text(f"# comentario\nEFFI_API_KEY='{KEY}'\nEFFI_PERMITIR_ESCRITURA=1\n", encoding="utf-8")
    cfg = EffiConfig.desde_entorno(env)
    assert cfg.api_key == KEY and cfg.permitir_escritura and cfg.base_url == "https://effi.com.co/api"
    monkeypatch.delenv("EFFI_API_KEY")
    with pytest.raises(ValueError, match="EFFI_API_KEY"):
        EffiConfig.desde_entorno(None)
    cargar_env(tmp_path / "no-existe.env")
