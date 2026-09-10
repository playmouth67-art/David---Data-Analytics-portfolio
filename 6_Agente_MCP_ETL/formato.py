"""Formateo compartido de respuestas.

Cada herramienta puede devolver markdown (legible para quien opera) o JSON
(procesable por otro programa). La lógica vive aquí y no en cada herramienta
para que el formato sea consistente y para no repetir el mismo bucle quince
veces.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class Formato(str, Enum):
    """Formato de salida de una herramienta."""

    MARKDOWN = "markdown"
    JSON = "json"


# Semáforo operativo. El mismo criterio que usa la vista vw_bi_ejecuciones,
# replicado aquí para poder aplicarlo a filas que no vienen de esa vista.
SEMAFORO = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}

_ICONO_ESTATUS = {
    "OK": "🟢",
    "OK_CON_ADVERTENCIAS": "🟡",
    "FALLIDO": "🔴",
    "EN_CURSO": "🔵",
    "PURGADO_ORIGEN": "🟢",
    "RESPALDADO": "🟢",
    "CARGADO": "🟢",
    "VALIDADO": "🔵",
    "DESCARGADO": "🔵",
    "RECHAZADO": "🔴",
    "RECHAZO": "🔴",
    "ADVERTENCIA": "🟡",
}


def icono(estatus: str | None) -> str:
    """Marcador visual para un estatus. Cadena vacía si no se reconoce."""
    return _ICONO_ESTATUS.get((estatus or "").upper(), "")


def _serializable(valor: Any) -> Any:
    """Convierte tipos de MySQL a algo que json.dumps acepte.

    El orden de las dos primeras comprobaciones importa: `datetime` hereda de
    `date`, así que preguntar por `date` primero atraparía también a los
    `datetime`, y `date.isoformat()` no acepta el argumento `sep`.
    """
    if isinstance(valor, datetime):
        return valor.isoformat(sep=" ")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace")
    return valor


def limpiar(filas: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normaliza filas de la base a tipos serializables."""
    return [{k: _serializable(v) for k, v in fila.items()} for fila in filas]


def a_json(datos: Any) -> str:
    """Serializa cualquier estructura, incluidas filas crudas de la base."""
    if isinstance(datos, list) and datos and isinstance(datos[0], Mapping):
        datos = limpiar(datos)
    return json.dumps(datos, indent=2, ensure_ascii=False, default=_serializable)


def _celda(valor: Any) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%Y-%m-%d %H:%M") if isinstance(valor, datetime) else valor.isoformat()
    texto = str(valor).replace("|", "\\|").replace("\n", " ")
    return texto if len(texto) <= 80 else texto[:77] + "…"


def tabla(filas: Sequence[Mapping[str, Any]], columnas: Sequence[str] | None = None) -> str:
    """Tabla markdown a partir de filas de la base.

    Devuelve un aviso legible en vez de una tabla vacía cuando no hay datos:
    una tabla sin renglones no le dice al agente si la consulta falló o si de
    verdad no hay nada.
    """
    if not filas:
        return "_Sin resultados._"
    cols = list(columnas) if columnas else list(filas[0].keys())
    lineas = ["| " + " | ".join(cols) + " |",
              "|" + "|".join("---" for _ in cols) + "|"]
    for fila in filas:
        lineas.append("| " + " | ".join(_celda(fila.get(c)) for c in cols) + " |")
    return "\n".join(lineas)


def campos(fila: Mapping[str, Any], etiquetas: Mapping[str, str]) -> str:
    """Lista de viñetas «etiqueta: valor» para el detalle de un solo registro."""
    return "\n".join(
        f"- **{etiqueta}**: {_celda(fila.get(clave))}"
        for clave, etiqueta in etiquetas.items()
        if clave in fila
    )


def bloque(titulo: str, cuerpo: str, nivel: int = 2) -> str:
    """Sección con encabezado, para componer respuestas de varias partes."""
    return f"{'#' * nivel} {titulo}\n\n{cuerpo}"


def paginacion(total: int, devueltos: int, offset: int) -> dict[str, Any]:
    """Metadatos de paginación consistentes en todas las herramientas de lista."""
    hay_mas = total > offset + devueltos
    return {
        "total": total,
        "devueltos": devueltos,
        "offset": offset,
        "hay_mas": hay_mas,
        "siguiente_offset": offset + devueltos if hay_mas else None,
    }


def nota_paginacion(pag: Mapping[str, Any]) -> str:
    """Pie de tabla que le dice al agente si faltan resultados y cómo pedirlos."""
    if not pag["hay_mas"]:
        return f"_Mostrando {pag['devueltos']} de {pag['total']}._"
    return (
        f"_Mostrando {pag['devueltos']} de {pag['total']}. "
        f"Para los siguientes, repite con offset={pag['siguiente_offset']}._"
    )
