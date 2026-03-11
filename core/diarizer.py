"""Diarisation par double canal : micro (Vous) vs systeme (Distant).

Optimise pour les reunions longues (1-2h) :
- Charge les canaux une seule fois (reuse du pipeline)
- Option pour recevoir des arrays pre-charges
"""

import gc
import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from config.constants import WHISPER_SAMPLE_RATE, ENERGY_RATIO_THRESHOLD, DEFAULT_MIN_SILENCE_DURATION
from core.transcriber import TranscriptionResult

logger = logging.getLogger(__name__)


class DualChannelDiarizer:
    """Attribue les locuteurs en comparant l'energie entre micro et loopback."""

    def __init__(self, ratio_threshold: float = ENERGY_RATIO_THRESHOLD,
                 min_silence_duration: float = DEFAULT_MIN_SILENCE_DURATION):
        self._ratio_threshold = ratio_threshold
        self._min_silence = min_silence_duration

    def diarize(self, mic_path: Path, loopback_path: Path,
                transcript: TranscriptionResult,
                mic_16k: Optional[np.ndarray] = None,
                lb_16k: Optional[np.ndarray] = None) -> TranscriptionResult:
        """Pour chaque segment, determine qui parle en comparant l'energie RMS.

        Si mic_16k/lb_16k sont fournis, les utilise directement (evite de
        recharger les fichiers). Sinon, charge et resample depuis les WAV.
        """
        if mic_16k is None or lb_16k is None:
            from core.audio_processor import read_wav_as_float, to_mono, resample_audio
            logger.info("Chargement des canaux pour diarisation...")

            mic_samples, mic_rate, mic_ch = read_wav_as_float(mic_path)
            mic_mono = to_mono(mic_samples)
            del mic_samples
            mic_16k = resample_audio(mic_mono, mic_rate, WHISPER_SAMPLE_RATE)
            del mic_mono

            lb_samples, lb_rate, lb_ch = read_wav_as_float(loopback_path)
            lb_mono = to_mono(lb_samples)
            del lb_samples
            lb_16k = resample_audio(lb_mono, lb_rate, WHISPER_SAMPLE_RATE)
            del lb_mono

            gc.collect()

        duration_min = max(len(mic_16k), len(lb_16k)) / WHISPER_SAMPLE_RATE / 60
        logger.info("Diarisation de %.0f min d'audio, %d segments...",
                     duration_min, len(transcript.segments))

        for segment in transcript.segments:
            start_sample = int(segment.start * WHISPER_SAMPLE_RATE)
            end_sample = int(segment.end * WHISPER_SAMPLE_RATE)

            mic_window = self._safe_slice(mic_16k, start_sample, end_sample)
            lb_window = self._safe_slice(lb_16k, start_sample, end_sample)

            mic_rms = self._rms(mic_window)
            lb_rms = self._rms(lb_window)

            if mic_rms > lb_rms * self._ratio_threshold:
                segment.speaker = "Vous"
            elif lb_rms > mic_rms * self._ratio_threshold:
                segment.speaker = "Distant"
            else:
                segment.speaker = "Vous" if mic_rms >= lb_rms else "Distant"

        # Sous-segmentation des locuteurs distants
        self._label_distant_speakers(transcript)

        you_count = sum(1 for s in transcript.segments if s.speaker == "Vous")
        dist_count = len(transcript.segments) - you_count
        logger.info("Diarisation terminee: %d segments (Vous: %d, Distant: %d)",
                     len(transcript.segments), you_count, dist_count)
        return transcript

    def _label_distant_speakers(self, transcript: TranscriptionResult) -> None:
        """Tente de distinguer les locuteurs distants par les silences."""
        current_speaker_id = 0
        last_distant_end = -1.0

        for segment in transcript.segments:
            if segment.speaker != "Distant":
                continue

            if last_distant_end >= 0 and (segment.start - last_distant_end) > self._min_silence:
                current_speaker_id += 1

            if current_speaker_id > 0:
                segment.speaker = f"Distant {current_speaker_id + 1}"
            else:
                segment.speaker = "Distant 1"

            last_distant_end = segment.end

        # Si un seul locuteur distant, garder "Distant" sans numero
        distant_speakers = set()
        for seg in transcript.segments:
            if seg.speaker and seg.speaker.startswith("Distant"):
                distant_speakers.add(seg.speaker)

        if len(distant_speakers) <= 1:
            for seg in transcript.segments:
                if seg.speaker and seg.speaker.startswith("Distant"):
                    seg.speaker = "Distant"

    @staticmethod
    def _safe_slice(arr: np.ndarray, start: int, end: int) -> np.ndarray:
        start = max(0, start)
        end = min(len(arr), end)
        if start >= end:
            return np.zeros(1, dtype=np.float32)
        return arr[start:end]

    @staticmethod
    def _rms(samples: np.ndarray) -> float:
        if len(samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(samples ** 2)))
