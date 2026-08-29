#!/bin/bash
# Restaura los archivos de origen desde data/seed.
#
# El ETL purga data/source por diseño, así que sin esto no se puede repetir
# una corrida completa. Se resuelve la ruta a partir de la ubicación del
# script, no del directorio de trabajo: así funciona desde cualquier lado y
# en cualquier máquina.
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p data/source data/landing
rm -f data/source/report_*.txt
rm -f data/landing/* 2>/dev/null || true
cp data/seed/report_*.txt data/source/

# Fecha de modificación antigua para que el quiet period de 10 minutos no
# omita los archivos recién copiados.
touch -t 202608010000 data/source/report_*.txt

echo "Origen restaurado:"
ls -l data/source/
