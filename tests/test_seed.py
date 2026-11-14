"""Pruebas de la carga: generación, validación y escenarios."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from pathlib import Path

from src.loading import extra_data
from src.loading.validation import DATASETS, leer_directorio, maximos_contadores, validar_y_transformar

ORIGINALES = Path(__file__).resolve().parent.parent / "data" / "original"
BASE = date(2026, 10, 13)


def _crudo(tmp_path: Path, base: date = BASE, con_adicionales: bool = True):
    crudo = leer_directorio(ORIGINALES, "original")
    if con_adicionales:
        extra_data.escribir_csv(tmp_path, base)
        extra = leer_directorio(tmp_path, "additional")
        for d in DATASETS:
            crudo[d] = crudo[d] + extra[d]
    return crudo


def test_originales_validan_y_se_transforman() -> None:
    docs, rep = validar_y_transformar(leer_directorio(ORIGINALES, "original"))
    assert rep.ok, rep.errores
    assert len(docs["ventas"]) == 16 and len(docs["clientes"]) == 8
    venta = next(v for v in docs["ventas"] if v["_id"] == "V002")
    assert len(venta["items"]) == 2 and venta["total"] == 5750
    assert venta["origen"] == "csv" and venta["id_operacion"] is None
    assert venta["stock_aplicado"] is True and venta["asignaciones_stock"] == []
    pendiente = next(v for v in docs["ventas"] if v["_id"] == "V011")
    assert pendiente["stock_aplicado"] is False
    assert docs["recetas"][0]["fecha_emision"].tzinfo is not None  # BSON Date UTC


def test_adicionales_tienen_al_menos_10_filas_por_csv(tmp_path: Path) -> None:
    conteos = extra_data.escribir_csv(tmp_path, BASE)
    assert set(conteos) == set(DATASETS)
    assert all(n >= 10 for n in conteos.values()), conteos


def test_adicionales_son_reproducibles(tmp_path: Path) -> None:
    assert extra_data.generar(BASE) == extra_data.generar(BASE)
    otra = extra_data.generar(BASE + timedelta(days=1))
    assert otra["ventas"] != extra_data.generar(BASE)["ventas"]  # las fechas relativas se desplazan


def test_union_originales_y_adicionales_es_valida(tmp_path: Path) -> None:
    docs, rep = validar_y_transformar(_crudo(tmp_path))
    assert rep.ok, rep.errores
    assert len(docs["ventas"]) == 32 and len(docs["clientes"]) == 18
    assert maximos_contadores(_crudo(tmp_path)) == {"cliente": 18, "venta": 32, "detalle": 40}


def test_escenarios_borde_presentes(tmp_path: Path) -> None:
    docs, _ = validar_y_transformar(_crudo(tmp_path))
    estados = {v["estado"] for v in docs["ventas"]}
    assert {"Completada", "Pendiente", "Anulada"} <= estados
    hoy_bson = date(2026, 10, 13)
    lotes = docs["stock_lotes"]
    assert any(l["unidades"] < 50 for l in lotes)
    assert any(l["vencimiento"].date() < hoy_bson for l in lotes)  # vencido
    assert sum(1 for l in lotes if l["_id"] in ("L019", "L020", "L021")) == 3  # FEFO con varios lotes
    assert any(not c["activo"] for c in docs["clientes"])
    droguerias = {s["_id"] for s in docs["sucursales"] if s["tipo"] == "Droguería"}
    assert any(f["id_sucursal"] in droguerias for f in docs["farmaceuticos"])
    prolongadas_vencidas = [r for r in docs["recetas"] if r["tipo"] == "Tratamiento prolongado"
                            and r["estado"] == "Vigente" and r["proxima_dispensa"].date() < hoy_bson]
    assert len(prolongadas_vencidas) >= 2


def test_rechaza_total_inconsistente_dni_repetido_y_receta_invalida(tmp_path: Path) -> None:
    crudo = _crudo(tmp_path, con_adicionales=False)
    mal = copy.deepcopy(crudo)
    mal["ventas"][0][1]["total"] = "1"
    mal["clientes"][1][1]["dni"] = mal["clientes"][0][1]["dni"]
    mal["recetas"][1][1]["dispensas_realizadas"] = "9"
    mal["productos"][0][1]["precio_unit"] = "12,5"
    mal["ventas"][2][1]["id_cliente"] = "C999"
    _, rep = validar_y_transformar(mal)
    texto = "\n".join(rep.errores)
    assert not rep.ok
    for esperado in ("no coincide con la suma", "dni", "dispensas_realizadas", "no es un entero", "C999"):
        assert esperado in texto, texto
