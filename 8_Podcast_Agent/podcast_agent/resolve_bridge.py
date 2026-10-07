"""Puente a DaVinci Resolve Studio — FASE 4 (pendiente de aprobación).

Se implementa en la Fase 4, después de leer el README de scripting instalado en
tu Mac y fijar la ruta de integración. Mientras tanto usa --dry-run e importa
el .fcpxml a mano (File > Import > Timeline).
"""
from .errors import ResolveUnavailable


def run_resolve(paths, cfg, edl, ingest, timeline_name, files):
    raise ResolveUnavailable(
        "El puente a Resolve es la Fase 4 y todavía no está implementado: hay que verificar primero el README "
        "de scripting de tu instalación (no se inventan métodos). Los archivos para importar a mano ya están en "
        f"{files['fcpxml']} y {files['otio']}.")
