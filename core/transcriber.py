"""Transcription locale avec faster-whisper."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Word:
    start: float
    end: float
    word: str
    probability: float


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: List[Word] = field(default_factory=list)
    speaker: Optional[str] = None


@dataclass
class TranscriptionResult:
    language: str
    segments: List[TranscriptSegment]
    duration: float


class Transcriber:
    """Wrapper faster-whisper pour la transcription locale en francais."""

    def __init__(self, model_size: str = "large-v3", device: str = "auto",
                 compute_type: str = "float16", models_dir: str = "./models"):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._models_dir = models_dir
        self._model = None

    def load_model(self) -> None:
        """Charge le modele faster-whisper."""
        from faster_whisper import WhisperModel

        if self._device == "auto":
            # Tenter CUDA d'abord, fallback sur CPU
            try:
                self._model = WhisperModel(
                    self._model_size,
                    device="cuda",
                    compute_type=self._compute_type,
                    download_root=self._models_dir,
                )
                logger.info("Modele Whisper %s charge sur GPU (CUDA)", self._model_size)
                return
            except Exception as e:
                logger.info("CUDA non disponible (%s), fallback sur CPU", e)

        device = "cpu" if self._device == "auto" else self._device
        compute = "int8" if device == "cpu" else self._compute_type

        self._model = WhisperModel(
            self._model_size,
            device=device,
            compute_type=compute,
            download_root=self._models_dir,
        )
        logger.info("Modele Whisper %s charge sur %s (%s)", self._model_size, device, compute)

    def transcribe(self, audio_path: Path, language: str = "fr",
                   on_progress: Optional[Callable[[float], None]] = None) -> TranscriptionResult:
        """Transcrit un fichier WAV et retourne les segments avec timestamps."""
        if self._model is None:
            raise RuntimeError("Le modele n'est pas charge. Appelez load_model() d'abord.")

        logger.info("Transcription de %s...", audio_path.name)

        segments_gen, info = self._model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )

        duration = info.duration
        result_segments = []

        for seg in segments_gen:
            words = []
            if seg.words:
                for w in seg.words:
                    words.append(Word(
                        start=w.start,
                        end=w.end,
                        word=w.word,
                        probability=w.probability,
                    ))

            result_segments.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                words=words,
            ))

            # Notifier la progression
            if on_progress and duration > 0:
                progress = min(seg.end / duration, 1.0)
                on_progress(progress)

        logger.info("Transcription terminee: %d segments, %.1f sec", len(result_segments), duration)

        return TranscriptionResult(
            language=info.language,
            segments=result_segments,
            duration=duration,
        )

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> None:
        """Libere la memoire du modele."""
        self._model = None
        logger.info("Modele Whisper decharge")
