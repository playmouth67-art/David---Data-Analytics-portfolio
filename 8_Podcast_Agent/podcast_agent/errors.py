"""Errores manejados: cada uno trae un mensaje claro y el siguiente paso."""


class AgentError(Exception):
    next_step = ""

    def __init__(self, message, next_step=None):
        super().__init__(message)
        if next_step:
            self.next_step = next_step

    def render(self):
        msg = f"ERROR: {self}"
        if self.next_step:
            msg += f"\nSiguiente paso: {self.next_step}"
        return msg


class FfmpegMissing(AgentError):
    next_step = "Instala ffmpeg con `brew install ffmpeg` y vuelve a correr."


class EmptyEpisode(AgentError):
    next_step = "Copia los archivos de cámara y los mics del episodio a la carpeta y vuelve a correr."


class MappingError(AgentError):
    next_step = ("Revisa output/<episodio>/mapping.yaml: asigna cada mic a una persona y cada cámara "
                 "a un rol (wide / closeup de X), pon `confirmed: true` y vuelve a correr.")


class SyncError(AgentError):
    next_step = ("Revisa que la cámara tenga audio de referencia audible y que cubra el mismo tramo que los mics. "
                 "Mira output/<episodio>/cache/sync.json para ver la confianza por ventana.")


class DriftError(SyncError):
    next_step = ("La deriva no es lineal ni corregible por segmentos. Revisa si la cámara cortó o se pausó "
                 "(archivos partidos) y vuelve a correr; o excluye esa cámara en mapping.yaml.")


class TranscriptionUnavailable(AgentError):
    next_step = ("En Apple Silicon: `pip install mlx-whisper`. En Intel: `pip install faster-whisper`. "
                 "Luego vuelve a correr la etapa analyze.")


class ResolveUnavailable(AgentError):
    next_step = ("Abre DaVinci Resolve Studio, activa Preferences > System > General > External scripting = Local, "
                 "o usa --dry-run e importa el .fcpxml a mano (File > Import > Timeline).")


class NotDocumented(AgentError):
    next_step = "Ese método no aparece en el README de scripting instalado; no se llama. Revisa la versión de Resolve."
