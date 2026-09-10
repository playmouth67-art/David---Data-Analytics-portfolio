"""Acceso a la base del ETL de visitas.

Toda consulta del servidor pasa por aquí. Dos razones:

1. Las credenciales viven en un solo lugar y se leen del entorno, nunca del
   código. Son las mismas variables que usa `etl_visitas.py`, así que el
   servidor se conecta al mismo entorno sin configuración adicional.
2. pymysql es síncrono. Envolver cada consulta en `asyncio.to_thread` evita
   bloquear el bucle de eventos del servidor MCP sin cambiar de driver ni
   apartarse del que ya usa el proceso ETL.

El servidor es de solo lectura sobre las tablas del ETL. La única escritura
que hace es en `dictamen_agente`, una tabla propia que no existe en el
esquema entregado: el agente registra ahí sus clasificaciones y no toca
nunca los datos que produjo el proceso.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Sequence

import pymysql
from pymysql.cursors import DictCursor

DB_CONFIG: dict[str, Any] = {
    "host": os.environ.get("ETL_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("ETL_DB_PORT", "3306")),
    "user": os.environ.get("ETL_DB_USER", "etl"),
    "password": os.environ.get("ETL_DB_PASSWORD", "etl"),
    "database": os.environ.get("ETL_DB_NAME", "etl_visitas"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    "connect_timeout": 10,
}

# Tablas y vistas que el servidor puede leer. Cualquier consulta fuera de
# esta lista es un error de programación, no una entrada del usuario, pero
# la lista sirve de documentación de la superficie de datos.
TABLAS_LECTURA = (
    "etl_ejecucion", "etl_archivo", "stg_visitas", "wrk_visitas",
    "estadistica", "visita", "visitante", "errores", "cat_validacion",
    "vw_bi_ejecuciones", "vw_bi_errores", "vw_bi_reporte_mensual",
    "vw_bi_calidad_diaria", "vw_bi_estatus_actual", "vw_visitante",
)


class ErrorBase(Exception):
    """Fallo al hablar con la base, con mensaje accionable para el agente."""


def _conectar() -> pymysql.connections.Connection:
    try:
        return pymysql.connect(**DB_CONFIG)
    except pymysql.err.OperationalError as e:
        codigo = e.args[0] if e.args else None
        destino = f"{DB_CONFIG['host']}:{DB_CONFIG['port']}"
        if codigo == 2003:
            raise ErrorBase(
                f"No hay respuesta de MySQL en {destino}. Verifica que la base esté "
                f"levantada (docker compose up -d) o ajusta ETL_DB_HOST y ETL_DB_PORT."
            ) from e
        if codigo == 1045:
            raise ErrorBase(
                f"Credenciales rechazadas para el usuario '{DB_CONFIG['user']}'. "
                f"Revisa ETL_DB_USER y ETL_DB_PASSWORD."
            ) from e
        if codigo == 1049:
            raise ErrorBase(
                f"La base '{DB_CONFIG['database']}' no existe. Créala corriendo "
                f"sql/01_ddl.sql, o ajusta ETL_DB_NAME."
            ) from e
        raise ErrorBase(f"No se pudo conectar a {destino}: {e}") from e


def _ejecutar(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    """Corre una consulta y devuelve las filas. Bloqueante: usar vía `consultar`."""
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params) if params else cur.execute(sql)
            return list(cur.fetchall() or [])
    except pymysql.err.ProgrammingError as e:
        if e.args and e.args[0] == 1146:
            raise ErrorBase(
                f"Falta una tabla del esquema: {e.args[1]}. Corre sql/01_ddl.sql "
                f"(y sql/06_agente_dictamenes.sql si el error menciona dictamen_agente)."
            ) from e
        raise ErrorBase(f"Consulta inválida: {e}") from e
    finally:
        conn.close()


def _escribir(sql: str, params: Sequence[Any] | None = None) -> int:
    """Ejecuta una escritura y devuelve el id generado. Bloqueante."""
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params) if params else cur.execute(sql)
            nuevo_id = cur.lastrowid
        conn.commit()
        return nuevo_id
    except pymysql.err.ProgrammingError as e:
        if e.args and e.args[0] == 1146:
            raise ErrorBase(
                "Falta la tabla dictamen_agente. Créala corriendo "
                "sql/06_agente_dictamenes.sql antes de registrar dictámenes."
            ) from e
        raise ErrorBase(f"Escritura inválida: {e}") from e
    finally:
        conn.close()


async def consultar(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    """Consulta de solo lectura, fuera del bucle de eventos."""
    return await asyncio.to_thread(_ejecutar, sql, params)


async def uno(sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
    """Primera fila de una consulta, o None si no hay resultados."""
    filas = await consultar(sql, params)
    return filas[0] if filas else None


async def escalar(sql: str, params: Sequence[Any] | None = None, default: Any = 0) -> Any:
    """Primer valor de la primera fila. Útil para conteos."""
    fila = await uno(sql, params)
    if not fila:
        return default
    return next(iter(fila.values()), default)


async def escribir(sql: str, params: Sequence[Any] | None = None) -> int:
    """Escritura, fuera del bucle de eventos. Solo se usa para dictamen_agente."""
    return await asyncio.to_thread(_escribir, sql, params)


async def resolver_ejecucion(id_ejecucion: int | None) -> int | None:
    """Devuelve el id pedido, o el de la última corrida si no se especificó.

    Existe para que todas las herramientas acepten «la última corrida» sin
    repetir la misma consulta en cada una.
    """
    if id_ejecucion is not None:
        return id_ejecucion
    return await escalar(
        "SELECT MAX(id_ejecucion) AS ultimo FROM etl_ejecucion", default=None
    )
