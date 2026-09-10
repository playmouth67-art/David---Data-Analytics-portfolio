#!/usr/bin/env python3
"""Ejercita las 14 herramientas del servidor contra la base real.

No es un sustituto de una suite de pruebas: es la verificación de que cada
herramienta corre, devuelve algo con sentido y no revienta con datos reales.
Cada caso imprime un extracto para poder revisar el contenido a ojo.
"""

import asyncio
import json
import os
import sys

import server

VERDE, ROJO, GRIS, FIN = "\033[92m", "\033[91m", "\033[90m", "\033[0m"

# Los archivos de muestra viven en el caso 5, que es el proceso que este
# servidor opera. La ruta se resuelve desde la ubicación de este archivo para
# que el arnés funcione desde cualquier directorio de trabajo; se puede
# apuntar a otro lado con ETL_SEED_DIR.
AQUI = os.path.dirname(os.path.abspath(__file__))
SEMILLAS = os.environ.get(
    "ETL_SEED_DIR",
    os.path.normpath(os.path.join(AQUI, "..", "5_ETL_Visitas_Web", "data", "seed")),
)


def semilla(nombre: str) -> str:
    """Ruta a un archivo de muestra del caso 5."""
    return os.path.join(SEMILLAS, nombre)


CASOS = [
    ("estado_actual",        "visitas_estado_actual",        {}),
    ("listar_ejecuciones",   "visitas_listar_ejecuciones",   {}),
    ("listar_solo_fallidas", "visitas_listar_ejecuciones",   {"estatus": "FALLIDO"}),
    ("detalle_ejecucion_1",  "visitas_detalle_ejecucion",    {"id_ejecucion": 1}),
    ("detalle_ultima",       "visitas_detalle_ejecucion",    {}),
    ("listar_archivos",      "visitas_listar_archivos",      {}),
    ("archivos_rechazados",  "visitas_listar_archivos",      {"estatus": "RECHAZADO"}),
    ("errores_todos",        "visitas_consultar_errores",    {"limite": 5}),
    ("errores_v03",          "visitas_consultar_errores",    {"codigo_error": "V-03",
                                                             "incluir_registro": True}),
    ("explicar_v04",         "visitas_explicar_codigo",      {"codigo_error": "V-04"}),
    ("explicar_catalogo",    "visitas_explicar_codigo",      {}),
    ("explicar_inexistente", "visitas_explicar_codigo",      {"codigo_error": "V-99"}),
    ("diagnosticar_2",       "visitas_diagnosticar",         {"id_ejecucion": 2}),
    ("diagnosticar_1",       "visitas_diagnosticar",         {"id_ejecucion": 1}),
    ("diagnosticar_3",       "visitas_diagnosticar",         {"id_ejecucion": 3}),
    ("diagnosticar_4",       "visitas_diagnosticar",         {"id_ejecucion": 4}),
    ("reconciliar",          "visitas_reconciliar",          {}),
    ("casos_ambiguos",       "visitas_casos_ambiguos",       {"limite": 3}),
    ("ambiguos_dedupe",      "visitas_casos_ambiguos",       {"tipo": "badmail_perdido_en_dedupe",
                                                             "limite": 3}),
    ("perfilar",             "visitas_perfilar_archivo",     {"ruta": semilla("report_7.txt")}),
    ("perfilar_inexistente", "visitas_perfilar_archivo",     {"ruta": "/no/existe.csv"}),
    ("proponer",             "visitas_proponer_validaciones", {"ruta": semilla("report_9.txt"),
                                                              "nombre_tabla": "stg_nueva"}),
    ("practica_diagnostico", "visitas_caso_practica",        {"modo": "diagnostico",
                                                             "mostrar_respuesta": True}),
    ("practica_regla",       "visitas_caso_practica",        {"modo": "regla",
                                                             "mostrar_respuesta": True}),
    ("practica_anomalia",    "visitas_caso_practica",        {"modo": "anomalia"}),
    ("dictamenes_vacio",     "visitas_listar_dictamenes",    {}),
]


async def llamar(nombre_tool: str, args: dict) -> str:
    resultado = await server.mcp._tool_manager.call_tool(nombre_tool, {"params": args})
    if isinstance(resultado, list) and resultado:
        primero = resultado[0]
        return getattr(primero, "text", str(primero))
    return str(resultado)


