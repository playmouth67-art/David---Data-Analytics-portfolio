import re
import os
import pymysql

from datetime import datetime
from decimal import Decimal, InvalidOperation


# ============================================================
# CONFIGURACIÓN
# ============================================================

DB_CONFIG = {
    "host": os.environ.get("ETL_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("ETL_DB_PORT", 3306)),
    "user": os.environ.get("ETL_DB_USER", "etl"),
    "password": os.environ.get("ETL_DB_PASSWORD", "etl"),
    "database": os.environ.get("ETL_DB_NAME", "etl_visitas"),
    "cursorclass": pymysql.cursors.DictCursor
}


# ============================================================
# CONEXIÓN
# ============================================================

def get_db_connection():
    return pymysql.connect(**DB_CONFIG)


# ============================================================
# UTILIDADES DE NORMALIZACIÓN
# ============================================================

def is_missing(value):
    """
    Determina si un valor representa ausencia de información.

    Importante:
    '-' se considera un estado de ausencia proveniente del origen,
    pero no se interpreta como error.
    """
    if value is None:
        return True

    value = str(value).strip()

    return value == "" or value == "-"


def normalize_text(value):
    """
    Normaliza texto sin modificar el significado del valor.

    Conserva '-' como representación de ausencia proveniente del
    origen.
    """
    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    return value


# ============================================================
# TIPIFICACIÓN NUMÉRICA
# ============================================================

def parse_integer(value):
    """
    Convierte un valor de origen a entero.

    Retorna:
        - None para valores ausentes ('', '-')
        - int para valores válidos
        - ValueError para valores malformados
    """

    if is_missing(value):
        return None

    normalized = str(value).strip()

    # Permitimos únicamente enteros.
    if not re.fullmatch(r"[+-]?\d+", normalized):
        raise ValueError(
            f"Valor no entero: '{value}'"
        )

    return int(normalized)


# ============================================================
# TIPIFICACIÓN DE FECHAS
# ============================================================

DATE_FORMATS = [
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
]


def parse_datetime(value):
    """
    Convierte fechas del formato esperado por los archivos fuente.

    Retorna:
        - None para '', '-'
        - datetime para valores válidos
        - ValueError para valores inválidos
    """

    if is_missing(value):
        return None

    normalized = str(value).strip()

    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(normalized, date_format)
        except ValueError:
            continue

    raise ValueError(
        f"Formato de fecha inválido: '{value}'"
    )


# ============================================================
# VALIDACIÓN DE EMAIL
# ============================================================

EMAIL_PATTERN = re.compile(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
)


def validate_email(value):
    """
    Valida la presencia y estructura básica del email.

    No pretende demostrar que el buzón exista.
    Solo valida que tenga una estructura sintácticamente razonable.
    """

    if is_missing(value):
        return False

    return bool(
        EMAIL_PATTERN.fullmatch(
            str(value).strip()
        )
    )


# ============================================================
# REPRESENTACIÓN DE RESULTADOS DE REGLAS
# ============================================================

def create_rule_finding(
    rule_id,
    severity,
    description,
    archivo_id,
    numero_fila,
    email=None
):
    """
    Construye una observación normalizada para la tabla errores.
    """

    return {
        "rule_id": rule_id,
        "severidad": severity,
        "descripcion": description,
        "archivo_id": archivo_id,
        "numero_fila": numero_fila,
        "email": email
    }