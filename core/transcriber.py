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
        self._actual_device = None

    # Ordre de fallback si le compute_type demande n'est pas supporte
    _CUDA_COMPUTE_FALLBACKS = ["float16", "int8", "float32"]

    def _try_load_cuda(self, compute_type: str):
        """Tente de charger le modele sur CUDA avec le compute_type donne."""
        from faster_whisper import WhisperModel
        import numpy as np

        model = WhisperModel(
            self._model_size,
            device="cuda",
            compute_type=compute_type,
            download_root=self._models_dir,
        )
        # Test rapide pour verifier que CUDA fonctionne vraiment
        test_audio = np.zeros(16000, dtype=np.float32)
        list(model.transcribe(test_audio, language="fr")[0])
        return model

    def load_model(self) -> None:
        """Charge le modele faster-whisper."""
        from faster_whisper import WhisperModel

        if self._device == "auto" or self._device == "cuda":
            # Essayer le compute_type demande, puis les fallbacks
            types_to_try = [self._compute_type]
            for fb in self._CUDA_COMPUTE_FALLBACKS:
                if fb not in types_to_try:
                    types_to_try.append(fb)

            for ct in types_to_try:
                try:
                    self._model = self._try_load_cuda(ct)
                    self._actual_device = "cuda"
                    if ct != self._compute_type:
                        logger.warning(
                            "compute_type '%s' non supporte, fallback sur '%s'",
                            self._compute_type, ct,
                        )
                    logger.info("Modele Whisper %s charge sur GPU (CUDA, %s)",
                                self._model_size, ct)
                    return
                except Exception as e:
                    logger.info("CUDA avec %s echoue (%s), essai suivant...", ct, e)

            if self._device == "cuda":
                logger.warning("Tous les compute_type CUDA ont echoue, fallback CPU")

        device = "cpu"
        compute = "int8"

        self._model = WhisperModel(
            self._model_size,
            device=device,
            compute_type=compute,
            download_root=self._models_dir,
        )
        self._actual_device = device
        logger.info("Modele Whisper %s charge sur %s (%s)", self._model_size, device, compute)

    def _reload_on_cpu(self):
        """Recharge le modele sur CPU en cas d'erreur CUDA."""
        logger.warning("Rechargement du modele Whisper sur CPU...")
        from faster_whisper import WhisperModel
        self._model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
            download_root=self._models_dir,
        )
        self._actual_device = "cpu"
        logger.info("Modele Whisper %s recharge sur CPU (int8)", self._model_size)

    def transcribe(self, audio_path: Path, language: str = "fr",
                   on_progress: Optional[Callable[[float], None]] = None,
                   use_vad: bool = True) -> TranscriptionResult:
        """Transcrit un fichier WAV et retourne les segments avec timestamps.

        Args:
            use_vad: Active le filtre VAD. Mettre a False pour les petits morceaux
                     (transcription en direct) car le VAD peut supprimer tout l'audio.
        """
        if self._model is None:
            raise RuntimeError("Le modele n'est pas charge. Appelez load_model() d'abord.")

        logger.info("Transcription de %s (vad=%s)...", audio_path.name, use_vad)

        try:
            return self._do_transcribe(audio_path, language, on_progress, use_vad)
        except RuntimeError as e:
            err_str = str(e).lower()
            if "cublas" in err_str or "cuda" in err_str or "library" in err_str:
                logger.warning("Erreur CUDA pendant la transcription: %s", e)
                self._reload_on_cpu()
                return self._do_transcribe(audio_path, language, on_progress, use_vad)
            raise

    def _do_transcribe(self, audio_path: Path, language: str,
                       on_progress: Optional[Callable[[float], None]],
                       use_vad: bool = True) -> TranscriptionResult:
        """Execute la transcription."""
        transcribe_kwargs = dict(
            language=language,
            beam_size=5,
            word_timestamps=True,
        )
        if use_vad:
            transcribe_kwargs["vad_filter"] = True
            transcribe_kwargs["vad_parameters"] = dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            )
        else:
            transcribe_kwargs["vad_filter"] = False

        segments_gen, info = self._model.transcribe(
            str(audio_path),
            **transcribe_kwargs,
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
        self._actual_device = None
        logger.info("Modele Whisper decharge")
