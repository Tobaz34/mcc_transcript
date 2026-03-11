"""Configuration de l'application avec persistence JSON."""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from config.constants import (
    WHISPER_SAMPLE_RATE,
    DEFAULT_RECORDING_SAMPLE_RATE,
    DEFAULT_CHANNELS,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_VAD_THRESHOLD,
    DEFAULT_MIN_SILENCE_DURATION,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_THEME,
)

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"


@dataclass
class AppSettings:
    # Audio
    mic_device_index: Optional[int] = None
    loopback_device_index: Optional[int] = None
    sample_rate: int = WHISPER_SAMPLE_RATE
    recording_sample_rate: int = DEFAULT_RECORDING_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    chunk_size: int = DEFAULT_CHUNK_SIZE

    # Transcription
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"
    whisper_compute_type: str = "float16"
    language: str = "fr"

    # Diarisation
    diarization_mode: str = "dual_channel"
    vad_threshold: float = DEFAULT_VAD_THRESHOLD
    min_silence_duration: float = DEFAULT_MIN_SILENCE_DURATION

    # LLM
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_host: str = DEFAULT_OLLAMA_HOST

    # Chemins
    output_directory: str = "./output"
    models_directory: str = "./models"

    # GUI
    theme: str = DEFAULT_THEME

    def save(self, config_dir: Path) -> None:
        config_dir.mkdir(parents=True, exist_ok=True)
        path = config_dir / SETTINGS_FILENAME
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2, ensure_ascii=False)
            logger.info("Configuration sauvegardee dans %s", path)
        except OSError as e:
            logger.error("Impossible de sauvegarder la configuration: %s", e)

    def auto_configure_hardware(self) -> str:
        """Detecte le materiel et configure automatiquement le modele Whisper.
        Retourne un resume de la configuration choisie."""
        try:
            from core.hardware import detect_hardware, recommend_model, format_recommendation
            hw = detect_hardware()
            rec = recommend_model(hw)

            self.whisper_model = rec.whisper_model
            self.whisper_device = rec.whisper_device
            self.whisper_compute_type = rec.whisper_compute_type

            summary = f"{hw.summary()}\n\n{format_recommendation(rec)}"
            logger.info("Auto-configuration materielle:\n%s", summary)
            return summary
        except Exception as e:
            logger.warning("Erreur auto-detection materielle: %s", e)
            return f"Detection echouee ({e}), configuration par defaut conservee."

    @classmethod
    def load(cls, config_dir: Path) -> "AppSettings":
        path = config_dir / SETTINGS_FILENAME
        if not path.exists():
            logger.info("Aucune configuration trouvee, auto-detection du materiel...")
            settings = cls()
            settings.auto_configure_hardware()
            settings.save(config_dir)
            return settings
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            known_fields = {f.name for f in cls.__dataclass_fields__.values()}
            filtered = {k: v for k, v in data.items() if k in known_fields}
            settings = cls(**filtered)
            logger.info("Configuration chargee depuis %s", path)
            return settings
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.warning("Erreur de chargement de la configuration: %s", e)
            return cls()
