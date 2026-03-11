"""Traitement audio : mix, resampling, normalisation.

Optimise pour les reunions longues (1-2h) :
- Traitement par morceaux pour limiter la RAM
- Streaming ecriture WAV (pas de chargement complet)
"""

import logging
import wave
from math import gcd
from pathlib import Path
from typing import Tuple

import numpy as np
from scipy.signal import resample_poly

from config.constants import WHISPER_SAMPLE_RATE

logger = logging.getLogger(__name__)

# Taille d'un morceau : 60 secondes a la fois (a la frequence source)
CHUNK_DURATION_SEC = 60


def read_wav_as_float(path: Path) -> Tuple[np.ndarray, int, int]:
    """Lit un WAV et retourne (samples_float32, sample_rate, channels)."""
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            samples = samples.reshape(-1, channels)
    return samples, rate, channels


def read_wav_chunk(wf: wave.Wave_read, n_frames: int, channels: int) -> np.ndarray:
    """Lit un morceau de WAV en float32."""
    raw = wf.readframes(n_frames)
    if len(raw) == 0:
        return np.array([], dtype=np.float32)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels)
        samples = samples.mean(axis=1)  # mono
    return samples


def write_wav(path: Path, samples: np.ndarray, rate: int, channels: int = 1) -> None:
    """Ecrit un tableau float32 en WAV 16-bit."""
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


def to_mono(samples: np.ndarray) -> np.ndarray:
    """Convertit en mono si stereo/multicanal."""
    if samples.ndim == 1:
        return samples
    return samples.mean(axis=1)


