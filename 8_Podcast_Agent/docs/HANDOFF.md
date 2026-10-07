# Traspaso: de la sesión en la nube a la Mac mini

## Estado de las fases

| Fase | Estado | Notas |
|---|---|---|
| 0. Descubrimiento | ⏳ **Pendiente en la Mac** | La sesión anterior corrió en un contenedor Linux x86_64 sin Resolve. `scripts/phase0_discovery.sh` junta todo |
| 1. Scaffold, fixtures, ingest, sync | ✅ | Validado en Linux |
| 2. Audio y análisis | ✅ | Transcripción con el backend `fixture`: Hugging Face estaba bloqueado, Whisper real **sin probar** |
| 3. Edit engine y viral | ✅ **Esperando aprobación** | Métricas abajo |
| 4. Puente a Resolve | ⏳ | `resolve_bridge.py` es un stub |
| 5. Episodio real | ⏳ | La carpeta `/Users/davicho/Downloads/podcasts/` está vacía |
| 6. Informe final | ⏳ | |

## Métricas validadas en la nube (fixture de 6 min, 29.97 DF, 3 cámaras, 2 mics)

- **Sync:** cam1 +3.200 s y 50.2 ppm (verdad: 3.2 s, 50 ppm); cam2 -0.800 s; cam3 +0.500 s. Error < 0.2 ms, ±1 frame
  en 25 puntos por cámara. Una deriva de 400 ppm (≈5 frames) queda corregida plano por plano.
- **Audio:** true peak -1.7 dBTP ✅; -14.8 LUFS (techo de la voz sintética; con voz real hay que verificarlo);
  desfase de 0–1 muestra.
- **Muletillas:** 13/13 removibles detectadas y removidas, 0 falsos positivos; "este libro" y "está bueno" se quedan.
- **Aire muerto:** 8/8; KEEP_PAUSE de pregunta y de remate respetadas; crosstalk detectado.
- **Edit:** 149 planos, promedio 2.54 s, máximo 3.87 s, mínimo 1.2 s; 0 fuera de rango; 25/25 uniones ocultas;
  0 cortes dentro de palabras; 0 J/L repetidos; 0 silencios en el primer minuto.
- **Cortes por razón:** monologue_break 87 · speaker_change 18 · reaction 16 · filler_hide 13 · silence_cut 12 ·
  crosstalk_wide 1 · cold_open 1.
- **Duración:** 360.5 s de origen → 338.2 s del episodio + cold open 43.7 s + sting 1 s = 379.6 s.
- **Tests:** pytest 43/43 en verde; pyflakes limpio.

## Decisiones tomadas (el usuario puede revisarlas)

1. **L-cut:** en el encargo sonaba igual que el J-cut, así que se implementó en su forma clásica. J = el video sigue al
   audio 6–12 frames después. L = el audio del anterior se sostiene 8–15 frames sobre la imagen del siguiente (se ve
   al que escucha).
2. **Regla 6 contra regla 12:** si dos uniones de audio dejarían un plano de menos de 1.2 s, se descarta la remoción
   de menor prioridad y se reporta en `rejected_removals`.
3. **Detección de crosstalk:** la regla de "+6 dB sobre todos" se usa para el hablante activo. El crosstalk usa la
   "voz propia", compensando el sangrado medido entre cada par de mics; si no, dos personas a volumen parecido nunca
   cuentan como activas.
4. **Energía de retención y viral:** se mide en el audio **original**, porque el compresor y el limitador aplanan la
   dinámica.
5. **Puntaje semántico:** la herramienta escribe `viral_candidates.json`; Claude lo lee y escribe
   `output/<ep>/semantic_scores.json` (`{"windows": [{start, end, score, hook, title}]}`). Sin ese archivo se usa una
   heurística y se avisa.
6. **Primer minuto:** las KEEP_PAUSE se recortan a 0.7 s (con 0.8 s, el redondeo a frames dejaba aire muerto).
7. **Ceros:** los puntos de edición caen dentro de pausas (todos los mics bajo umbral, con guarda de 30 ms a las
   palabras), no se ajustan a cruces por cero a nivel de muestra. Los cortes en el NLE son por frame.

## Preguntas abiertas para la Fase 0 y la Fase 4 (verificar en la Mac)

- **Python de Resolve:** las dependencias piden Python ≥ 3.12 (numpy 2.5, scipy 1.18, librosa 1.0). Si Resolve
  necesita un Python más viejo, el puente puede correr en otro venv que solo lea `edl.json`. Decídelo con el README.
- **Ruta de integración** (a) `ImportTimelineFromFile` con el `.fcpxml`/`.otio`, o (b) `AppendToTimeline` con
  `clipInfo` + `SetProperty` (ZoomX/ZoomY) + `AddMarker`. Elegir **solo** con lo que documente el README instalado.
- **Por verificar empíricamente** con un clip de prueba en PODCAST_AUTO:
  - si `endFrame` es inclusivo;
  - si `recordFrame` es absoluto (incluye el TC de inicio del timeline, 01:00:00:00) o relativo;
  - si `startFrame` es relativo al inicio del clip o al TC de origen;
  - si `AddMarker` usa frames relativos.
- **FCPXML:** hoy sale con `tcStart="0s"`. Revisar que Resolve importe bien las escalas (`adjust-transform`), los
  carriles de audio negativos y los marcadores. Los colores de marcador solo se pueden poner por API.
- **Modelo de Whisper:** `large-v3-turbo` pesa ~1.6 GB, así que **hay que pedir permiso** antes de la primera
  transcripción real.

## Cómo mudarlo a la Mac

```bash
# Opción A: tarball (recomendada; sin el resto del portafolio)
mkdir -p ~/podcast_agent && tar -xzf ~/Downloads/podcast_agent_v0.1.0.tar.gz -C ~/podcast_agent

# Opción B: desde git
git clone --depth 1 --branch claude/relaxed-johnson-bfv91y \
  https://github.com/playmouth67-art/David---Data-Analytics-portfolio.git /tmp/portfolio
cp -R /tmp/portfolio/8_Podcast_Agent ~/podcast_agent

# Luego, en los dos casos:
cd ~/podcast_agent
bash scripts/setup_mac.sh         # venv + requirements + pytest (no instala nada con brew)
cd ~/podcast_agent && git init && git add -A && git commit -m "podcast_agent v0.1.0 (fases 1-3)"   # opcional
claude                            # nueva sesión de Claude Code aquí
```

## Primer mensaje para la nueva sesión (copiar y pegar)

```
Estás en ~/podcast_agent en mi Mac mini (verifícalo con uname -m y sw_vers). Lee CLAUDE.md, docs/SPEC.md y
docs/HANDOFF.md antes de nada. Las fases 1–3 se hicieron en una sesión en la nube (Linux) y están aprobadas.
Ahora haz la Fase 0 real en esta Mac:
1) corre bash scripts/phase0_discovery.sh y python -m pytest -q;
2) lee completo el README de scripting de Resolve y lista los métodos que necesitamos y si existen
   (CreateProject, LoadProject, ImportMedia, AddSubFolder, CreateEmptyTimeline, AppendToTimeline con recordFrame,
   ImportTimelineFromFile, AddMarker, SetProperty con ZoomX/ZoomY, GetItemListInTrack, AddTrack, SetSetting);
3) dame el informe en español, la ruta de integración elegida (a o b) con su justificación, y las respuestas a
   las preguntas abiertas de HANDOFF.md.
Luego STOP y espera mi aprobación para la Fase 4.
```
