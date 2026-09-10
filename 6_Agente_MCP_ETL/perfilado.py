"""Perfilado determinista de archivos planos.

Este módulo no le pregunta nada a un modelo: cuenta, mide y detecta patrones.
El agente recibe el perfil como evidencia y a partir de ahí propone un esquema
y un catálogo de validaciones, que es donde su criterio sí aporta.

La separación importa y es la misma que rige el resto del servidor: lo que se
puede verificar con aritmética se calcula; lo que exige interpretar el negocio
se le deja al agente, con la evidencia enfrente.
"""

from __future__ import annotations

import csv
import io
import os
import re
from collections import Counter
from typing import Any

# Formatos de fecha que se prueban contra los valores, en orden. El primero
# es el que exige el requerimiento de de visitas web.
FORMATOS_FECHA = [
    ("%d/%m/%Y %H:%M", r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$"),
    ("%d/%m/%Y", r"^\d{2}/\d{2}/\d{4}$"),
    ("%Y-%m-%d %H:%M:%S", r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"),
    ("%Y-%m-%d %H:%M", r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$"),
    ("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}$"),
    ("%m/%d/%Y %H:%M", r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$"),
]

PATRON_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PATRON_ENTERO = re.compile(r"^-?\d+$")
PATRON_DECIMAL = re.compile(r"^-?\d+[.,]\d+$")

# Marcadores de ausencia que aparecen en los archivos de de visitas web. Un guion no
# es un valor: es la forma en que ese proveedor escribe «no hubo dato».
AUSENTES = {"", "-", "NULL", "null", "N/A", "n/a", "NaN"}

LIMITE_BYTES = 200 * 1024 * 1024
MUESTRA_DEFECTO = 5000


def _detectar_terminadores(crudo: bytes) -> dict[str, Any]:
    """Cuenta terminadores de línea y evalúa el riesgo de CRLF con comillas.

    Es el control que nació del hallazgo del proyecto: CRLF combinado con
    campos entrecomillados hace que MySQL pierda el delimitador y absorba
    renglones en silencio. Si el archivo trae las dos cosas, se advierte antes
    de que alguien lo cargue.
    """
    crlf = crudo.count(b"\r\n")
    cr_solo = crudo.count(b"\r") - crlf
    lf_solo = crudo.count(b"\n") - crlf
    tiene_comillas = b'"' in crudo
    riesgo = crlf > 0 and tiene_comillas
    return {
        "crlf": crlf,
        "cr_sueltos": cr_solo,
        "lf": lf_solo,
        "campos_entrecomillados": tiene_comillas,
        "riesgo_crlf_comillas": riesgo,
        "nota": (
            "CRLF junto con campos entrecomillados. Al cargar con "
            "LINES TERMINATED BY '\\n', el retorno de carro queda después de la "
            "comilla de cierre y MySQL puede absorber los renglones siguientes sin "
            "avisar. Normalizar a LF sobre una copia antes de cargar, y reconciliar "
            "filas leídas contra filas insertadas."
            if riesgo else
            "Sin riesgo detectado de terminadores de línea."
        ),
    }


def _detectar_delimitador(texto: str) -> str:
    """Elige el delimitador probando cuál produce el conteo de columnas más estable."""
    candidatos = [",", ";", "\t", "|"]
    lineas = [l for l in texto.split("\n")[:50] if l.strip()]
    if not lineas:
        return ","
    mejor, mejor_puntaje = ",", -1.0
    for d in candidatos:
        conteos = [len(next(csv.reader(io.StringIO(l), delimiter=d))) for l in lineas]
        if not conteos or max(conteos) < 2:
            continue
        comun = Counter(conteos).most_common(1)[0]
        puntaje = comun[1] / len(conteos) * comun[0]  # estabilidad × ancho
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = d, puntaje
    return mejor


def _inferir_tipo(valores: list[str]) -> dict[str, Any]:
    """Clasifica una columna a partir de sus valores no ausentes."""
    presentes = [v for v in valores if v not in AUSENTES]
    if not presentes:
        return {"tipo": "vacia", "detalle": "La columna llegó sin un solo valor"}

    if all(PATRON_EMAIL.match(v) for v in presentes):
        return {"tipo": "email", "detalle": "Todos los valores cumplen patrón de correo"}
    invalidos_email = [v for v in presentes if "@" in v and not PATRON_EMAIL.match(v)]
    if invalidos_email and sum(1 for v in presentes if "@" in v) / len(presentes) > 0.8:
        return {
            "tipo": "email",
            "detalle": f"Parece correo, pero {len(invalidos_email)} valores no cumplen el patrón",
            "invalidos": invalidos_email[:5],
        }

    for fmt, patron in FORMATOS_FECHA:
        rx = re.compile(patron)
        if all(rx.match(v) for v in presentes):
            return {"tipo": "fecha", "formato": fmt,
                    "detalle": f"Todos los valores cumplen {fmt}"}

    if all(PATRON_ENTERO.match(v) for v in presentes):
        nums = [int(v) for v in presentes]
        return {"tipo": "entero", "minimo": min(nums), "maximo": max(nums),
                "detalle": f"Enteros entre {min(nums)} y {max(nums)}"}
    if all(PATRON_ENTERO.match(v) or PATRON_DECIMAL.match(v) for v in presentes):
        return {"tipo": "decimal", "detalle": "Valores numéricos con decimales"}

    distintos = set(presentes)
    if len(distintos) <= 8:
        return {"tipo": "categoria", "valores": sorted(distintos),
                "detalle": f"{len(distintos)} valores distintos: catálogo cerrado"}

    largos = [len(v) for v in presentes]
    return {"tipo": "texto", "largo_maximo": max(largos),
            "detalle": f"Texto libre, hasta {max(largos)} caracteres"}


def _candidatos_llave(filas: list[list[str]], encabezados: list[str]) -> list[dict[str, Any]]:
    """Busca columnas y pares de columnas que podrían identificar un registro.

    Devuelve el porcentaje de unicidad de cada candidato en vez de un veredicto:
    que `email + fecha` sea único en la muestra no prueba que sea la llave de
    negocio, y ese fue justamente el hallazgo que cambió el diseño del ETL.
    """
    total = len(filas)
    if total == 0:
        return []
    candidatos: list[dict[str, Any]] = []

    for i, nombre in enumerate(encabezados):
        valores = [f[i] for f in filas if i < len(f) and f[i] not in AUSENTES]
        if not valores:
            continue
        unicidad = len(set(valores)) / total
        if unicidad > 0.5:
            candidatos.append({
                "columnas": [nombre],
                "unicidad": round(unicidad, 4),
                "duplicados": total - len(set(valores)),
            })

    # Pares: solo con columnas que ya tienen buena dispersión, para no
    # generar combinaciones sin sentido.
    dispersas = [
        i for i, n in enumerate(encabezados)
        if len({f[i] for f in filas if i < len(f) and f[i] not in AUSENTES}) > total * 0.1
    ][:6]
    for a in dispersas:
        for b in dispersas:
            if a >= b:
                continue
            pares = [(f[a], f[b]) for f in filas if a < len(f) and b < len(f)]
            unicidad = len(set(pares)) / total
            if unicidad > 0.9:
                candidatos.append({
                    "columnas": [encabezados[a], encabezados[b]],
                    "unicidad": round(unicidad, 4),
                    "duplicados": total - len(set(pares)),
                })

    candidatos.sort(key=lambda c: (-c["unicidad"], len(c["columnas"])))
    return candidatos[:6]


def perfilar(ruta: str, muestra: int = MUESTRA_DEFECTO) -> dict[str, Any]:
    """Perfila un archivo plano y devuelve estructura, tipos y anomalías.

    Args:
        ruta: ruta absoluta del archivo a perfilar.
        muestra: máximo de filas de datos a analizar.

    Returns:
        Diccionario con: archivo, terminadores, delimitador, encabezados,
        conteos, perfil por columna, candidatos a llave y anomalías.

    Raises:
        FileNotFoundError, ValueError: rutas inválidas o archivos ilegibles.
    """
    if not os.path.isfile(ruta):
        raise FileNotFoundError(
            f"No existe el archivo '{ruta}'. Da una ruta absoluta a un archivo "
            f"de texto plano (csv, txt o tsv)."
        )
    tam = os.path.getsize(ruta)
    if tam == 0:
        raise ValueError(f"El archivo '{ruta}' está vacío.")
    if tam > LIMITE_BYTES:
        raise ValueError(
            f"El archivo pesa {tam / 1e6:.0f} MB y el límite del perfilado es "
            f"{LIMITE_BYTES / 1e6:.0f} MB. Perfila una muestra del archivo."
        )

    with open(ruta, "rb") as f:
        crudo = f.read()

    terminadores = _detectar_terminadores(crudo)

    codificacion = "utf-8-sig"
    try:
        texto = crudo.decode(codificacion)
    except UnicodeDecodeError:
        codificacion = "latin-1"
        texto = crudo.decode(codificacion, errors="replace")

    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    delimitador = _detectar_delimitador(texto)

    lector = csv.reader(io.StringIO(texto), delimiter=delimitador, quotechar='"')
    todas = [f for f in lector if any(c.strip() for c in f)]
    if not todas:
        raise ValueError(f"El archivo '{ruta}' no tiene filas legibles.")

    encabezados = [c.strip() for c in todas[0]]
    datos = todas[1:]
    total_datos = len(datos)
    analizadas = datos[:muestra]

    esperado = len(encabezados)
    irregulares = [
        {"linea": i + 2, "columnas": len(f)}
        for i, f in enumerate(datos) if len(f) != esperado
    ]

    perfil_columnas = []
    for i, nombre in enumerate(encabezados):
        valores = [f[i] if i < len(f) else "" for f in analizadas]
        presentes = [v for v in valores if v not in AUSENTES]
        conteo_ausentes = Counter(v for v in valores if v in AUSENTES)
        info = _inferir_tipo(valores)
        perfil_columnas.append({
            "posicion": i + 1,
            "nombre": nombre or f"(sin nombre, posición {i + 1})",
            "no_nulos": len(presentes),
            "pct_presente": round(len(presentes) / len(analizadas) * 100, 1) if analizadas else 0.0,
            "distintos": len(set(presentes)),
            "formas_de_ausencia": dict(conteo_ausentes),
            "ejemplos": presentes[:3],
            **info,
        })

    anomalias = []
    if irregulares:
        anomalias.append({
            "tipo": "columnas_irregulares",
            "gravedad": "rechazo",
            "detalle": f"{len(irregulares)} líneas no tienen {esperado} columnas",
            "ejemplos": irregulares[:5],
        })
    if terminadores["riesgo_crlf_comillas"]:
        anomalias.append({
            "tipo": "crlf_con_comillas",
            "gravedad": "advertencia",
            "detalle": terminadores["nota"],
        })
    vacias = [c["nombre"] for c in perfil_columnas if c["tipo"] == "vacia"]
    if vacias:
        anomalias.append({
            "tipo": "columnas_vacias",
            "gravedad": "advertencia",
            "detalle": f"{len(vacias)} columnas llegaron sin un solo valor",
            "columnas": vacias,
        })
    sin_nombre = [c["posicion"] for c in perfil_columnas if not encabezados[c["posicion"] - 1]]
    if sin_nombre:
        anomalias.append({
            "tipo": "encabezados_sin_nombre",
            "gravedad": "advertencia",
            "detalle": f"Las posiciones {sin_nombre} no tienen encabezado",
        })

    return {
        "archivo": os.path.basename(ruta),
        "ruta": ruta,
        "bytes": tam,
        "codificacion": codificacion,
        "delimitador": {"\t": "tab"}.get(delimitador, delimitador),
        "terminadores": terminadores,
        "columnas": esperado,
        "filas_datos": total_datos,
        "filas_analizadas": len(analizadas),
        "encabezados": encabezados,
        "perfil_columnas": perfil_columnas,
        "candidatos_llave": _candidatos_llave(analizadas, encabezados),
        "anomalias": anomalias,
    }
