#!/usr/bin/env bash
# Prepara ~/podcast_agent: venv + dependencias fijadas + tests. No instala nada con Homebrew.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "Falta ffmpeg/ffprobe. Instálalo con:  brew install ffmpeg   y vuelve a correr este script." >&2
  exit 1
fi

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.13 python3.12 python3; do
    if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
      PY="$c"; break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "Se necesita Python >= 3.12 (numpy 2.5 / scipy 1.18 / librosa 1.0)." >&2
  echo "Opciones: instalador de python.org, o  brew install python@3.13  (pedir permiso si lo hace Claude)." >&2
  exit 1
fi
echo "Python: $($PY --version) ($(command -v "$PY")) · arquitectura: $(uname -m)"

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python - <<'EOF'
import importlib.util, platform
mlx = importlib.util.find_spec("mlx_whisper") is not None
fw = importlib.util.find_spec("faster_whisper") is not None
print(f"Transcripción: mlx-whisper={'sí' if mlx else 'no'} · faster-whisper={'sí' if fw else 'no'} · {platform.machine()}")
EOF
python -m pytest -q
echo "Listo. Activa el entorno con:  source .venv/bin/activate"
