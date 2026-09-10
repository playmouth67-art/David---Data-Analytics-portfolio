#!/usr/bin/env python3
"""Servidor MCP para el proceso ETL de visitas web de de visitas web.

Expone la operación, la auditoría y el diseño del ETL como herramientas que un
agente puede componer. La línea que ordena todo el diseño es esta:

    Lo que se puede verificar con aritmética se calcula en SQL.
    Lo que exige interpretar el negocio se le deja al agente, con la evidencia
    enfrente y el dictamen registrado para que un humano pueda revisarlo.

Ninguna herramienta le pide al modelo que cuente, cuadre o decida un estatus:
esas respuestas salen de la base. Lo que sí le toca al agente es clasificar los
casos que el ETL dejó marcados como ambiguos a propósito, y proponer esquemas
para archivos que nadie ha modelado todavía.

Superficie de herramientas, en cuatro familias:

  Operación         estado_actual · listar_ejecuciones · detalle_ejecucion
                    listar_archivos · consultar_errores · explicar_codigo
                    diagnosticar · reconciliar
  Interpretación    casos_ambiguos · registrar_dictamen · listar_dictamenes
  Ingesta           perfilar_archivo · proponer_validaciones
  Práctica          caso_practica

Configuración por entorno, con las mismas variables que usa etl_visitas.py:
ETL_DB_HOST, ETL_DB_PORT, ETL_DB_USER, ETL_DB_PASSWORD, ETL_DB_NAME.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

import db
import perfilado
from formato import (
    Formato, a_json, bloque, campos, icono, limpiar,
    nota_paginacion, paginacion, tabla,
)

mcp = FastMCP("visitas_etl_mcp")

SOLO_LECTURA = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
ESCRITURA = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}

# Tipos de ambigüedad que el ETL deja marcados a propósito. La definición
# completa de cada uno —consulta, regla aplicable y pregunta de negocio abierta—
# vive en _CONSULTAS_AMBIGUAS, más abajo. Aquí van solo las llaves porque el
# modelo de entrada las necesita antes de que el diccionario exista.
TIPOS_AMBIGUOS = (
    "badmail_con_actividad",
    "badmail_perdido_en_dedupe",
    "fecha_anterior_al_envio",
    "virales_mayor_que_total",
    "baja_con_actividad",
    "clic_sin_apertura",
)

# El enum se deriva de la tupla: agregar un tipo de ambigüedad se hace en un
# solo lugar y el esquema de entrada de la herramienta lo refleja solo.
TipoAmbiguo = Enum(
    "TipoAmbiguo",
    {"TODOS": "todos", **{k.upper(): k for k in TIPOS_AMBIGUOS}},
    type=str,
    module=__name__,
)


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------

class Base(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    response_format: Formato = Field(
        default=Formato.MARKDOWN,
        description="Formato de salida: 'markdown' para leer, 'json' para procesar",
    )


class SinArgs(Base):
    """Herramientas que no necesitan parámetros más allá del formato."""


class Ejecucion(Base):
    id_ejecucion: Optional[int] = Field(
        default=None, ge=1,
        description="Id de la corrida. Si se omite, se usa la más reciente.",
    )


class ListarEjecuciones(Base):
    estatus: Optional[str] = Field(
        default=None,
        description="Filtra por estatus: OK, OK_CON_ADVERTENCIAS, FALLIDO o EN_CURSO",
    )
    limite: int = Field(default=20, ge=1, le=200, description="Máximo de corridas a devolver")
    offset: int = Field(default=0, ge=0, description="Corridas a saltar, para paginar")

    @field_validator("estatus")
    @classmethod
    def _validar(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        validos = {"OK", "OK_CON_ADVERTENCIAS", "FALLIDO", "EN_CURSO"}
        if v.upper() not in validos:
            raise ValueError(f"estatus debe ser uno de {sorted(validos)}")
        return v.upper()


class ListarArchivos(Base):
    id_ejecucion: Optional[int] = Field(default=None, ge=1, description="Filtra por corrida")
    estatus: Optional[str] = Field(
        default=None,
        description="Filtra por estatus: DESCARGADO, VALIDADO, CARGADO, RECHAZADO, "
                    "RESPALDADO o PURGADO_ORIGEN",
    )
    limite: int = Field(default=50, ge=1, le=200, description="Máximo de archivos a devolver")
    offset: int = Field(default=0, ge=0, description="Archivos a saltar, para paginar")


class ConsultarErrores(Base):
    id_ejecucion: Optional[int] = Field(default=None, ge=1, description="Filtra por corrida")
    codigo_error: Optional[str] = Field(
        default=None, max_length=20,
        description="Filtra por código, por ejemplo 'V-03'",
    )
    severidad: Optional[str] = Field(default=None, description="RECHAZO o ADVERTENCIA")
    incluir_registro: bool = Field(
        default=False,
        description="Incluye el renglón original completo del archivo. Útil para "
                    "reprocesar un registro, pero alarga mucho la respuesta.",
    )
    limite: int = Field(default=25, ge=1, le=200, description="Máximo de incidencias")
    offset: int = Field(default=0, ge=0, description="Incidencias a saltar, para paginar")

    @field_validator("severidad")
    @classmethod
    def _sev(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v.upper() not in {"RECHAZO", "ADVERTENCIA"}:
            raise ValueError("severidad debe ser 'RECHAZO' o 'ADVERTENCIA'")
        return v.upper()


class ExplicarCodigo(Base):
    codigo_error: Optional[str] = Field(
        default=None, max_length=20,
        description="Código a explicar, por ejemplo 'V-04'. Si se omite, devuelve "
                    "el catálogo completo.",
    )


class CasosAmbiguos(Base):
    tipo: TipoAmbiguo = Field(default=TipoAmbiguo.TODOS,
                              description="Qué clase de ambigüedad buscar")
    limite: int = Field(default=15, ge=1, le=100, description="Máximo de casos por tipo")
    solo_sin_dictamen: bool = Field(
        default=False,
        description="Devuelve únicamente los casos que todavía no tienen dictamen registrado",
    )


class RegistrarDictamen(Base):
    class Clasificacion(str, Enum):
        VALIDO = "VALIDO"
        SOSPECHOSO = "SOSPECHOSO"
        ERROR_DE_ORIGEN = "ERROR_DE_ORIGEN"
        REQUIERE_NEGOCIO = "REQUIERE_NEGOCIO"

    tipo_caso: str = Field(..., min_length=3, max_length=60,
                           description="Tipo de ambigüedad, tal como lo devolvió casos_ambiguos")
    email: str = Field(..., min_length=3, max_length=320, description="Correo del registro dictaminado")
    fecha_envio: str = Field(..., min_length=10, max_length=25,
                             description="Fecha de envío del registro, 'YYYY-MM-DD HH:MM:SS'")
    clasificacion: Clasificacion = Field(..., description="Veredicto del agente")
    justificacion: str = Field(..., min_length=20, max_length=1000,
                               description="Por qué se clasificó así, con la evidencia que lo sostiene")
    confianza: float = Field(..., ge=0.0, le=1.0,
                             description="Qué tan seguro está el agente, de 0 a 1")


class ProponerValidaciones(Base):
    ruta: str = Field(..., min_length=1, max_length=4096,
                      description="Ruta absoluta del archivo plano ya perfilado")
    nombre_tabla: str = Field(default="stg_nueva", min_length=1, max_length=60,
                              description="Nombre de la tabla de staging a proponer")


class PerfilarArchivo(Base):
    ruta: str = Field(..., min_length=1, max_length=4096,
                      description="Ruta absoluta del archivo plano (csv, txt o tsv)")
    muestra: int = Field(default=5000, ge=100, le=100000,
                         description="Máximo de filas de datos a analizar")


class CasoPractica(Base):
    class Modo(str, Enum):
        DIAGNOSTICO = "diagnostico"
        REGLA = "regla"
        ANOMALIA = "anomalia"
        ALEATORIO = "aleatorio"

    modo: Modo = Field(default=Modo.ALEATORIO,
                       description="Tipo de caso: diagnóstico de corrida, regla de negocio, "
                                   "anomalía de datos, o uno al azar")
    mostrar_respuesta: bool = Field(
        default=False,
        description="Incluye la respuesta modelo. Déjalo en false para intentar "
                    "responder primero.",
    )


# ---------------------------------------------------------------------------
# Utilidades compartidas
# ---------------------------------------------------------------------------

def _error(e: Exception) -> str:
    """Mensaje de error accionable, uniforme en todas las herramientas."""
    if isinstance(e, db.ErrorBase):
        return f"Error: {e}"
    if isinstance(e, FileNotFoundError):
        return f"Error: {e}"
    if isinstance(e, ValueError):
        return f"Error: {e}"
    return f"Error inesperado ({type(e).__name__}): {e}"


def _salida(params: Base, datos: Any, markdown: str) -> str:
    """Devuelve JSON o markdown según lo pedido."""
    return a_json(datos) if params.response_format == Formato.JSON else markdown


async def _no_hay_corrida() -> str:
    return ("No hay ninguna corrida registrada en `etl_ejecucion`. "
            "Ejecuta el ETL al menos una vez (python3 python/etl_visitas.py) "
            "antes de consultar su estado.")


def _semaforo(fila: dict[str, Any]) -> str:
    """Clasifica una corrida con el mismo criterio que la vista vw_bi_ejecuciones."""
    leidos = fila.get("registros_leidos") or 0
    errores = fila.get("registros_error") or 0
    if fila.get("estatus") == "FALLIDO":
        return "ROJO"
    if leidos and errores > 0.05 * leidos:
        return "ROJO"
    if (fila.get("archivos_rechazados") or 0) > 0 or errores > 0:
        return "AMARILLO"
    return "VERDE"


async def _resumen_errores(id_ejecucion: int) -> list[dict[str, Any]]:
    return await db.consultar(
        """SELECT e.codigo_error, c.nombre, e.severidad, COUNT(*) AS incidencias,
                  c.accion_operacion
           FROM errores e LEFT JOIN cat_validacion c ON c.codigo_error = e.codigo_error
           WHERE e.id_ejecucion = %s
           GROUP BY e.codigo_error, c.nombre, e.severidad, c.accion_operacion
           ORDER BY e.severidad DESC, incidencias DESC""",
        (id_ejecucion,),
    )


# ---------------------------------------------------------------------------
# Familia 1 · Operación
# ---------------------------------------------------------------------------

@mcp.tool(name="visitas_estado_actual", annotations={"title": "Estado actual del ETL", **SOLO_LECTURA})
async def visitas_estado_actual(params: SinArgs) -> str:
    """Devuelve el estado de la última corrida del ETL, con semáforo y alerta de vigencia.

    Es el punto de entrada natural: contesta «¿cómo va el proceso?» en una sola
    llamada, antes de entrar a detalle. Incluye si la corrida está vencida, es
    decir si pasaron más de 26 horas sin que el ETL volviera a correr.

    Args:
        params (SinArgs): solo el formato de salida.

    Returns:
        str: markdown con encabezado de estado, métricas de la corrida y, si
        aplica, las alertas detectadas. En JSON:
        {
          "id_ejecucion": int, "estatus": str, "semaforo": "VERDE|AMARILLO|ROJO",
          "fecha_inicio": str, "fecha_fin": str|null, "duracion_segundos": int|null,
          "archivos_detectados": int, "archivos_cargados": int, "archivos_rechazados": int,
          "registros_leidos": int, "registros_cargados": int,
          "registros_error": int, "registros_advertencia": int,
          "mensaje": str|null, "horas_desde_inicio": int, "vigencia": str,
          "alertas": [str]
        }

    Examples:
        - «¿cómo está el ETL?» / «¿corrió bien anoche?» -> esta herramienta
        - Para saber POR QUÉ falló, encadena con visitas_diagnosticar
        - Para el histórico, usa visitas_listar_ejecuciones
    """
    try:
        fila = await db.uno(
            """SELECT *, TIMESTAMPDIFF(HOUR, fecha_inicio, NOW()) AS horas_desde_inicio
               FROM etl_ejecucion ORDER BY id_ejecucion DESC LIMIT 1"""
        )
        if not fila:
            return await _no_hay_corrida()

        horas = fila.get("horas_desde_inicio") or 0
        alertas: list[str] = []
        if horas > 26:
            alertas.append(f"No hay corrida desde hace {horas} horas. El proceso es diario.")
        if fila["estatus"] == "EN_CURSO":
            alertas.append(
                "La corrida sigue marcada EN_CURSO. Si el proceso ya murió, bloqueará "
                "las siguientes hasta que pasen 6 horas desde su inicio."
            )
        if fila["estatus"] == "FALLIDO":
            alertas.append("La última corrida falló. Usa visitas_diagnosticar para el detalle.")
        if (fila.get("archivos_detectados") or 0) > 0 and (fila.get("archivos_cargados") or 0) == 0:
            alertas.append(
                "Se detectaron archivos pero no se cargó ninguno. Puede ser idempotencia "
                "(todos ya procesados) o rechazo de layout."
            )

        sem = _semaforo(fila)
        datos = {**limpiar([fila])[0], "semaforo": sem,
                 "vigencia": "VENCIDA" if horas > 26 else "OK", "alertas": alertas}

        md = [
            f"# {icono(fila['estatus'])} Corrida {fila['id_ejecucion']} · {fila['estatus']}",
            "",
            campos(fila, {
                "fecha_negocio": "Fecha de negocio",
                "fecha_inicio": "Inicio",
                "fecha_fin": "Fin",
                "duracion_segundos": "Duración (s)",
                "host_ejecucion": "Host",
            }),
            "",
            "## Métricas",
            "",
            tabla([{
                "archivos detectados": fila["archivos_detectados"],
                "cargados": fila["archivos_cargados"],
                "rechazados": fila["archivos_rechazados"],
                "registros leídos": fila["registros_leidos"],
                "cargados ": fila["registros_cargados"],
                "rechazos": fila["registros_error"],
                "advertencias": fila["registros_advertencia"],
            }]),
        ]
        if fila.get("mensaje"):
            md += ["", "## Mensaje", "", f"```\n{fila['mensaje']}\n```"]
        if alertas:
            md += ["", "## Alertas", ""] + [f"- ⚠️ {a}" for a in alertas]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_listar_ejecuciones", annotations={"title": "Historial de corridas", **SOLO_LECTURA})
async def visitas_listar_ejecuciones(params: ListarEjecuciones) -> str:
    """Lista las corridas del ETL, de la más reciente a la más antigua.

    Sirve para ver tendencias: si los rechazos crecen, si la duración se dispara,
    si hay corridas que no procesaron nada.

    Args:
        params (ListarEjecuciones): filtro opcional por estatus, más límite y offset.

    Returns:
        str: markdown con tabla de corridas y nota de paginación. En JSON:
        {"total": int, "devueltos": int, "offset": int, "hay_mas": bool,
         "siguiente_offset": int|null, "ejecuciones": [{...}]}

    Examples:
        - «muéstrame las corridas fallidas» -> estatus="FALLIDO"
        - «¿cuántas veces ha corrido el proceso?» -> sin filtros, mira "total"
    """
    try:
        where, args = "", []
        if params.estatus:
            where, args = "WHERE estatus = %s", [params.estatus]

        total = await db.escalar(f"SELECT COUNT(*) AS n FROM etl_ejecucion {where}", args or None)
        filas = await db.consultar(
            f"""SELECT id_ejecucion, fecha_negocio, estatus, fecha_inicio, fecha_fin,
                       duracion_segundos, archivos_detectados, archivos_cargados,
                       archivos_rechazados, registros_leidos, registros_cargados,
                       registros_error, registros_advertencia, mensaje
                FROM etl_ejecucion {where}
                ORDER BY id_ejecucion DESC LIMIT %s OFFSET %s""",
            args + [params.limite, params.offset],
        )
        if not filas:
            filtro = f" con estatus {params.estatus}" if params.estatus else ""
            return f"No hay corridas registradas{filtro}."

        enriquecidas = [{**f, "semaforo": _semaforo(f)} for f in filas]
        pag = paginacion(total, len(filas), params.offset)
        datos = {**pag, "ejecuciones": limpiar(enriquecidas)}

        vista = [{
            "": icono(f["estatus"]),
            "id": f["id_ejecucion"],
            "estatus": f["estatus"],
            "inicio": f["fecha_inicio"],
            "seg": f["duracion_segundos"],
            "arch.": f"{f['archivos_cargados']}/{f['archivos_detectados']}",
            "leídos": f["registros_leidos"],
            "cargados": f["registros_cargados"],
            "rech.": f["registros_error"],
            "adv.": f["registros_advertencia"],
        } for f in filas]
        md = bloque("Historial de corridas", tabla(vista) + "\n\n" + nota_paginacion(pag), 1)
        return _salida(params, datos, md)
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_detalle_ejecucion", annotations={"title": "Detalle de una corrida", **SOLO_LECTURA})
async def visitas_detalle_ejecucion(params: Ejecucion) -> str:
    """Devuelve todo lo que se sabe de una corrida: métricas, archivos e incidencias.

    Junta en una sola llamada lo que de otro modo requeriría consultar
    etl_ejecucion, etl_archivo y errores por separado.

    Args:
        params (Ejecucion): id de la corrida, o la última si se omite.

    Returns:
        str: markdown con tres secciones (corrida, archivos, incidencias). En JSON:
        {"ejecucion": {...}, "archivos": [{...}], "incidencias": [{...}]}

    Examples:
        - «cuéntame de la corrida 2» -> id_ejecucion=2
        - «qué archivos entraron ayer» -> sin id, se usa la última
    """
    try:
        id_ej = await db.resolver_ejecucion(params.id_ejecucion)
        if id_ej is None:
            return await _no_hay_corrida()

        ejec = await db.uno("SELECT * FROM etl_ejecucion WHERE id_ejecucion = %s", (id_ej,))
        if not ejec:
            return (f"No existe la corrida {id_ej}. Usa visitas_listar_ejecuciones "
                    f"para ver los ids disponibles.")

        archivos = await db.consultar(
            """SELECT a.id_archivo, a.nombre_archivo, a.estatus, a.bytes,
                      a.registros_leidos, a.archivo_zip, a.motivo_rechazo,
                      LEFT(a.hash_archivo, 12) AS hash,
                      (SELECT COUNT(*) FROM estadistica s WHERE s.id_archivo = a.id_archivo)
                        AS registros_en_destino
               FROM etl_archivo a WHERE a.id_ejecucion = %s ORDER BY a.id_archivo""",
            (id_ej,),
        )
        incidencias = await _resumen_errores(id_ej)
        datos = {"ejecucion": limpiar([ejec])[0],
                 "archivos": limpiar(archivos),
                 "incidencias": limpiar(incidencias)}

        md = [f"# {icono(ejec['estatus'])} Corrida {id_ej} · {ejec['estatus']}", ""]
        md += [campos(ejec, {
            "fecha_negocio": "Fecha de negocio", "fecha_inicio": "Inicio", "fecha_fin": "Fin",
            "duracion_segundos": "Duración (s)", "host_ejecucion": "Host",
            "registros_leidos": "Registros leídos", "registros_cargados": "Registros cargados",
            "registros_error": "Rechazos", "registros_advertencia": "Advertencias",
        })]
        if ejec.get("mensaje"):
            md += ["", f"**Mensaje:** `{ejec['mensaje']}`"]

        md += ["", "## Archivos", ""]
        if archivos:
            md += [tabla([{
                "": icono(a["estatus"]), "archivo": a["nombre_archivo"], "estatus": a["estatus"],
                "hash": a["hash"], "leídos": a["registros_leidos"],
                "en destino": a["registros_en_destino"], "zip": a["archivo_zip"],
            } for a in archivos])]
            for a in archivos:
                if a.get("motivo_rechazo"):
                    md += ["", f"- `{a['nombre_archivo']}` rechazado: {a['motivo_rechazo']}"]
        else:
            md += ["_Esta corrida no registró archivos._"]

        md += ["", "## Incidencias", ""]
        md += [tabla([{
            "": icono(i["severidad"]), "código": i["codigo_error"], "regla": i["nombre"],
            "severidad": i["severidad"], "incidencias": i["incidencias"],
        } for i in incidencias]) if incidencias else "_Sin incidencias registradas._"]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_listar_archivos", annotations={"title": "Archivos procesados", **SOLO_LECTURA})
async def visitas_listar_archivos(params: ListarArchivos) -> str:
    """Lista los archivos que el ETL ha visto, con su estatus y su huella.

    El estatus es una máquina de estados: DESCARGADO, VALIDADO, CARGADO,
    RESPALDADO, PURGADO_ORIGEN, o RECHAZADO. Un archivo detenido en un estado
    intermedio dice exactamente en qué paso murió el proceso.

    Args:
        params (ListarArchivos): filtros por corrida y estatus, más paginación.

    Returns:
        str: markdown con tabla de archivos. En JSON:
        {"total": int, "devueltos": int, "offset": int, "hay_mas": bool,
         "siguiente_offset": int|null, "archivos": [{...}]}

    Examples:
        - «¿qué archivos se rechazaron?» -> estatus="RECHAZADO"
        - «¿cuáles quedaron a medias?» -> estatus="CARGADO" (no llegaron a RESPALDADO)
    """
    try:
        cond, args = [], []
        if params.id_ejecucion is not None:
            cond.append("a.id_ejecucion = %s")
            args.append(params.id_ejecucion)
        if params.estatus:
            cond.append("a.estatus = %s")
            args.append(params.estatus.upper())
        where = ("WHERE " + " AND ".join(cond)) if cond else ""

        total = await db.escalar(f"SELECT COUNT(*) AS n FROM etl_archivo a {where}", args or None)
        filas = await db.consultar(
            f"""SELECT a.id_archivo, a.id_ejecucion, a.nombre_archivo, a.estatus,
                       a.bytes, a.registros_leidos, a.fecha_deteccion, a.archivo_zip,
                       a.motivo_rechazo, LEFT(a.hash_archivo, 12) AS hash,
                       (SELECT COUNT(*) FROM estadistica s WHERE s.id_archivo = a.id_archivo)
                         AS registros_en_destino
                FROM etl_archivo a {where}
                ORDER BY a.id_archivo DESC LIMIT %s OFFSET %s""",
            args + [params.limite, params.offset],
        )
        if not filas:
            return "No hay archivos que cumplan ese filtro."

        pag = paginacion(total, len(filas), params.offset)
        datos = {**pag, "archivos": limpiar(filas)}
        vista = [{
            "": icono(f["estatus"]), "id": f["id_archivo"], "corrida": f["id_ejecucion"],
            "archivo": f["nombre_archivo"], "estatus": f["estatus"], "hash": f["hash"],
            "leídos": f["registros_leidos"], "en destino": f["registros_en_destino"],
        } for f in filas]
        md = bloque("Archivos", tabla(vista) + "\n\n" + nota_paginacion(pag), 1)
        return _salida(params, datos, md)
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_consultar_errores", annotations={"title": "Auditoría de incidencias", **SOLO_LECTURA})
async def visitas_consultar_errores(params: ConsultarErrores) -> str:
    """Consulta la tabla de auditoría: qué registros se rechazaron o se advirtieron y por qué.

    Cada incidencia trae el archivo y la línea física donde estaba el registro,
    el valor que falló, y la acción que el catálogo indica para ese código. Con
    `incluir_registro` se agrega el renglón original completo, que es lo que
    permite reprocesar un registro después de que su archivo fue purgado.

    Args:
        params (ConsultarErrores): filtros por corrida, código y severidad; bandera
            para incluir el renglón original; paginación.

    Returns:
        str: markdown con las incidencias y la acción de operación. En JSON:
        {"total": int, "devueltos": int, "offset": int, "hay_mas": bool,
         "siguiente_offset": int|null,
         "incidencias": [{"id_error": int, "nombre_archivo": str, "num_linea": int,
                          "codigo_error": str, "severidad": str, "campo": str,
                          "valor_original": str, "descripcion": str,
                          "que_significa": str, "que_hacer": str,
                          "registro_completo": str|null}]}

    Examples:
        - «¿qué correos se rechazaron?» -> codigo_error="V-03"
        - «dame los rechazos de la corrida 4 con el renglón original»
          -> id_ejecucion=4, severidad="RECHAZO", incluir_registro=true
    """
    try:
        cond, args = [], []
        if params.id_ejecucion is not None:
            cond.append("er.id_ejecucion = %s")
            args.append(params.id_ejecucion)
        if params.codigo_error:
            cond.append("er.codigo_error = %s")
            args.append(params.codigo_error.upper())
        if params.severidad:
            cond.append("er.severidad = %s")
            args.append(params.severidad)
        where = ("WHERE " + " AND ".join(cond)) if cond else ""

        total = await db.escalar(f"SELECT COUNT(*) AS n FROM errores er {where}", args or None)
        campo_registro = ", er.registro_completo" if params.incluir_registro else ""
        filas = await db.consultar(
            f"""SELECT er.id_error, er.id_ejecucion, er.nombre_archivo, er.num_linea,
                       er.codigo_error, er.severidad, er.campo, er.valor_original,
                       er.descripcion, c.nombre AS regla,
                       c.descripcion AS que_significa,
                       c.accion_operacion AS que_hacer{campo_registro}
                FROM errores er
                LEFT JOIN cat_validacion c ON c.codigo_error = er.codigo_error
                {where}
                ORDER BY er.severidad DESC, er.id_error LIMIT %s OFFSET %s""",
            args + [params.limite, params.offset],
        )
        if not filas:
            return ("No hay incidencias con ese filtro. Si esperabas resultados, revisa "
                    "que la corrida exista con visitas_listar_ejecuciones.")

        pag = paginacion(total, len(filas), params.offset)
        datos = {**pag, "incidencias": limpiar(filas)}

        vista = [{
            "": icono(f["severidad"]), "código": f["codigo_error"], "archivo": f["nombre_archivo"],
            "línea": f["num_linea"], "campo": f["campo"], "valor": f["valor_original"],
        } for f in filas]
        acciones = {(f["codigo_error"], f["regla"], f["que_hacer"]) for f in filas}
        md = [bloque("Incidencias", tabla(vista) + "\n\n" + nota_paginacion(pag), 1),
              "", "## Acción indicada por el catálogo", ""]
        md += [f"- **{cod}** ({nombre}): {accion}" for cod, nombre, accion in sorted(acciones)]
        if params.incluir_registro:
            md += ["", "## Renglones originales", ""]
            md += [f"- `{f['nombre_archivo']}:{f['num_linea']}` → `{f.get('registro_completo')}`"
                   for f in filas[:10]]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_explicar_codigo", annotations={"title": "Catálogo de validaciones", **SOLO_LECTURA})
async def visitas_explicar_codigo(params: ExplicarCodigo) -> str:
    """Explica qué significa un código de validación y qué debe hacer quien opera.

    El catálogo `cat_validacion` es el playbook del proceso: lo escribieron
    personas y vive dentro de la base, no en un manual aparte. Esta herramienta
    lo expone tal cual. El agente no inventa acciones: las cita.

    Args:
        params (ExplicarCodigo): código a explicar, o ninguno para el catálogo completo.

    Returns:
        str: markdown con la regla, su severidad, su nivel y la acción indicada.
        En JSON: {"reglas": [{"codigo_error": str, "nombre": str, "descripcion": str,
                              "severidad": str, "nivel": str, "accion_operacion": str,
                              "incidencias_historicas": int}]}

    Examples:
        - «¿qué es V-07?» -> codigo_error="V-07"
        - «¿cuáles reglas rechazan un registro?» -> sin código, y filtra el resultado
    """
    try:
        if params.codigo_error:
            filas = await db.consultar(
                """SELECT c.*, (SELECT COUNT(*) FROM errores e
                                WHERE e.codigo_error = c.codigo_error) AS incidencias_historicas
                   FROM cat_validacion c WHERE c.codigo_error = %s""",
                (params.codigo_error.upper(),),
            )
            if not filas:
                disponibles = await db.consultar("SELECT codigo_error FROM cat_validacion ORDER BY 1")
                codigos = ", ".join(f["codigo_error"] for f in disponibles)
                return (f"No existe el código '{params.codigo_error}'. "
                        f"Los códigos del catálogo son: {codigos}.")
        else:
            filas = await db.consultar(
                """SELECT c.*, (SELECT COUNT(*) FROM errores e
                                WHERE e.codigo_error = c.codigo_error) AS incidencias_historicas
                   FROM cat_validacion c ORDER BY c.codigo_error"""
            )

        datos = {"reglas": limpiar(filas)}
        md = ["# Catálogo de validaciones", ""]
        for r in filas:
            md += [
                f"## {icono(r['severidad'])} {r['codigo_error']} · {r['nombre']}", "",
                f"- **Qué detecta**: {r['descripcion']}",
                f"- **Severidad**: {r['severidad']} · **Nivel**: {r['nivel']}",
                f"- **Acción del operador**: {r['accion_operacion']}",
                f"- **Veces registrada**: {r['incidencias_historicas']}", "",
            ]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_diagnosticar", annotations={"title": "Diagnóstico de una corrida", **SOLO_LECTURA})
async def visitas_diagnosticar(params: Ejecucion) -> str:
    """Diagnostica una corrida: qué pasó, en qué fase, y qué hacer al respecto.

    Es la herramienta de flujo del servidor. En vez de que el agente arme el
    diagnóstico a partir de cinco consultas, aquí se aplican los controles que
    importan y se devuelve el paquete completo: el estatus, los archivos
    detenidos, las incidencias con su acción, y los hallazgos que solo se ven al
    cruzar tablas.

    Entre esos hallazgos hay uno que ninguna consulta suelta revela: un archivo
    que llegó a PURGADO_ORIGEN en una corrida que después falló ya no está en el
    origen, y su huella quedó registrada, así que volver a colocarlo NO lo
    reprocesa (el ETL lo salta por idempotencia). Sus registros no están en el
    destino y no llegarán solos.

    Args:
        params (Ejecucion): id de la corrida, o la última si se omite.

    Returns:
        str: markdown con estado, hallazgos priorizados y acciones sugeridas.
        En JSON: {"ejecucion": {...}, "hallazgos": [{"gravedad": str, "titulo": str,
                  "detalle": str, "accion": str, "evidencia": {...}}],
                  "incidencias": [{...}]}

    Examples:
        - «¿por qué falló la corrida de anoche?» -> sin id
        - «diagnostica la corrida 2» -> id_ejecucion=2
        - Si solo quieres el estado sin análisis, usa visitas_estado_actual
    """
    try:
        id_ej = await db.resolver_ejecucion(params.id_ejecucion)
        if id_ej is None:
            return await _no_hay_corrida()
        ejec = await db.uno("SELECT * FROM etl_ejecucion WHERE id_ejecucion = %s", (id_ej,))
        if not ejec:
            return f"No existe la corrida {id_ej}."

        hallazgos: list[dict[str, Any]] = []

        if ejec["estatus"] == "FALLIDO":
            hallazgos.append({
                "gravedad": "critico",
                "titulo": "La corrida terminó FALLIDA",
                "detalle": ejec.get("mensaje") or "Sin mensaje registrado.",
                "accion": "Revisar el mensaje del error. Si viene de la transformación, "
                          "los archivos ya cargados pueden haberse purgado del origen.",
                "evidencia": {"estatus": ejec["estatus"], "mensaje": ejec.get("mensaje")},
            })

        # La trampa de idempotencia: el archivo se purgó del origen y DESPUÉS la
        # corrida falló, así que sus registros no llegaron al destino y su huella
        # ya bloquea el reproceso.
        #
        # La condición exige que la corrida sea FALLIDA a propósito. En una
        # corrida exitosa, cero filas con ese id_archivo no significa que el dato
        # se haya perdido: `estadistica` consolida por (email, fecha_envio) con
        # ON DUPLICATE KEY UPDATE, y esa cláusula no actualiza `id_archivo`, así
        # que el linaje se queda apuntando al primer archivo que trajo ese envío.
        # Sin ese matiz, la herramienta reporta pérdidas que no ocurrieron.
        huerfanos = await db.consultar(
            """SELECT a.id_archivo, a.nombre_archivo, a.registros_leidos, a.archivo_zip,
                      LEFT(a.hash_archivo,12) AS hash,
                      (SELECT COUNT(*) FROM estadistica s WHERE s.id_archivo = a.id_archivo)
                        AS en_destino
               FROM etl_archivo a
               JOIN etl_ejecucion e ON e.id_ejecucion = a.id_ejecucion
               WHERE a.id_ejecucion = %s AND a.estatus = 'PURGADO_ORIGEN'
                 AND a.registros_leidos > 0 AND e.estatus = 'FALLIDO'
               HAVING en_destino = 0""",
            (id_ej,),
        )
        for h in huerfanos:
            hallazgos.append({
                "gravedad": "critico",
                "titulo": f"{h['nombre_archivo']}: purgado del origen sin llegar al destino",
                "detalle": (
                    f"Se leyeron {h['registros_leidos']} registros y hay 0 en `estadistica`. "
                    f"El archivo ya fue borrado del origen y su huella {h['hash']} está "
                    f"registrada, así que volver a colocarlo NO lo reprocesa: el ETL lo salta "
                    f"por idempotencia y la corrida reporta OK."
                ),
                "accion": (
                    f"Recuperar el archivo del respaldo `{h['archivo_zip']}`, borrar su fila de "
                    f"`etl_archivo` (id_archivo={h['id_archivo']}) para liberar la huella, y "
                    f"volver a colocarlo en el origen."
                ),
                "evidencia": {k: h[k] for k in ("id_archivo", "nombre_archivo",
                                                "registros_leidos", "en_destino", "archivo_zip")},
            })

        # Linaje: en una corrida exitosa, un archivo cargado sin filas propias en
        # el destino significa que todos sus envíos ya existían y se consolidaron
        # sobre las filas del archivo que los trajo primero.
        if ejec["estatus"] != "FALLIDO":
            sin_linaje = await db.consultar(
                """SELECT a.nombre_archivo, a.registros_leidos
                   FROM etl_archivo a
                   WHERE a.id_ejecucion = %s AND a.estatus = 'PURGADO_ORIGEN'
                     AND a.registros_leidos > 0
                     AND (SELECT COUNT(*) FROM estadistica s
                          WHERE s.id_archivo = a.id_archivo) = 0""",
                (id_ej,),
            )
            for s in sin_linaje:
                hallazgos.append({
                    "gravedad": "medio",
                    "titulo": f"{s['nombre_archivo']}: sus registros se consolidaron sobre otro archivo",
                    "detalle": (
                        f"Se cargaron {s['registros_leidos']} registros, pero ninguna fila de "
                        f"`estadistica` apunta a este archivo. Todos sus envíos ya existían y se "
                        f"actualizaron con ON DUPLICATE KEY UPDATE, que no toca `id_archivo`: el "
                        f"linaje sigue apuntando al primer archivo que trajo cada envío. El dato "
                        f"está, la trazabilidad al archivo de origen no."
                    ),
                    "accion": "Si se necesita rastrear qué archivo aportó la última actualización, "
                              "agregar `id_archivo = VALUES(id_archivo)` a la cláusula ON DUPLICATE "
                              "de `estadistica`, o llevar una tabla de linaje aparte.",
                    "evidencia": dict(s),
                })

        detenidos = await db.consultar(
            """SELECT nombre_archivo, estatus, motivo_rechazo
               FROM etl_archivo
               WHERE id_ejecucion = %s AND estatus IN
                     ('DESCARGADO','VALIDADO','CARGADO','RESPALDADO')""",
            (id_ej,),
        )
        for d in detenidos:
            hallazgos.append({
                "gravedad": "alto",
                "titulo": f"{d['nombre_archivo']}: detenido en {d['estatus']}",
                "detalle": "El archivo no completó el ciclo hasta PURGADO_ORIGEN.",
                "accion": {
                    "CARGADO": "Cargó pero no se respaldó. El archivo sigue en el origen; "
                               "la siguiente corrida lo saltará por huella si su fila ya existe.",
                    "RESPALDADO": "Se respaldó pero no se purgó del origen. La siguiente "
                                  "corrida lo detectará y lo saltará por huella.",
                }.get(d["estatus"], "Revisar en qué fase se detuvo el proceso."),
                "evidencia": dict(d),
            })

        rechazados = await db.consultar(
            """SELECT nombre_archivo, motivo_rechazo FROM etl_archivo
               WHERE id_ejecucion = %s AND estatus = 'RECHAZADO'""",
            (id_ej,),
        )
        for r in rechazados:
            hallazgos.append({
                "gravedad": "alto",
                "titulo": f"{r['nombre_archivo']}: rechazado",
                "detalle": r.get("motivo_rechazo") or "Sin motivo registrado.",
                "accion": "No se cargó ni se borró del origen. Escalar a Desarrollo y pedir "
                          "el archivo corregido al proveedor.",
                "evidencia": dict(r),
            })

        leidos = ejec.get("registros_leidos") or 0
        errores = ejec.get("registros_error") or 0
        if leidos and errores / leidos > 0.05:
            hallazgos.append({
                "gravedad": "alto",
                "titulo": f"Tasa de rechazo de {errores / leidos:.1%}",
                "detalle": f"{errores} rechazos sobre {leidos} registros leídos.",
                "accion": "El catálogo indica escalar cuando V-03 supera el 5% del archivo.",
                "evidencia": {"registros_leidos": leidos, "registros_error": errores},
            })

        if (ejec.get("archivos_detectados") or 0) > 0 and (ejec.get("archivos_cargados") or 0) == 0:
            hallazgos.append({
                "gravedad": "medio",
                "titulo": "Se detectaron archivos pero no se cargó ninguno",
                "detalle": f"{ejec['archivos_detectados']} archivos detectados, 0 cargados. "
                           f"Suele significar que todos se saltaron por huella ya registrada.",
                "accion": "Verificar con visitas_listar_archivos si son archivos ya procesados "
                          "o si quedaron atorados en el origen.",
                "evidencia": {"detectados": ejec["archivos_detectados"], "cargados": 0},
            })

        if ejec["estatus"] == "EN_CURSO":
            hallazgos.append({
                "gravedad": "alto",
                "titulo": "La corrida sigue EN_CURSO",
                "detalle": "Si el proceso ya murió, PC-0 bloquea las siguientes corridas "
                           "hasta que pasen 6 horas desde su inicio.",
                "accion": "Esperar a que venza la ventana o cerrar la fila a mano si se "
                          "confirma que el proceso no está vivo.",
                "evidencia": {"fecha_inicio": str(ejec.get("fecha_inicio"))},
            })

        # Integridad del renglón auditado. Toda la seguridad de purgar el origen
        # descansa en que `registro_completo` permita reconstruir el registro; si
        # no trae las 15 columnas, esa garantía no se cumple.
        renglones = await db.uno(
            """SELECT COUNT(*) AS auditados,
                      SUM((LENGTH(registro_completo) -
                           LENGTH(REPLACE(registro_completo, ',', '')) + 1) <> 15) AS incompletos
               FROM errores
               WHERE id_ejecucion = %s AND registro_completo IS NOT NULL""",
            (id_ej,),
        )
        if renglones and (renglones.get("incompletos") or 0) > 0:
            hallazgos.append({
                "gravedad": "alto",
                "titulo": "Renglones auditados que no permiten reconstruir el registro",
                "detalle": (
                    f"{renglones['incompletos']} de {renglones['auditados']} renglones "
                    f"guardados en `errores` no tienen 15 campos. `CONCAT_WS` omite los "
                    f"valores nulos, así que un campo vacío desaparece del renglón y las "
                    f"posiciones se recorren. El registro no se puede reprocesar a partir "
                    f"de lo guardado, y el archivo original ya fue purgado del origen."
                ),
                "accion": "Reemplazar CONCAT_WS por CONCAT con separadores explícitos, o "
                          "guardar la línea cruda antes de tipificar.",
                "evidencia": dict(renglones),
            })

        incidencias = await _resumen_errores(id_ej)
        orden = {"critico": 0, "alto": 1, "medio": 2, "bajo": 3}
        hallazgos.sort(key=lambda h: orden.get(h["gravedad"], 9))

        datos = {"ejecucion": limpiar([ejec])[0],
                 "hallazgos": hallazgos,
                 "incidencias": limpiar(incidencias)}

        marca = {"critico": "🔴", "alto": "🟠", "medio": "🟡", "bajo": "⚪"}
        md = [f"# Diagnóstico de la corrida {id_ej}", "",
              f"**Estatus:** {icono(ejec['estatus'])} {ejec['estatus']} · "
              f"**Leídos:** {leidos} · **Cargados:** {ejec.get('registros_cargados')} · "
              f"**Rechazos:** {errores}", ""]
        if not hallazgos:
            md += ["✅ Sin hallazgos. La corrida completó su ciclo sin anomalías estructurales."]
        else:
            md += [f"## {len(hallazgos)} hallazgo(s)", ""]
            for h in hallazgos:
                md += [f"### {marca.get(h['gravedad'],'')} {h['titulo']}", "",
                       h["detalle"], "", f"**Acción:** {h['accion']}", ""]
        if incidencias:
            md += ["## Incidencias auditadas", "",
                   tabla([{"código": i["codigo_error"], "regla": i["nombre"],
                           "severidad": i["severidad"], "n": i["incidencias"],
                           "acción": i["accion_operacion"]} for i in incidencias])]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_reconciliar", annotations={"title": "Puntos de control", **SOLO_LECTURA})
async def visitas_reconciliar(params: Ejecucion) -> str:
    """Corre los puntos de control de reconciliación y devuelve el cuadre por capa.

    Estos controles no miran el contenido de cada registro: comparan cantidades
    entre etapas. Es el único tipo de control que detecta una pérdida silenciosa,
    donde cada registro individual es válido pero faltan filas.

    Args:
        params (Ejecucion): id de la corrida para el cuadre por archivo, o la última.

    Returns:
        str: markdown con el conteo por capa, el cuadre por archivo y el resultado
        de cada punto de control. En JSON:
        {"id_ejecucion": int, "conteo_por_capa": [{"capa": str, "registros": int}],
         "cuadre_por_archivo": [{...}],
         "puntos_control": [{"punto": str, "descripcion": str, "valor": int,
                             "resultado": "OK"|"FALLA"}],
         "todos_ok": bool}

    Examples:
        - «¿cuadran los números?» -> sin id
        - «reconcilia la corrida 1» -> id_ejecucion=1
    """
    try:
        id_ej = await db.resolver_ejecucion(params.id_ejecucion)
        if id_ej is None:
            return await _no_hay_corrida()

        existe_wrk = await db.escalar(
            """SELECT COUNT(*) AS n FROM information_schema.tables
               WHERE table_schema = DATABASE() AND table_name = 'wrk_visitas'"""
        )

        capas = [
            ("stg_visitas", "SELECT COUNT(*) AS n FROM stg_visitas"),
            ("estadistica", "SELECT COUNT(*) AS n FROM estadistica"),
            ("visita", "SELECT COUNT(*) AS n FROM visita"),
            ("visitante", "SELECT COUNT(*) AS n FROM visitante"),
            ("suma de clics", "SELECT IFNULL(SUM(clicks),0) AS n FROM visita"),
        ]
        if existe_wrk:
            capas.insert(1, ("wrk_visitas", "SELECT COUNT(*) AS n FROM wrk_visitas"))
        conteo = [{"capa": nombre, "registros": await db.escalar(sql)} for nombre, sql in capas]

        cuadre = await db.consultar(
            """SELECT a.nombre_archivo, a.registros_leidos AS leidos,
                      (SELECT COUNT(*) FROM estadistica s WHERE s.id_archivo = a.id_archivo)
                        AS en_estadistica,
                      (SELECT COUNT(*) FROM errores e
                       WHERE e.id_archivo = a.id_archivo AND e.severidad = 'RECHAZO')
                        AS rechazados
               FROM etl_archivo a WHERE a.id_ejecucion = %s ORDER BY a.id_archivo""",
            (id_ej,),
        )

        controles = []

        if existe_wrk:
            d = await db.escalar(
                "SELECT (SELECT COUNT(*) FROM stg_visitas) - (SELECT COUNT(*) FROM wrk_visitas) AS d"
            )
            controles.append(("PC-5", "staging = capa de trabajo", d))

            d = await db.escalar(
                """SELECT COUNT(*) AS d FROM (
                       SELECT a.id_archivo FROM etl_archivo a
                       JOIN wrk_visitas w ON w.id_archivo = a.id_archivo
                       WHERE a.id_ejecucion = %s
                       GROUP BY a.id_archivo, a.registros_leidos
                       HAVING COUNT(w.id_stg) <> a.registros_leidos) x""",
                (id_ej,),
            )
            controles.append(("PC-6", "cuadre por archivo", d))

            d = await db.escalar(
                """SELECT (SELECT COUNT(*) FROM wrk_visitas WHERE rn > 1)
                        - (SELECT COUNT(*) FROM errores
                           WHERE id_ejecucion = %s AND codigo_error = 'V-07') AS d""",
                (id_ej,),
            )
            controles.append(("PC-7", "descartes por duplicado auditados", d))

            d = await db.escalar(
                r"""SELECT (SELECT COUNT(*) FROM wrk_visitas WHERE plataformas LIKE '%\r')
                         + (SELECT COUNT(*) FROM wrk_visitas WHERE navegadores LIKE '%\r') AS d"""
            )
            controles.append(("PC-8", "higiene de saltos de línea", d))

        fila = await db.uno(
            """SELECT
                 (SELECT COUNT(*) FROM estadistica WHERE email IS NULL OR fecha_envio IS NULL) AS a,
                 (SELECT COUNT(*) FROM visitante WHERE visitasTotales <= 0) AS b,
                 (SELECT COUNT(*) FROM visitante WHERE fechaPrimeraVisita > fechaUltimaVisita) AS c,
                 (SELECT COUNT(DISTINCT email) FROM visita) - (SELECT COUNT(*) FROM visitante) AS d"""
        )
        controles.append(("PC-9", "integridad del destino", sum(abs(v or 0) for v in fila.values())))

        d = await db.escalar(
            """SELECT COUNT(*) AS d FROM (
                   SELECT vt.email FROM visitante vt
                   JOIN (SELECT email, SUM(clicks) AS c FROM visita GROUP BY email) v
                     ON v.email = vt.email
                   WHERE vt.visitasTotales <> v.c) x"""
        )
        controles.append(("P-04", "visitasTotales = suma de clics", d))

        resultados = [{"punto": p, "descripcion": desc, "valor": int(v or 0),
                       "resultado": "OK" if (v or 0) == 0 else "FALLA"}
                      for p, desc, v in controles]
        todos_ok = all(r["resultado"] == "OK" for r in resultados)

        datos = {"id_ejecucion": id_ej, "conteo_por_capa": conteo,
                 "cuadre_por_archivo": limpiar(cuadre),
                 "puntos_control": resultados, "todos_ok": todos_ok}

        md = [f"# Reconciliación · corrida {id_ej}", "",
              "## Conteo por capa", "", tabla(conteo), ""]
        if not existe_wrk:
            md += ["> La capa de trabajo `wrk_visitas` no existe: se reconstruye en cada "
                   "corrida y solo está presente después de una transformación exitosa. "
                   "PC-5 a PC-8 no se pueden evaluar.", ""]
        md += ["## Cuadre por archivo", "", tabla(cuadre) if cuadre else "_Sin archivos._", "",
               "## Puntos de control", "",
               tabla([{"": "🟢" if r["resultado"] == "OK" else "🔴", "punto": r["punto"],
                       "control": r["descripcion"], "diferencia": r["valor"],
                       "resultado": r["resultado"]} for r in resultados]), "",
               "✅ **Todos los puntos de control cuadran.**" if todos_ok
               else "🔴 **Hay puntos de control fuera de cuadre.** Una diferencia distinta de "
                    "cero significa que se perdieron o duplicaron registros entre etapas."]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


# ---------------------------------------------------------------------------
# Familia 2 · Interpretación de casos ambiguos
# ---------------------------------------------------------------------------

# Cada caso ambiguo trae la regla de negocio que aplica y por qué quedó sin
# resolver. El agente clasifica con esa evidencia; la herramienta no decide.
_CONSULTAS_AMBIGUAS: dict[str, dict[str, str]] = {
    "badmail_con_actividad": {
        "titulo": "Badmail marcado, con interacción en la misma fila",
        "regla": "BR-011 del catálogo. Un rebote duro debería ser incompatible con una "
                 "apertura o un clic en el mismo registro.",
        "pregunta_abierta": "¿Qué significa funcionalmente Badmail = HARD y es un estado "
                            "permanente del correo o del envío? Sin esa definición no se "
                            "puede convertir en regla de exclusión.",
        "sql": """SELECT email, fecha_envio, badmail, baja, opens, clicks,
                         fecha_open, fecha_click, id_archivo
                  FROM estadistica
                  WHERE badmail IS NOT NULL AND (opens > 0 OR clicks > 0)
                  ORDER BY clicks DESC, opens DESC""",
    },
    "badmail_perdido_en_dedupe": {
        "titulo": "La marca Badmail se perdió al deduplicar",
        "regla": "Cruce de V-07 con la tabla destino. El ranking de duplicados ordena por "
                 "`opens DESC, clicks DESC`, así que cuando dos filas del mismo envío "
                 "difieren en el estatus de entrega, gana la de más interacción y con ella "
                 "se descarta la marca de rebote.",
        "pregunta_abierta": "¿Debe el ranking de duplicados preservar el estatus de entrega "
                            "aunque conserve las métricas del otro registro? Hoy la "
                            "contradicción solo sobrevive en `errores.registro_completo`: "
                            "quien consulte únicamente `estadistica` nunca la ve.",
        "sql": """SELECT SUBSTRING_INDEX(er.registro_completo, ',', 1) AS email,
                         e.fecha_envio,
                         IFNULL(e.badmail, '(sin marca)') AS badmail_en_destino,
                         e.opens, e.clicks,
                         er.nombre_archivo, er.num_linea,
                         er.registro_completo AS renglon_descartado
                  FROM errores er
                  JOIN estadistica e
                    ON e.email = SUBSTRING_INDEX(er.registro_completo, ',', 1)
                  WHERE er.codigo_error = 'V-07'
                    AND er.registro_completo REGEXP '(^|,)HARD(,|$)'
                    AND (e.opens > 0 OR e.clicks > 0)
                  ORDER BY e.clicks DESC""",
    },
    "fecha_anterior_al_envio": {
        "titulo": "Apertura o clic con fecha anterior al envío",
        "regla": "V-08, coherencia temporal. Se carga con advertencia porque la causa "
                 "puede ser del sistema de origen y no del dato.",
        "pregunta_abierta": "¿La fecha de envío marca el momento a partir del cual deben "
                            "registrarse los eventos, o hay desfase de zona horaria entre "
                            "los campos?",
        "sql": """SELECT email, fecha_envio, fecha_open, fecha_click, opens, clicks,
                         TIMESTAMPDIFF(MINUTE, fecha_envio, fecha_open) AS minutos_diferencia
                  FROM estadistica
                  WHERE fecha_open IS NOT NULL AND fecha_open < fecha_envio
                  ORDER BY minutos_diferencia""",
    },
    "virales_mayor_que_total": {
        "titulo": "Métrica viral mayor que su total",
        "regla": "BR-009 y BR-010. Quedaron como advertencia porque no está establecido "
                 "que las métricas virales sean un subconjunto de las totales.",
        "pregunta_abierta": "¿Opens virales y Clicks virales son un subconjunto matemático "
                            "de Opens y Clicks? Si el negocio lo confirma, la regla se "
                            "puede promover a rechazo.",
        "sql": """SELECT email, fecha_envio, opens, opens_virales, clicks, clicks_virales
                  FROM estadistica
                  WHERE opens_virales > opens OR clicks_virales > clicks
                  ORDER BY (opens_virales - opens) DESC""",
    },
    "baja_con_actividad": {
        "titulo": "Baja marcada, con interacción registrada",
        "regla": "BR-012 a BR-016. Se considera válido: alguien puede recibir, abrir, darse "
                 "de baja y después volver a dar clic.",
        "pregunta_abierta": "El archivo no trae timestamp del evento de baja, así que el "
                            "orden entre la baja y la interacción no se puede probar.",
        "sql": """SELECT email, fecha_envio, baja, opens, clicks, fecha_open, fecha_click
                  FROM estadistica
                  WHERE baja IS NOT NULL AND (opens > 0 OR clicks > 0)
                  ORDER BY clicks DESC""",
    },
    "clic_sin_apertura": {
        "titulo": "Clic registrado sin fecha de apertura",
        "regla": "V-10, coherencia de embudo. Indica que se perdió el evento intermedio "
                 "en el origen.",
        "pregunta_abierta": "¿El proveedor garantiza que toda apertura queda registrada, o "
                            "el pixel de seguimiento puede fallar y aun así registrarse el clic?",
        "sql": """SELECT email, fecha_envio, opens, clicks, fecha_open, fecha_click, links
                  FROM estadistica
                  WHERE clicks > 0 AND fecha_open IS NULL
                  ORDER BY clicks DESC""",
    },
}


assert set(_CONSULTAS_AMBIGUAS) == set(TIPOS_AMBIGUOS), (
    "TIPOS_AMBIGUOS y _CONSULTAS_AMBIGUAS deben cubrir exactamente los mismos casos: "
    f"sobran {set(_CONSULTAS_AMBIGUAS) ^ set(TIPOS_AMBIGUOS)}"
)


@mcp.tool(name="visitas_casos_ambiguos", annotations={"title": "Casos que exigen criterio", **SOLO_LECTURA})
async def visitas_casos_ambiguos(params: CasosAmbiguos) -> str:
    """Devuelve los registros que el ETL marcó como ambiguos a propósito, con su contexto.

    Son los casos donde el proceso determinista se detuvo por diseño: la regla de
    negocio no está definida, así que el ETL carga el dato con una advertencia en
    vez de inventar una corrección. Aquí es donde el criterio del agente aporta
    algo que el SQL no puede dar.

    La herramienta entrega evidencia, no veredictos: los registros, la regla que
    aplica, y la pregunta de negocio que sigue sin respuesta. Clasificar es
    trabajo del agente, y para que quede auditable debe registrarse con
    visitas_registrar_dictamen.

    Args:
        params (CasosAmbiguos): tipo de ambigüedad, límite y filtro de sin dictamen.

    Returns:
        str: markdown con un bloque por tipo: regla aplicable, pregunta abierta y
        tabla de registros. En JSON:
        {"tipos": [{"tipo": str, "titulo": str, "regla": str, "pregunta_abierta": str,
                    "total": int, "casos": [{...}]}]}

    Examples:
        - «¿qué casos raros hay en los datos?» -> tipo="todos"
        - «muéstrame los badmail con actividad» -> tipo="badmail_con_actividad"
        - «¿qué falta por dictaminar?» -> solo_sin_dictamen=true
    """
    try:
        tipos = (list(_CONSULTAS_AMBIGUAS) if params.tipo.value == "todos"
                 else [params.tipo.value])
        salida = []
        for t in tipos:
            cfg = _CONSULTAS_AMBIGUAS[t]
            filas = await db.consultar(f"{cfg['sql']} LIMIT %s", (params.limite,))
            total = await db.escalar(
                f"SELECT COUNT(*) AS n FROM ({cfg['sql']}) x"
            )
            if params.solo_sin_dictamen and filas:
                try:
                    ya = await db.consultar(
                        "SELECT email, fecha_envio FROM dictamen_agente WHERE tipo_caso = %s", (t,)
                    )
                    vistos = {(d["email"], str(d["fecha_envio"])) for d in ya}
                    filas = [f for f in filas
                             if (f["email"], str(f["fecha_envio"])) not in vistos]
                except db.ErrorBase:
                    pass  # sin tabla de dictámenes todavía: no hay nada que filtrar
            salida.append({"tipo": t, "titulo": cfg["titulo"], "regla": cfg["regla"],
                           "pregunta_abierta": cfg["pregunta_abierta"],
                           "total": total, "casos": limpiar(filas)})

        datos = {"tipos": salida}
        md = ["# Casos que exigen criterio", "",
              "_El ETL cargó estos registros con advertencia porque la regla de negocio no "
              "está definida. La evidencia va abajo; el veredicto le toca al agente, y "
              "conviene registrarlo con `visitas_registrar_dictamen`._", ""]
        for s in salida:
            md += [f"## {s['titulo']}", "",
                   f"- **Regla aplicable**: {s['regla']}",
                   f"- **Pregunta abierta**: {s['pregunta_abierta']}",
                   f"- **Casos en la base**: {s['total']}", ""]
            md += [tabla(s["casos"]) if s["casos"] else "_Sin casos de este tipo._", ""]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_registrar_dictamen", annotations={"title": "Registrar dictamen", **ESCRITURA})
async def visitas_registrar_dictamen(params: RegistrarDictamen) -> str:
    """Registra la clasificación que el agente dio a un caso ambiguo, con su justificación.

    Es la pieza que hace auditable el juicio del modelo. Un agente que clasifica
    sin dejar rastro no es usable en producción: nadie puede revisar sus
    decisiones ni medir si acierta. Cada dictamen guarda quién clasificó, qué
    evidencia usó y con cuánta confianza, en una tabla propia que no toca los
    datos que produjo el ETL.

    Args:
        params (RegistrarDictamen): tipo de caso, llave del registro (email y fecha
            de envío), clasificación, justificación y confianza de 0 a 1.

    Returns:
        str: confirmación con el id del dictamen. En JSON:
        {"id_dictamen": int, "tipo_caso": str, "email": str, "fecha_envio": str,
         "clasificacion": str, "confianza": float, "registrado": true}

    Examples:
        - Después de analizar un badmail con actividad:
          tipo_caso="badmail_con_actividad", clasificacion="REQUIERE_NEGOCIO",
          justificacion="El HARD parece de un envío previo; sin definición del
          proveedor no se puede excluir el registro.", confianza=0.6

    Error Handling:
        - Si falta la tabla, indica correr sql/06_agente_dictamenes.sql
        - Si el registro no existe en `estadistica`, lo dice en vez de escribir a ciegas
    """
    try:
        existe = await db.escalar(
            "SELECT COUNT(*) AS n FROM estadistica WHERE email = %s AND fecha_envio = %s",
            (params.email, params.fecha_envio),
        )
        if not existe:
            return (f"No hay ningún registro en `estadistica` con email '{params.email}' y "
                    f"fecha de envío '{params.fecha_envio}'. Verifica la llave con "
                    f"visitas_casos_ambiguos antes de dictaminar.")
        if params.tipo_caso not in _CONSULTAS_AMBIGUAS:
            validos = ", ".join(_CONSULTAS_AMBIGUAS)
            return f"tipo_caso '{params.tipo_caso}' no es uno de los conocidos: {validos}."

        id_dictamen = await db.escribir(
            """INSERT INTO dictamen_agente
                 (tipo_caso, email, fecha_envio, clasificacion, justificacion, confianza)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (params.tipo_caso, params.email, params.fecha_envio,
             params.clasificacion.value, params.justificacion, params.confianza),
        )
        datos = {"id_dictamen": id_dictamen, "tipo_caso": params.tipo_caso,
                 "email": params.email, "fecha_envio": params.fecha_envio,
                 "clasificacion": params.clasificacion.value,
                 "confianza": params.confianza, "registrado": True}
        md = (f"✅ Dictamen **{id_dictamen}** registrado.\n\n"
              f"- **Caso**: {params.tipo_caso}\n"
              f"- **Registro**: {params.email} · {params.fecha_envio}\n"
              f"- **Clasificación**: {params.clasificacion.value}\n"
              f"- **Confianza**: {params.confianza:.0%}\n\n"
              f"Queda disponible para revisión humana con `visitas_listar_dictamenes`.")
        return _salida(params, datos, md)
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_listar_dictamenes", annotations={"title": "Dictámenes registrados", **SOLO_LECTURA})
async def visitas_listar_dictamenes(params: ListarEjecuciones) -> str:
    """Lista los dictámenes que el agente ha registrado, para revisión humana.

    Args:
        params (ListarEjecuciones): se usan `limite` y `offset`; `estatus` se ignora.

    Returns:
        str: markdown con los dictámenes y un resumen por clasificación. En JSON:
        {"total": int, "devueltos": int, "offset": int, "hay_mas": bool,
         "siguiente_offset": int|null, "resumen": [{"clasificacion": str, "n": int,
         "confianza_promedio": float}], "dictamenes": [{...}]}

    Examples:
        - «¿qué ha dictaminado el agente?» -> sin parámetros
        - Para revisar dictámenes de baja confianza, pide JSON y filtra por confianza
    """
    try:
        total = await db.escalar("SELECT COUNT(*) AS n FROM dictamen_agente")
        if not total:
            return ("Todavía no hay dictámenes registrados. Usa visitas_casos_ambiguos "
                    "para revisar casos y visitas_registrar_dictamen para dejar constancia.")
        filas = await db.consultar(
            """SELECT id_dictamen, tipo_caso, email, fecha_envio, clasificacion,
                      confianza, justificacion, fecha_dictamen
               FROM dictamen_agente ORDER BY id_dictamen DESC LIMIT %s OFFSET %s""",
            (params.limite, params.offset),
        )
        resumen = await db.consultar(
            """SELECT clasificacion, COUNT(*) AS n, ROUND(AVG(confianza), 2) AS confianza_promedio
               FROM dictamen_agente GROUP BY clasificacion ORDER BY n DESC"""
        )
        pag = paginacion(total, len(filas), params.offset)
        datos = {**pag, "resumen": limpiar(resumen), "dictamenes": limpiar(filas)}
        md = ["# Dictámenes del agente", "", "## Resumen", "", tabla(resumen), "",
              "## Detalle", "",
              tabla([{"id": f["id_dictamen"], "caso": f["tipo_caso"], "email": f["email"],
                      "clasificación": f["clasificacion"], "confianza": f["confianza"],
                      "cuándo": f["fecha_dictamen"]} for f in filas]),
              "", nota_paginacion(pag)]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


