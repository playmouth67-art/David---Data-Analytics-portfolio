# podcast_agent — instrucciones para Claude Code

Proyecto: herramienta local que convierte multicámara + mics aislados de podcasts largos en un timeline editado para
DaVinci Resolve Studio. **Encargo completo, reglas y criterios de aceptación: `docs/SPEC.md` (léelo entero antes de
trabajar).** Estado, métricas y decisiones tomadas: `docs/HANDOFF.md`.

## Reglas de trabajo (del encargo; no negociables)

- Habla con el usuario **en español**. Después de cada fase: ✅ qué se hizo, archivos tocados, métricas.
  Nunca afirmes progreso sin salida de herramientas que lo respalde.
- Trabaja solo dentro de `~/podcast_agent`. `/Users/davicho/Downloads/podcasts/` es **SOLO LECTURA**.
  Todo lo generado va a `~/podcast_agent/output/<episodio>/`.
- Resolve: crea **solo** el proyecto `PODCAST_AUTO`, timelines `AUTO_EDIT_<episodio>_v{n}` y sus bins. Nunca
  modifiques ni borres proyectos, timelines, bins o media existentes.
- **Antes de escribir cualquier llamada a la API de Resolve**, lee
  `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/README.txt` y usa solo métodos
  documentados ahí. Nunca inventes métodos.
- Secretos solo por variables de entorno (`HF_TOKEN`). Nunca en el código.
- Solo cambios pedidos: sin GUI, dashboards, uploads ni exports verticales.

## STOP: pide permiso antes de

- instalar paquetes de Homebrew, torch/pyannote/whisperx o cualquier dependencia (o **modelo**) de más de 500 MB
  (ojo: la primera transcripción con `mlx-community/whisper-large-v3-turbo` descarga ~1.6 GB);
- usar `HF_TOKEN`;
- seguir si el mapeo de hablantes o cámaras es ambiguo, o si la confianza de sync es baja;
- llamar un método que no esté en el README de Resolve;
- escribir en Resolve fuera de `PODCAST_AUTO`, sus timelines y sus bins;
- seguir después de un error que no resolviste en 2 intentos.

Las fases marcadas STOP en `docs/SPEC.md` terminan esperando la aprobación del usuario.

## Comandos

```bash
source .venv/bin/activate                      # crear con: bash scripts/setup_mac.sh
python -m pytest -q                            # 43 tests; ~2 min la 1.ª vez (genera el fixture sintético)
bash scripts/phase0_discovery.sh               # informe de la Fase 0 (solo lectura) -> output/phase0_report.txt
python -m podcast_agent run --episode <carpeta> --dry-run [--excerpt 10m] [--set clave.sub=valor] [--force]
python -m podcast_agent run --episode <carpeta> --stage ingest|sync|audio|analyze|edit|resolve|all
python -m tests.fixtures --out /tmp/EP_SYNTH   # episodio sintético para probar a mano
```

En los fixtures, la transcripción usa el backend `fixture` (`--set transcription.backend=fixture`), que lee
`_fixture_truth.json`. Con un episodio real, `auto` elige mlx-whisper (Apple Silicon) o faster-whisper.

## Mapa del código (`podcast_agent/`)

| Módulo | Qué hace |
|---|---|
| `cli.py` | Orquesta etapas, caché, exports y `report.json` |
| `config.py` / `config.yaml` | Todos los umbrales; `Paths` arma `output/<ep>[__excerpt_X]/` |
| `timecode.py` | Frames enteros, tasas como `Fraction`, DF/NDF |
| `cache.py` | `cache/<etapa>.json`; el hash incluye entradas, config y código del módulo |
| `media.py` | ffmpeg/ffprobe, decodificación en streaming |
| `ingest.py` | Detecta cámaras y mics, fps, resolución, TC, canales; un frame por cámara |
| `sync.py` | Correlación FFT de envolventes, ventanas finas, deriva lineal o por tramos; `CameraClock` |
| `audio_clean.py` | Cadena ffmpeg, compensa la latencia de afftdn, limitador enlazado -14 LUFS / -1 dBTP |
| `transcribe.py` | Backends mlx / faster / fixture |
| `analyze.py` | VAD + sangrado, crosstalk, palabras, muletillas, aire muerto, KEEP_PAUSE, risas, temas, menciones |
| `viral.py` | Ventanas de 20–90 s, energía / pyin / risas / ritmo / semántico → `clips.json` |
| `edit_engine.py` | Remociones globales, cold open, planos (J/L, monólogos, reacciones, wide), uniones ocultas, marcadores, QC → `edl.json` |
| `export.py` | `edl.json` → FCPXML 1.9 y OTIO |
| `resolve_bridge.py` | **Stub: es la Fase 4** |
| `tests/fixtures.py` | Generador del episodio sintético + `mapping_from_truth` |
