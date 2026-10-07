# podcast_agent

Herramienta local en Python que convierte el material crudo de un podcast largo (60–180 min) en un timeline editado
para DaVinci Resolve Studio. Trabaja con multicámara y mics aislados. El objetivo es un corte que se sienta hecho por
una persona: sin aire muerto, sin planos estáticos, con un buen gancho y sin jump cuts visibles.

> **Estado:** fases 1–3 completas y probadas sobre fixtures sintéticos (42 tests en verde).
> La fase 4 (puente a Resolve) se hace en tu Mac después de leer el README de scripting instalado.
> Mientras tanto, `--dry-run` genera el `.fcpxml` y el `.otio` para importar a mano.

## Instalación (macOS)

```bash
# 1) ffmpeg
brew install ffmpeg

# 2) Proyecto (este folder = ~/podcast_agent)
cp -R 8_Podcast_Agent ~/podcast_agent && cd ~/podcast_agent
python3 -m venv .venv && source .venv/bin/activate     # Python ≥ 3.12
pip install -r requirements.txt                         # en Apple Silicon instala mlx-whisper (Metal)

# 3) Probar
python -m pytest -q
```

Variables para el scripting de Resolve (fase 4; requiere Studio y *Preferences > System > General > External
scripting = Local*):

```bash
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
```

Los secretos solo entran por variables de entorno (`HF_TOKEN`). Hoy no se usa ninguno.

## Uso

```bash
python -m podcast_agent run --episode /Users/davicho/Downloads/podcasts/EP01 --stage all
python -m podcast_agent run --episode .../EP01 --dry-run                 # sin Resolve: edl.json, clips.json, .fcpxml, .otio
python -m podcast_agent run --episode .../EP01 --dry-run --excerpt 10m   # solo los primeros 10 min (o 45m+10m)
python -m podcast_agent run --episode .../EP01 --stage analyze           # hasta una etapa
python -m podcast_agent run --episode .../EP01 --set dead_air.min_silence_s=1.0   # sobrescribir config
```

Etapas: `ingest → sync → audio → analyze → edit → resolve`. Cada una escribe `output/<episodio>/cache/<etapa>.json` y
se salta si el hash de sus entradas no cambió (`--force` la rehace). La carpeta del episodio es **solo lectura**: todo
lo que se genera va a `output/<episodio>/`.

### Flujo con un episodio real

1. `--stage analyze`: detecta cámaras y mics, sincroniza, limpia el audio y transcribe. Exporta un frame por cámara a
   `output/<ep>/frames/` y escribe una **propuesta** en `output/<ep>/mapping.yaml`: qué mic es de quién (con
   evidencia de la transcripción) y qué cámara es la wide o el close-up de cada persona.
2. Revisas el mapeo (Claude te lo propone después de ver los frames), pones `confirmed: true`.
3. Claude lee `viral_candidates.json` y escribe `semantic_scores.json` (puntaje semántico, gancho y título en
   español). Sin ese archivo se usa una heurística, y la herramienta lo avisa.
4. `--dry-run --excerpt 10m` para revisar un tramo, y luego el episodio completo.

### Salidas (`output/<episodio>/`)

| Archivo | Qué es |
|---|---|
| `edl.json` | Fuente única de verdad: piezas, remociones, planos (con razón), pistas de audio, marcadores y QC |
| `AUTO_EDIT_<ep>_v{n}.fcpxml` / `.otio` | Timeline para importar (File > Import > Timeline) |
| `clips.json` | Top 10 clips virales: inicio/fin en frases, gancho, título, desglose del puntaje |
| `audio_processed/` | Mics procesados (archivos nuevos, nunca se escribe sobre los originales) |
| `frames/` | Un frame por cámara para proponer roles |
| `mapping.yaml` | Mapeo mic ↔ persona ↔ cámara (requiere `confirmed: true`) |
| `report.json` | Métricas de QC de la corrida |

## Cómo decide

- **Sync:** correlación FFT de envolventes band-pass (200–3000 Hz) a 8 kHz. Primero una búsqueda gruesa en todo el
  archivo, luego ≥3 ventanas finas (inicio, medio, final, y una cada 10 min) y un ajuste lineal de deriva. Si el
  residuo pasa de 1 frame, densifica las ventanas y usa un modelo por tramos. Si la confianza es baja, **se detiene**.
  La deriva se corrige plano por plano: cada plano mapea su frame de cámara con el modelo medido.