# ---------------------------------------------------------------------------
# Familia 3 · Ingesta de archivos nuevos
# ---------------------------------------------------------------------------

@mcp.tool(name="visitas_perfilar_archivo", annotations={"title": "Perfilar archivo plano", **SOLO_LECTURA})
async def visitas_perfilar_archivo(params: PerfilarArchivo) -> str:
    """Perfila un archivo plano: estructura, tipos, ausencias, llaves candidatas y anomalías.

    Todo el perfilado es determinista: cuenta y mide, no interpreta. Incluye la
    detección del riesgo de CRLF con campos entrecomillados, que es el patrón
    que provoca pérdida silenciosa de filas al cargar con LOAD DATA.

    Sobre las llaves candidatas, devuelve el porcentaje de unicidad y no un
    veredicto: que una combinación sea única en la muestra no prueba que sea la
    llave de negocio, y confundir las dos cosas es lo que lleva a deduplicar
    borrando información real.

    Args:
        params (PerfilarArchivo): ruta absoluta del archivo y tamaño de muestra.

    Returns:
        str: markdown con estructura, perfil por columna, llaves candidatas y
        anomalías. En JSON, el diccionario completo del perfil:
        {"archivo": str, "bytes": int, "codificacion": str, "delimitador": str,
         "terminadores": {"crlf": int, "riesgo_crlf_comillas": bool, "nota": str},
         "columnas": int, "filas_datos": int, "encabezados": [str],
         "perfil_columnas": [{"posicion": int, "nombre": str, "tipo": str,
                              "no_nulos": int, "pct_presente": float, "distintos": int,
                              "formas_de_ausencia": {str: int}, "ejemplos": [str]}],
         "candidatos_llave": [{"columnas": [str], "unicidad": float, "duplicados": int}],
         "anomalias": [{"tipo": str, "gravedad": str, "detalle": str}]}

    Examples:
        - «perfila /datos/nuevo.csv» -> ruta="/datos/nuevo.csv"
        - Encadena con visitas_proponer_validaciones para el esquema
    """
    try:
        import asyncio
        perfil = await asyncio.to_thread(perfilado.perfilar, params.ruta, params.muestra)
        t = perfil["terminadores"]
        md = [f"# Perfil de `{perfil['archivo']}`", "",
              campos(perfil, {"bytes": "Tamaño (bytes)", "codificacion": "Codificación",
                              "delimitador": "Delimitador", "columnas": "Columnas",
                              "filas_datos": "Filas de datos",
                              "filas_analizadas": "Filas analizadas"}), "",
              "## Terminadores de línea", "",
              f"- CRLF: {t['crlf']} · CR sueltos: {t['cr_sueltos']} · LF: {t['lf']}",
              f"- Campos entrecomillados: {'sí' if t['campos_entrecomillados'] else 'no'}",
              f"- {'⚠️ ' if t['riesgo_crlf_comillas'] else ''}{t['nota']}", "",
              "## Columnas", "",
              tabla([{"#": c["posicion"], "nombre": c["nombre"], "tipo": c["tipo"],
                      "presente": f"{c['pct_presente']}%", "distintos": c["distintos"],
                      "ejemplos": ", ".join(str(e) for e in c["ejemplos"][:2]),
                      "detalle": c.get("detalle", "")}
                     for c in perfil["perfil_columnas"]]), "",
              "## Llaves candidatas", ""]
        md += [tabla([{"columnas": " + ".join(c["columnas"]),
                       "unicidad": f"{c['unicidad']:.1%}", "duplicados": c["duplicados"]}
                      for c in perfil["candidatos_llave"]])
               if perfil["candidatos_llave"] else "_Ninguna columna alcanza 50% de unicidad._"]
        md += ["", "_La unicidad en una muestra no prueba que sea la llave de negocio. "
                   "Antes de deduplicar por una combinación, confírmala con el proveedor._", "",
               "## Anomalías", ""]
        if perfil["anomalias"]:
            for a in perfil["anomalias"]:
                marca = "🔴" if a["gravedad"] == "rechazo" else "🟡"
                md += [f"- {marca} **{a['tipo']}**: {a['detalle']}"]
        else:
            md += ["_Sin anomalías estructurales._"]
        return _salida(params, perfil, "\n".join(md))
    except Exception as e:
        return _error(e)


