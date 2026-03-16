"""Constantes audio et application."""

# Audio
WHISPER_SAMPLE_RATE = 16000
DEFAULT_RECORDING_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 1
DEFAULT_CHUNK_SIZE = 1024
AUDIO_FORMAT_BITS = 16

# Niveaux audio (pour VU-metres)
LEVEL_UPDATE_INTERVAL_MS = 50
TIMER_UPDATE_INTERVAL_MS = 1000
LIVE_CHUNK_INTERVAL_MIN = 1  # Transcription en direct par defaut: toutes les 1 min

# Diarisation
DEFAULT_VAD_THRESHOLD = 0.03
DEFAULT_MIN_SILENCE_DURATION = 0.8
ENERGY_RATIO_THRESHOLD = 1.5

# LLM
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "mistral"
MAX_TOKENS_PER_CHUNK = 6000
CHUNK_OVERLAP_SECONDS = 30

# Application
APP_NAME = "MCC - TRANSCRIPT"
APP_VERSION = "1.1.0"

# Mise a jour (remplacer par votre URL GitHub)
GITHUB_REPO = "Tobaz34/mcc_transcript"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_ZIP_URL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip"
DEFAULT_THEME = "dark"
MIN_WINDOW_WIDTH = 800
MIN_WINDOW_HEIGHT = 600
DEFAULT_WINDOW_WIDTH = 1100
DEFAULT_WINDOW_HEIGHT = 750