def resample_audio(samples: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
    """Resample un signal audio vers le taux cible."""
    if orig_rate == target_rate:
        return samples
    g = gcd(orig_rate, target_rate)
    up = target_rate // g
    down = orig_rate // g
    return resample_poly(samples, up, down).astype(np.float32)


def normalize(samples: np.ndarray) -> np.ndarray:
    """Normalise en amplitude crete."""
    peak = np.max(np.abs(samples))
    if peak > 0:
        return samples / peak * 0.95
    return samples


class AudioProcessor:
    """Traitement audio post-enregistrement, optimise pour les longues reunions."""

    @staticmethod
    def get_wav_info(wav_path: Path) -> Tuple[int, int, int]:
        """Retourne (sample_rate, channels, n_frames) d'un WAV."""
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getframerate(), wf.getnchannels(), wf.getnframes()

    @staticmethod
    def get_wav_duration(wav_path: Path) -> float:
        """Retourne la duree d'un WAV en secondes."""
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()

    @staticmethod
    def estimate_disk_usage(mic_path: Path, loopback_path: Path) -> float:
        """Estime l'espace disque necessaire en Mo (fichiers existants + mix)."""
        mic_size = mic_path.stat().st_size / (1024 * 1024) if mic_path.exists() else 0
        lb_size = loopback_path.stat().st_size / (1024 * 1024) if loopback_path.exists() else 0
        # Le mix 16kHz mono sera bien plus petit que les originaux
        duration = AudioProcessor.get_wav_duration(mic_path) if mic_path.exists() else 0
        mix_size = duration * WHISPER_SAMPLE_RATE * 2 / (1024 * 1024)  # 16-bit mono
        return mic_size + lb_size + mix_size

    @staticmethod
    def mix_to_mono(mic_path: Path, loopback_path: Path, output_path: Path) -> Path:
        """Mixe micro + loopback en WAV mono 16kHz par morceaux (economise la RAM).

        Pour 2h d'enregistrement, ne charge que ~60 sec a la fois en memoire
        au lieu de charger les 2 fichiers complets (~4 Go).
        """
        mic_rate, mic_ch, mic_frames = AudioProcessor.get_wav_info(mic_path)
        lb_rate, lb_ch, lb_frames = AudioProcessor.get_wav_info(loopback_path)

        mic_duration = mic_frames / mic_rate
        lb_duration = lb_frames / lb_rate
        total_duration = max(mic_duration, lb_duration)

        logger.info(
            "Mix par morceaux: micro=%.0fs (%dHz %dch), systeme=%.0fs (%dHz %dch)",
            mic_duration, mic_rate, mic_ch, lb_duration, lb_rate, lb_ch,
        )

        # Ouvrir les fichiers source
        mic_wf = wave.open(str(mic_path), "rb")
        lb_wf = wave.open(str(loopback_path), "rb")

        # Ouvrir le fichier de sortie
        out_wf = wave.open(str(output_path), "wb")
        out_wf.setnchannels(1)
        out_wf.setsampwidth(2)
        out_wf.setframerate(WHISPER_SAMPLE_RATE)

        # Nombre de frames source par morceau de 60 sec
        mic_chunk_frames = CHUNK_DURATION_SEC * mic_rate
        lb_chunk_frames = CHUNK_DURATION_SEC * lb_rate

        # Passe 1 : calculer le pic global pour la normalisation
        global_peak = 0.0
        processed_sec = 0.0

        mic_wf.rewind()
        lb_wf.rewind()

        while processed_sec < total_duration:
            mic_chunk = read_wav_chunk(mic_wf, mic_chunk_frames, mic_ch)
            lb_chunk = read_wav_chunk(lb_wf, lb_chunk_frames, lb_ch)

            # Resampler en 16kHz
            mic_16k = resample_audio(mic_chunk, mic_rate, WHISPER_SAMPLE_RATE) if len(mic_chunk) > 0 else np.array([], dtype=np.float32)
            lb_16k = resample_audio(lb_chunk, lb_rate, WHISPER_SAMPLE_RATE) if len(lb_chunk) > 0 else np.array([], dtype=np.float32)

            # Aligner les longueurs du morceau
            target_len = int(CHUNK_DURATION_SEC * WHISPER_SAMPLE_RATE)
            mic_16k = _pad_or_trim(mic_16k, target_len)
            lb_16k = _pad_or_trim(lb_16k, target_len)

            mixed = 0.5 * mic_16k + 0.5 * lb_16k
            chunk_peak = np.max(np.abs(mixed)) if len(mixed) > 0 else 0.0
            global_peak = max(global_peak, chunk_peak)

            processed_sec += CHUNK_DURATION_SEC

        # Passe 2 : ecrire les donnees normalisees
        norm_factor = 0.95 / global_peak if global_peak > 0 else 1.0

        mic_wf.rewind()
        lb_wf.rewind()
        processed_sec = 0.0
        total_written = 0

        while processed_sec < total_duration:
            mic_chunk = read_wav_chunk(mic_wf, mic_chunk_frames, mic_ch)
            lb_chunk = read_wav_chunk(lb_wf, lb_chunk_frames, lb_ch)

            mic_16k = resample_audio(mic_chunk, mic_rate, WHISPER_SAMPLE_RATE) if len(mic_chunk) > 0 else np.array([], dtype=np.float32)
            lb_16k = resample_audio(lb_chunk, lb_rate, WHISPER_SAMPLE_RATE) if len(lb_chunk) > 0 else np.array([], dtype=np.float32)

            target_len = int(CHUNK_DURATION_SEC * WHISPER_SAMPLE_RATE)
            mic_16k = _pad_or_trim(mic_16k, target_len)
            lb_16k = _pad_or_trim(lb_16k, target_len)

            mixed = (0.5 * mic_16k + 0.5 * lb_16k) * norm_factor
            mixed = np.clip(mixed, -1.0, 1.0)

            # Ne pas ecrire au-dela de la duree reelle
            remaining_samples = int((total_duration - processed_sec) * WHISPER_SAMPLE_RATE)
            if remaining_samples < len(mixed):
                mixed = mixed[:remaining_samples]

            if len(mixed) == 0:
                break

            pcm = (mixed * 32767).astype(np.int16)
            out_wf.writeframes(pcm.tobytes())
            total_written += len(mixed)

            processed_sec += CHUNK_DURATION_SEC

        mic_wf.close()
        lb_wf.close()
        out_wf.close()

        final_duration = total_written / WHISPER_SAMPLE_RATE
        logger.info("Mix cree: %s (%.1f min, %.1f Mo)",
                     output_path.name, final_duration / 60,
                     output_path.stat().st_size / (1024 * 1024))
        return output_path

    @staticmethod
    def resample_wav(input_path: Path, target_rate: int = WHISPER_SAMPLE_RATE) -> Path:
        """Resample un WAV vers le taux cible par morceaux."""
        rate, channels, n_frames = AudioProcessor.get_wav_info(input_path)
        if rate == target_rate and channels == 1:
            return input_path

        output_path = input_path.parent / f"{input_path.stem}_16k.wav"
        chunk_frames = CHUNK_DURATION_SEC * rate

        in_wf = wave.open(str(input_path), "rb")
        out_wf = wave.open(str(output_path), "wb")
        out_wf.setnchannels(1)
        out_wf.setsampwidth(2)
        out_wf.setframerate(target_rate)

        frames_read = 0
        while frames_read < n_frames:
            chunk = read_wav_chunk(in_wf, chunk_frames, channels)
            if len(chunk) == 0:
                break
            resampled = resample_audio(chunk, rate, target_rate)
            pcm = (np.clip(resampled, -1.0, 1.0) * 32767).astype(np.int16)
            out_wf.writeframes(pcm.tobytes())
            frames_read += chunk_frames

        in_wf.close()
        out_wf.close()
        logger.info("Resample %s: %dHz -> %dHz", input_path.name, rate, target_rate)
        return output_path

    @staticmethod
    def prepare_channel_for_diarization(wav_path: Path) -> Tuple[np.ndarray, int]:
        """Prepare un canal audio pour la diarisation : mono 16kHz float32.

        Note: pour 2h, cela utilise ~460 Mo de RAM. C'est acceptable car
        la diarisation a besoin d'un acces aleatoire aux timestamps.
        """
        samples, rate, channels = read_wav_as_float(wav_path)
        mono = to_mono(samples)
        resampled = resample_audio(mono, rate, WHISPER_SAMPLE_RATE)
        return resampled, WHISPER_SAMPLE_RATE


def _pad_or_trim(arr: np.ndarray, target_len: int) -> np.ndarray:
    """Ajuste la taille d'un tableau au target_len."""
    if len(arr) == 0:
        return np.zeros(target_len, dtype=np.float32)
    if len(arr) >= target_len:
        return arr[:target_len]
    return np.pad(arr, (0, target_len - len(arr)))