@mcp.tool(name="visitas_proponer_validaciones", annotations={"title": "Proponer esquema y validaciones", **SOLO_LECTURA})
async def visitas_proponer_validaciones(params: ProponerValidaciones) -> str:
    """Genera un DDL de staging y un catálogo de validaciones candidatas para un archivo nuevo.

    El DDL sale del perfil y sigue la misma decisión que el ETL de de visitas web: staging
    declara todo como texto para conservar la evidencia del valor que llegó, y la
    tipificación ocurre después en la capa de trabajo.

    Las validaciones son candidatas, no definitivas: la herramienta propone según
    los tipos detectados y le toca al agente decidir cuáles rechazan y cuáles solo
    advierten, con el criterio de que solo se rechaza lo que vuelve inutilizable
    al registro.

    Args:
        params (ProponerValidaciones): ruta del archivo y nombre de la tabla destino.

    Returns:
        str: markdown con el DDL propuesto, las validaciones candidatas y las
        decisiones que quedan pendientes. En JSON:
        {"tabla": str, "ddl": str, "validaciones": [{"codigo": str, "columna": str,
         "regla": str, "severidad_sugerida": str, "razon": str}],
         "decisiones_pendientes": [str]}

    Examples:
        - «propón el esquema para /datos/nuevo.csv» -> ruta="/datos/nuevo.csv"
        - Requiere haber corrido antes visitas_perfilar_archivo sobre el mismo archivo
    """
    try:
        import asyncio
        import re as _re
        perfil = await asyncio.to_thread(perfilado.perfilar, params.ruta)

        def col_sql(nombre: str, pos: int) -> str:
            limpio = _re.sub(r"[^a-z0-9_]", "_", (nombre or f"col_{pos}").strip().lower())
            return _re.sub(r"_+", "_", limpio).strip("_") or f"col_{pos}"

        lineas_ddl = [f"CREATE TABLE {params.nombre_tabla} (",
                      "  id_stg BIGINT AUTO_INCREMENT PRIMARY KEY,",
                      "  id_archivo BIGINT NOT NULL,",
                      "  num_linea INT NOT NULL,"]
        validaciones, codigo = [], 3
        for c in perfil["perfil_columnas"]:
            nombre = col_sql(c["nombre"], c["posicion"])
            largo = max(50, min(500, (c.get("largo_maximo") or 50) * 2))
            if c["tipo"] == "email":
                largo = 320
            lineas_ddl.append(f"  {nombre} VARCHAR({largo}),"
                              f"  -- {c['tipo']}: {c.get('detalle','')}")
            if c["tipo"] == "email":
                validaciones.append({
                    "codigo": f"V-{codigo:02d}", "columna": nombre,
                    "regla": "El valor cumple el patrón de correo electrónico",
                    "severidad_sugerida": "RECHAZO",
                    "razon": "Sin correo válido no se puede atribuir el registro a nadie.",
                })
                codigo += 1
            elif c["tipo"] == "fecha":
                validaciones.append({
                    "codigo": f"V-{codigo:02d}", "columna": nombre,
                    "regla": f"El valor cumple el formato {c.get('formato')}",
                    "severidad_sugerida": "RECHAZO" if c["pct_presente"] > 95 else "ADVERTENCIA",
                    "razon": ("Presente en casi todos los registros: parece obligatoria."
                              if c["pct_presente"] > 95 else
                              "Ausente en parte de los registros: la ausencia parece legítima."),
                })
                codigo += 1
            elif c["tipo"] in ("entero", "decimal"):
                validaciones.append({
                    "codigo": f"V-{codigo:02d}", "columna": nombre,
                    "regla": "El valor es numérico",
                    "severidad_sugerida": "ADVERTENCIA",
                    "razon": "Un numérico basura se puede cargar como 0 y marcarse, "
                             "en vez de tirar el registro completo.",
                })
                codigo += 1
            elif c["tipo"] == "vacia":
                validaciones.append({
                    "codigo": f"V-{codigo:02d}", "columna": nombre,
                    "regla": "La columna llegó vacía en el 100% de los registros",
                    "severidad_sugerida": "ADVERTENCIA",
                    "razon": "Puede significar que el origen dejó de enviar el campo.",
                })
                codigo += 1

        lineas_ddl += ["  fecha_carga DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,",
                       "  INDEX idx_archivo (id_archivo)",
                       ") ENGINE=InnoDB;"]
        ddl = "\n".join(lineas_ddl)

        pendientes = ["Confirmar con el proveedor cuál es la llave de negocio real: la "
                      "unicidad en la muestra no la prueba.",
                      "Definir qué hacer con los registros duplicados: conservar el más "
                      "completo exige un criterio de ranking explícito y determinista."]
        if perfil["terminadores"]["riesgo_crlf_comillas"]:
            pendientes.insert(0, "Normalizar CRLF a LF sobre una copia antes de cargar, y "
                                 "reconciliar filas leídas contra filas insertadas: este "
                                 "archivo tiene el patrón que provoca pérdida silenciosa.")
        vacias = [c["nombre"] for c in perfil["perfil_columnas"] if c["tipo"] == "vacia"]
        if vacias:
            pendientes.append(f"Preguntar si {', '.join(vacias)} deberían traer dato: "
                              f"llegaron vacías en todo el archivo.")

        datos = {"tabla": params.nombre_tabla, "ddl": ddl,
                 "validaciones": validaciones, "decisiones_pendientes": pendientes}
        md = [f"# Propuesta para `{perfil['archivo']}`", "",
              "## DDL de staging", "",
              "```sql", ddl, "```", "",
              "_Todo va como texto a propósito: staging conserva el valor tal como llegó "
              "para que la tabla de errores pueda mostrarlo. La tipificación ocurre en la "
              "capa de trabajo._", "",
              "## Validaciones candidatas", "",
              tabla([{"código": v["codigo"], "columna": v["columna"], "regla": v["regla"],
                      "severidad": v["severidad_sugerida"], "razón": v["razon"]}
                     for v in validaciones]) if validaciones else "_Sin validaciones evidentes._",
              "", "## Decisiones que siguen abiertas", ""]
        md += [f"{i}. {p}" for i, p in enumerate(pendientes, 1)]
        return _salida(params, datos, "\n".join(md))
    except Exception as e:
        return _error(e)