async def main() -> int:
    fallos = 0
    detalle = "--detalle" in sys.argv

    for etiqueta, tool, args in CASOS:
        try:
            salida = await llamar(tool, args)
            problema = salida.startswith("Error inesperado")
            marca = ROJO + "FALLA" + FIN if problema else VERDE + "  ok " + FIN
            fallos += problema
            primera = salida.strip().split("\n")[0][:95]
            print(f"[{marca}] {etiqueta:22} {GRIS}{len(salida):>6} car{FIN}  {primera}")
            if detalle:
                print(GRIS + "\n".join("      " + l for l in salida.split("\n")[:40]) + FIN + "\n")
        except Exception as e:
            fallos += 1
            print(f"[{ROJO}FALLA{FIN}] {etiqueta:22} excepción: {type(e).__name__}: {e}")

    # Escritura: registrar un dictamen sobre un caso ambiguo real y releerlo.
    print("\n--- ciclo de escritura ---")
    try:
        crudo = await llamar("visitas_casos_ambiguos",
                             {"tipo": "fecha_anterior_al_envio", "limite": 1,
                              "response_format": "json"})
        casos = json.loads(crudo)["tipos"][0]["casos"]
        if not casos:
            print(f"[{GRIS} skip {FIN}] sin casos ambiguos para dictaminar")
        else:
            c = casos[0]
            r = await llamar("visitas_registrar_dictamen", {
                "tipo_caso": "fecha_anterior_al_envio",
                "email": c["email"],
                "fecha_envio": c["fecha_envio"],
                "clasificacion": "REQUIERE_NEGOCIO",
                "justificacion": ("La apertura precede al envío por pocos minutos, patrón "
                                  "consistente con desfase de zona horaria en el origen y no "
                                  "con un dato corrupto. Sin confirmación del proveedor no se "
                                  "puede cerrar la regla."),
                "confianza": 0.65,
            })
            ok = r.startswith("✅")
            print(f"[{VERDE+'  ok '+FIN if ok else ROJO+'FALLA'+FIN}] registrar_dictamen"
                  f"        {r.strip().splitlines()[0][:80]}")
            fallos += not ok

            r2 = await llamar("visitas_listar_dictamenes", {})
            ok2 = "Dictámenes del agente" in r2
            print(f"[{VERDE+'  ok '+FIN if ok2 else ROJO+'FALLA'+FIN}] listar_dictamenes"
                  f"         {len(r2)} car")
            fallos += not ok2

            r3 = await llamar("visitas_casos_ambiguos",
                              {"tipo": "fecha_anterior_al_envio", "limite": 3,
                               "solo_sin_dictamen": True, "response_format": "json"})
            restantes = json.loads(r3)["tipos"][0]["casos"]
            excluido = all(x["email"] != c["email"] or x["fecha_envio"] != c["fecha_envio"]
                           for x in restantes)
            print(f"[{VERDE+'  ok '+FIN if excluido else ROJO+'FALLA'+FIN}] filtro_sin_dictamen"
                  f"       el registro dictaminado {'ya no aparece' if excluido else 'SIGUE apareciendo'}")
            fallos += not excluido

            r4 = await llamar("visitas_registrar_dictamen", {
                "tipo_caso": "fecha_anterior_al_envio",
                "email": "noexiste@ejemplo.com",
                "fecha_envio": "2013-02-08 18:30:00",
                "clasificacion": "VALIDO",
                "justificacion": "Prueba de que rechaza una llave que no está en estadistica.",
                "confianza": 0.5,
            })
            ok4 = r4.startswith("No hay ningún registro")
            print(f"[{VERDE+'  ok '+FIN if ok4 else ROJO+'FALLA'+FIN}] rechaza_llave_falsa"
                  f"       {r4.strip()[:70]}")
            fallos += not ok4
    except Exception as e:
        fallos += 1
        print(f"[{ROJO}FALLA{FIN}] ciclo de escritura: {type(e).__name__}: {e}")

    print(f"\n{'='*70}")
    if fallos:
        print(f"{ROJO}{fallos} caso(s) con problema{FIN}")
    else:
        print(f"{VERDE}Todos los casos pasaron{FIN}")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