- **Audio:** highpass 80 Hz → `afftdn` (su latencia de ~25 ms se mide y se compensa) → de-esser → compresor. Después,
  una ganancia común y un **limitador enlazado** (una sola curva de ganancia sobre la suma, aplicada a todas las
  pistas). Así la mezcla queda en -14 LUFS / -1 dBTP sin dejar de tener una pista por mic.
- **VAD:** umbral = piso de ruido + 12 dB (con -40 dBFS de respaldo). Un mic está activo solo si supera a todos los
  demás por ≥6 dB. El crosstalk se detecta con la presencia de voz propia, compensando el sangrado medido entre cada
  par de mics.
- **Transcripción:** mlx-whisper en Apple Silicon (o faster-whisper), con timestamps por palabra y las muletillas en
  el `initial_prompt`. Se transcribe cada mic con el sangrado atenuado, y los bordes de cada palabra se ajustan a la
  energía real.
- **Muletillas:** solo sueltas, con ≥0.1 s libres a cada lado y los otros mics en silencio. "este", "pues", "bueno" y
  "o sea" exigen además una pausa después y contexto de turno ("este libro" o "está bueno" no se tocan).
- **Aire muerto:** todos los mics bajo umbral por >0.8 s. Se dejan 0.25 s de pausa y nunca se corta a menos de 30 ms
  de una palabra. Las pausas después de una pregunta o antes de un remate se marcan `KEEP_PAUSE`.
- **Video:** muestra al hablante activo con J-cuts (el video sigue al audio 6–12 frames después) y L-cuts (el audio
  del anterior se sostiene 8–15 frames sobre la imagen nueva), sin repetir offset. Los monólogos se rompen cada
  3–6 s según la energía (reacción, wide, punch-in 110–115%). Crosstalk >1 s o cambio de tema → wide. Cada unión de
  audio cae exactamente en un cambio de ángulo o de encuadre. Para que eso sea siempre posible, las remociones que
  dejarían un plano de menos de 1.2 s se descartan (y se reportan).
- **Cold open:** el mejor clip de 15–45 s, un sting y luego el inicio. El momento también queda en su lugar
  original. En el primer minuto no hay silencios >0.8 s y los planos duran ≤4 s.
- **Marcadores:** rojo = viral, amarillo = KEEP_PAUSE / revisar, azul = tema, morado = sync dudoso, verde = B-roll o
  lower-third cada 45–90 s (personas, lugares, números, productos).

Todos los umbrales están en `config.yaml`.

## Tests

`tests/fixtures.py` genera con ffmpeg y numpy un episodio sintético:

- 3 cámaras con offsets de 0.5 s, 3.2 s y -0.8 s, y 50 ppm de deriva en una;
- 2 mics con sangrado;
- muletillas, silencios, una pregunta, un remate con risas, crosstalk y un cambio de tema.

La verdad de terreno (`_fixture_truth.json`) se usa con el backend de transcripción `fixture`. Los tests verifican
los criterios de aceptación de forma independiente:

- sync a ±1 frame en 25 puntos por cámara;
- 0 cortes dentro de palabras (contra las palabras de la verdad);
- planos entre 1.2 y 6 s;
- 100% de uniones ocultas;
- exports que coinciden frame a frame con `edl.json`;
- `--dry-run` sin Resolve.

```bash
python -m pytest -q                          # ~2 min la primera vez (genera el fixture), luego usa caché
python -m tests.fixtures --out /tmp/EP_SYNTH # generar un episodio sintético a mano
```

## Limitaciones conocidas

- La voz sintética no llega a -14 LUFS con -1 dBTP (queda en ~-14.8). Con voz real se espera que sí.
- Las menciones (B-roll) usan heurística de mayúsculas y números, sin un modelo NER.
- pyannote (dos personas en un mic) y WhisperX no se instalan: requieren torch (>500 MB) y se piden con permiso.
- El puente a Resolve (fase 4) todavía no existe: depende del README de scripting de tu instalación.