# ---------------------------------------------------------------------------
# Familia 4 · Práctica con datos reales
# ---------------------------------------------------------------------------

@mcp.tool(name="visitas_caso_practica", annotations={"title": "Caso de práctica", **SOLO_LECTURA})
async def visitas_caso_practica(params: CasoPractica) -> str:
    """Plantea un caso real sacado de la base para practicar la defensa del proyecto.

    No usa preguntas enlatadas: toma una corrida, una incidencia o una anomalía que
    de verdad está en la base y la plantea como situación. La respuesta modelo se
    deriva de los datos y del catálogo, así que si el estado cambia, el caso cambia.

    Args:
        params (CasoPractica): modo del caso y si se muestra la respuesta.

    Returns:
        str: markdown con la situación, los datos disponibles y las preguntas. Con
        `mostrar_respuesta=true` agrega la respuesta modelo. En JSON:
        {"modo": str, "situacion": str, "datos": {...}, "preguntas": [str],
         "respuesta_modelo": str|null, "herramientas_utiles": [str]}

    Examples:
        - «ponme un caso» -> modo="aleatorio"
        - «practiquemos diagnóstico» -> modo="diagnostico"
        - Responde primero, luego repite con mostrar_respuesta=true
    """
    try:
        import random
        modo = params.modo.value
        if modo == "aleatorio":
            modo = random.choice(["diagnostico", "regla", "anomalia"])

        if modo == "diagnostico":
            fila = await db.uno(
                """SELECT * FROM etl_ejecucion
                   WHERE estatus IN ('FALLIDO','OK_CON_ADVERTENCIAS')
                      OR (archivos_detectados > 0 AND archivos_cargados = 0)
                   ORDER BY RAND() LIMIT 1"""
            ) or await db.uno("SELECT * FROM etl_ejecucion ORDER BY RAND() LIMIT 1")
            if not fila:
                return await _no_hay_corrida()
            archivos = await db.consultar(
                """SELECT nombre_archivo, estatus, registros_leidos, motivo_rechazo
                   FROM etl_archivo WHERE id_ejecucion = %s""", (fila["id_ejecucion"],))
            situacion = (
                f"Son las 8 de la mañana y el tablero muestra la corrida "
                f"{fila['id_ejecucion']} con estatus **{fila['estatus']}**. "
                f"Detectó {fila['archivos_detectados']} archivos y cargó "
                f"{fila['archivos_cargados']}. Leyó {fila['registros_leidos']} registros."
            )
            preguntas = [
                "¿Qué revisas primero y por qué?",
                "¿Los datos de esta corrida llegaron al destino? ¿Cómo lo compruebas?",
                "¿Qué le respondes al negocio si pregunta si puede confiar en el reporte de hoy?",
            ]
            datos = {"ejecucion": limpiar([fila])[0], "archivos": limpiar(archivos)}
            resp = (
                f"Empezar por `etl_ejecucion` y `etl_archivo`, no por el log: el estatus de "
                f"cada archivo dice en qué fase se detuvo. En esta corrida "
                f"{'el mensaje del error es: ' + str(fila.get('mensaje')) if fila.get('mensaje') else 'no hay mensaje de error'}. "
                f"Para saber si los datos llegaron, comparar `registros_leidos` de cada archivo "
                f"contra las filas con ese `id_archivo` en `estadistica`. El caso peligroso es un "
                f"archivo en PURGADO_ORIGEN con cero filas en el destino: ya no está en el origen, "
                f"su huella está registrada, y volver a colocarlo no lo reprocesa."
            )
        elif modo == "regla":
            fila = await db.uno(
                """SELECT e.*, c.nombre, c.descripcion AS que_significa,
                          c.severidad AS sev_catalogo, c.nivel, c.accion_operacion
                   FROM errores e JOIN cat_validacion c ON c.codigo_error = e.codigo_error
                   ORDER BY RAND() LIMIT 1"""
            )
            if not fila:
                return ("No hay incidencias registradas todavía. Corre el ETL con datos que "
                        "disparen alguna validación para poder practicar sobre casos reales.")
            situacion = (
                f"En `{fila['nombre_archivo']}`, línea {fila['num_linea']}, el proceso registró "
                f"**{fila['codigo_error']}** con severidad {fila['severidad']}. "
                f"El campo señalado es `{fila['campo']}` con el valor `{fila['valor_original']}`."
            )
            preguntas = [
                f"¿Qué detecta {fila['codigo_error']} y por qué tiene esa severidad y no la otra?",
                "¿El registro entró al destino o se quedó fuera?",
                "¿Qué debe hacer quien opera el proceso cuando ve esto?",
            ]
            datos = limpiar([fila])[0]
            resp = (
                f"{fila['codigo_error']} ({fila['nombre']}) detecta: {fila['que_significa']}. "
                f"Es de nivel {fila['nivel']} y severidad {fila['sev_catalogo']}, "
                f"{'así que el registro no entra al destino' if fila['sev_catalogo'] == 'RECHAZO' else 'así que el registro se carga y queda marcado'}. "
                f"La acción indicada por el catálogo es: {fila['accion_operacion']}. "
                f"El principio de fondo: solo se rechaza lo que vuelve inutilizable al registro "
                f"—sin correo o sin fecha de envío—; lo demás se carga con advertencia, porque "
                f"un dato marcado vale más que un dato perdido."
            )
        else:
            # Se recorren los tipos en orden aleatorio hasta encontrar uno con
            # datos: quedarse con el primer sorteo daría "no hay casos" cuando
            # sí los hay, solo que de otro tipo.
            tipos_barajados = list(_CONSULTAS_AMBIGUAS)
            random.shuffle(tipos_barajados)
            tipo, cfg, fila = None, None, None
            for candidato in tipos_barajados:
                posible = await db.uno(f"{_CONSULTAS_AMBIGUAS[candidato]['sql']} LIMIT 1")
                if posible:
                    tipo, cfg, fila = candidato, _CONSULTAS_AMBIGUAS[candidato], posible
                    break
            if not fila:
                return ("No hay casos ambiguos en la base para practicar. Prueba con "
                        "modo='regla' o modo='diagnostico'.")
            situacion = (f"**{cfg['titulo']}**. En los datos cargados aparece este registro:\n\n"
                         + tabla([fila]))
            preguntas = [
                "¿Es un error de datos o un escenario legítimo del negocio?",
                "¿El ETL debería rechazarlo, marcarlo o cargarlo sin más? Justifica.",
                "¿Qué le preguntarías al proveedor para poder cerrar la regla?",
            ]
            datos = {"tipo": tipo, "registro": limpiar([fila])[0],
                     "regla": cfg["regla"], "pregunta_abierta": cfg["pregunta_abierta"]}
            resp = (
                f"Regla aplicable: {cfg['regla']} La decisión del proyecto fue cargarlo con "
                f"advertencia y no corregirlo, porque la información disponible no alcanza para "
                f"determinar la interpretación correcta, y el ETL no debe inventar una corrección. "
                f"La pregunta que hay que llevarle al proveedor: {cfg['pregunta_abierta']}"
            )

        utiles = {"diagnostico": ["visitas_diagnosticar", "visitas_listar_archivos", "visitas_reconciliar"],
                  "regla": ["visitas_explicar_codigo", "visitas_consultar_errores"],
                  "anomalia": ["visitas_casos_ambiguos", "visitas_registrar_dictamen"]}[modo]

        salida = {"modo": modo, "situacion": situacion, "datos": datos,
                  "preguntas": preguntas,
                  "respuesta_modelo": resp if params.mostrar_respuesta else None,
                  "herramientas_utiles": utiles}
        md = [f"# Caso de práctica · {modo}", "", "## Situación", "", situacion, "",
              "## Preguntas", ""] + [f"{i}. {p}" for i, p in enumerate(preguntas, 1)]
        md += ["", f"_Herramientas útiles: {', '.join('`' + u + '`' for u in utiles)}._"]
        if params.mostrar_respuesta:
            md += ["", "## Respuesta modelo", "", resp]
        else:
            md += ["", "_Responde primero. Para ver la respuesta modelo, repite con "
                       "`mostrar_respuesta=true`._"]
        return _salida(params, salida, "\n".join(md))
    except Exception as e:
        return _error(e)


if __name__ == "__main__":
    mcp.run()
