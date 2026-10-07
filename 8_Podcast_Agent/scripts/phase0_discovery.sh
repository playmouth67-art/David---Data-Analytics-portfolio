#!/usr/bin/env bash
# Fase 0: descubrimiento de SOLO LECTURA. No instala, no escribe en Resolve ni en la carpeta de media.
# Guarda el informe en output/phase0_report.txt.
cd "$(dirname "$0")/.."
mkdir -p output
OUT=output/phase0_report.txt
README="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/README.txt"
APP="/Applications/DaVinci Resolve/DaVinci Resolve.app"
{
echo "== Sistema =="; sw_vers; uname -m; sysctl -n machdep.cpu.brand_string; sysctl -n hw.memsize | awk '{print $1/1073741824 " GB RAM"}'
echo; echo "== GPU / Metal =="; system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Chipset|Metal|Cores|VRAM"
echo; echo "== Python =="; which -a python3 python3.11 python3.12 python3.13 2>/dev/null; python3 --version
[ -x .venv/bin/python ] && echo "venv: $(.venv/bin/python --version)"
echo; echo "== Herramientas =="; for t in ffmpeg ffprobe brew git; do printf "%-8s %s\n" "$t" "$(command -v $t || echo NO)"; done
ffmpeg -hide_banner -version 2>/dev/null | head -1
ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libx264 && echo "libx264: sí" || echo "libx264: no"
ffmpeg -hide_banner -filters 2>/dev/null | grep -cE " (afftdn|deesser|acompressor|ebur128|highpass|amix) " | xargs echo "filtros de audio requeridos presentes (de 6):"
brew --version 2>/dev/null | head -1
echo; echo "== DaVinci Resolve =="
if [ -d "$APP" ]; then
  defaults read "$APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null | xargs echo "versión:"
  defaults read "$APP/Contents/Info.plist" CFBundleGetInfoString 2>/dev/null
  defaults read "$APP/Contents/Info.plist" CFBundleName 2>/dev/null
  ls "$APP/Contents/Libraries/Fusion/fusionscript.so" 2>/dev/null || echo "fusionscript.so NO encontrado"
else
  echo "Resolve NO instalado en $APP"
fi
pgrep -fl "DaVinci Resolve" >/dev/null && echo "Resolve está ABIERTO" || echo "Resolve está cerrado"
echo; echo "== README de scripting =="
if [ -f "$README" ]; then
  ls -la "$README"
  echo "-- Python soportado según el README:"; grep -n -iE "python ?[0-9]|python3" "$README" | head -20
  echo "-- Métodos clave:"
  for m in GetProductName GetVersionString CreateProject LoadProject GetProjectListInCurrentFolder SetSetting \
           GetMediaPool GetRootFolder AddSubFolder SetCurrentFolder ImportMedia CreateEmptyTimeline \
           AppendToTimeline ImportTimelineFromFile GetTimelineCount GetTimelineByIndex SetCurrentTimeline \
           AddTrack GetTrackCount GetItemListInTrack GetStartFrame AddMarker GetMarkers SetProperty GetProperty; do
    n=$(grep -c "\b$m\b" "$README"); printf "  %-30s %s\n" "$m" "$([ "$n" -gt 0 ] && echo "sí ($n)" || echo NO)"
  done
  echo "-- Propiedades de TimelineItem:"; grep -n -E "ZoomX|ZoomY|Pan|Tilt" "$README" | head -10
  echo "-- clipInfo / recordFrame:"; grep -n -E "recordFrame|mediaType|startFrame|endFrame" "$README" | head -10
else
  echo "README NO encontrado en $README"
fi
echo; echo "== Prueba de conexión a la API (solo lectura) =="
if [ -f "$README" ] && grep -q "GetProductName" "$README" && grep -q "GetVersionString" "$README"; then
  export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
  export RESOLVE_SCRIPT_LIB="$APP/Contents/Libraries/Fusion/fusionscript.so"
  export PYTHONPATH="${PYTHONPATH:-}:$RESOLVE_SCRIPT_API/Modules/"
  python3 -c "import DaVinciResolveScript as d; r=d.scriptapp('Resolve'); print('API inalcanzable (¿Resolve abierto? ¿Studio? ¿External scripting = Local?)' if r is None else ('Producto:', r.GetProductName(), 'Versión:', r.GetVersionString()))" 2>&1
else
  echo "Se omite: GetProductName/GetVersionString no confirmados en el README."
fi
echo; echo "== Media (solo lectura) =="; ls -la /Users/davicho/Downloads/podcasts/ 2>&1
} 2>&1 | tee "$OUT"
echo; echo "Informe guardado en $OUT"
