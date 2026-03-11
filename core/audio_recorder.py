"""Enregistrement dual-stream : microphone + son systeme (WASAPI loopback)."""

import logging
import struct
import threading
import time
import wave
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pyaudiowpatch as pyaudio

from config.settings import AppSettings
from core.audio_devices import AudioDeviceManager

logger = logging.getLogger(__name__)


class DualStreamRecorder:
    """Enregistre le microphone et le son systeme simultanement."""

    def __init__(self, settings: AppSettings, device_manager: AudioDeviceManager):
        self._settings = settings
        self._device_manager = device_manager
        self._pa: Optional[pyaudio.PyAudio] = None
        self._mic_stream: Optional[pyaudio.Stream] = None
        self._loopback_stream: Optional[pyaudio.Stream] = None
        self._mic_writer: Optional[wave.Wave_write] = None
        self._loopback_writer: Optional[wave.Wave_write] = None
        self._is_recording = False
        self._is_monitoring = False
        self._lock = threading.Lock()
        self._start_time: float = 0.0

        # Niveaux audio temps reel (0.0 - 1.0)
        self._mic_level: float = 0.0
        self._loopback_level: float = 0.0

        # Parametres des streams (remplis au demarrage)
        self._mic_rate: int = 0
        self._mic_channels: int = 0
        self._loopback_rate: int = 0
        self._loopback_channels: int = 0

    def start_monitoring(self) -> bool:
        """Demarre le monitoring audio (niveaux seulement, sans enregistrer)."""
        if self._is_recording or self._is_monitoring:
            return False
        try:
            self._pa = pyaudio.PyAudio()

            mic_device = self._get_mic_device()
            if mic_device:
                self._mic_rate = int(mic_device["defaultSampleRate"])
                self._mic_channels = min(mic_device["maxInputChannels"], 1) or 1
                self._mic_stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=self._mic_channels,
                    rate=self._mic_rate,
                    input=True,
                    input_device_index=mic_device["index"],
                    frames_per_buffer=self._settings.chunk_size,
                    stream_callback=self._monitor_callback_mic,
                )

            loopback_device = self._get_loopback_device()
            if loopback_device:
                self._loopback_rate = int(loopback_device["defaultSampleRate"])
                self._loopback_channels = loopback_device["maxInputChannels"]
                self._loopback_stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=self._loopback_channels,
                    rate=self._loopback_rate,
                    input=True,
                    input_device_index=loopback_device["index"],
                    frames_per_buffer=self._settings.chunk_size,
                    stream_callback=self._monitor_callback_lb,
                )

            self._is_monitoring = True
            logger.info("Monitoring audio demarre")
            return True
        except Exception as e:
            logger.warning("Impossible de demarrer le monitoring: %s", e)
            self._close_streams()
            return False

    def stop_monitoring(self) -> None:
        """Arrete le monitoring audio."""
        if not self._is_monitoring:
            return
        self._is_monitoring = False
        self._close_streams()
        self._mic_level = 0.0
        self._loopback_level = 0.0

    def _monitor_callback_mic(self, in_data, frame_count, time_info, status):
        self._mic_level = self._compute_rms_level(in_data)
        return (None, pyaudio.paContinue)

    def _monitor_callback_lb(self, in_data, frame_count, time_info, status):
        self._loopback_level = self._compute_rms_level(in_data)
        return (None, pyaudio.paContinue)

    def _close_streams(self):
        """Ferme les streams audio."""
        for stream in (self._mic_stream, self._loopback_stream):
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
        self._mic_stream = None
        self._loopback_stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    @property
    def is_monitoring(self) -> bool:
        return self._is_monitoring

    def start_recording(self, output_dir: Path) -> None:
        """Demarre l'enregistrement des deux flux audio."""
        with self._lock:
            if self._is_recording:
                raise RuntimeError("Enregistrement deja en cours")

            # Arreter le monitoring s'il tourne
            if self._is_monitoring:
                self.stop_monitoring()

            output_dir.mkdir(parents=True, exist_ok=True)
            self._pa = pyaudio.PyAudio()

            # --- Microphone ---
            mic_device = self._get_mic_device()
            if mic_device is None:
                raise RuntimeError("Aucun microphone disponible")

            self._mic_rate = int(mic_device["defaultSampleRate"])
            self._mic_channels = min(mic_device["maxInputChannels"], 1)
            if self._mic_channels == 0:
                self._mic_channels = 1

            mic_path = output_dir / "micro.wav"
            self._mic_writer = wave.open(str(mic_path), "wb")
            self._mic_writer.setnchannels(self._mic_channels)
            self._mic_writer.setsampwidth(2)  # 16-bit
            self._mic_writer.setframerate(self._mic_rate)

            self._mic_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._mic_channels,
                rate=self._mic_rate,
                input=True,
                input_device_index=mic_device["index"],
                frames_per_buffer=self._settings.chunk_size,
                stream_callback=self._mic_callback,
            )

            # --- Loopback (son systeme) ---
            loopback_device = self._get_loopback_device()
            if loopback_device is None:
                # Fermer le flux micro si le loopback echoue
                self._mic_stream.stop_stream()
                self._mic_stream.close()
                self._mic_writer.close()
                raise RuntimeError("Aucun peripherique loopback WASAPI disponible")

            self._loopback_rate = int(loopback_device["defaultSampleRate"])
            self._loopback_channels = loopback_device["maxInputChannels"]

            loopback_path = output_dir / "systeme.wav"
            self._loopback_writer = wave.open(str(loopback_path), "wb")
            self._loopback_writer.setnchannels(self._loopback_channels)
            self._loopback_writer.setsampwidth(2)
            self._loopback_writer.setframerate(self._loopback_rate)

            self._loopback_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._loopback_channels,
                rate=self._loopback_rate,
                input=True,
                input_device_index=loopback_device["index"],
                frames_per_buffer=self._settings.chunk_size,
                stream_callback=self._loopback_callback,
            )

            self._start_time = time.time()
            self._is_recording = True
            logger.info(
                "Enregistrement demarre - Micro: %s (%dHz, %dch) | Loopback: %s (%dHz, %dch)",
                mic_device["name"], self._mic_rate, self._mic_channels,
                loopback_device["name"], self._loopback_rate, self._loopback_channels,
            )

    def stop_recording(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Arrete l'enregistrement et retourne les chemins des fichiers WAV."""
        with self._lock:
            if not self._is_recording:
                return None, None

            self._is_recording = False
            mic_path = None
            loopback_path = None

            # Fermer le flux micro
            if self._mic_stream is not None:
                try:
                    self._mic_stream.stop_stream()
                    self._mic_stream.close()
                except Exception as e:
                    logger.warning("Erreur fermeture flux micro: %s", e)
                self._mic_stream = None

            if self._mic_writer is not None:
                try:
                    mic_path = Path(self._mic_writer._file.name)
                except Exception:
                    pass
                try:
                    self._mic_writer.close()
                except Exception as e:
                    logger.warning("Erreur fermeture WAV micro: %s", e)
                self._mic_writer = None

            # Fermer le flux loopback
            if self._loopback_stream is not None:
                try:
                    self._loopback_stream.stop_stream()
                    self._loopback_stream.close()
                except Exception as e:
                    logger.warning("Erreur fermeture flux loopback: %s", e)
                self._loopback_stream = None

            if self._loopback_writer is not None:
                try:
                    loopback_path = Path(self._loopback_writer._file.name)
                except Exception:
                    pass
                try:
                    self._loopback_writer.close()
                except Exception as e:
                    logger.warning("Erreur fermeture WAV loopback: %s", e)
                self._loopback_writer = None

            # Fermer PyAudio
            if self._pa is not None:
                try:
                    self._pa.terminate()
                except Exception:
                    pass
                self._pa = None

            duration = time.time() - self._start_time
            logger.info("Enregistrement arrete apres %.1f secondes", duration)
            self._mic_level = 0.0
            self._loopback_level = 0.0

            return mic_path, loopback_path

    def get_levels(self) -> Tuple[float, float]:
        """Retourne les niveaux audio actuels (mic, loopback) de 0.0 a 1.0."""
        return self._mic_level, self._loopback_level

    def get_elapsed_time(self) -> float:
        """Retourne le temps ecoule en secondes."""
        if self._is_recording:
            return time.time() - self._start_time
        return 0.0

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def mic_sample_rate(self) -> int:
        return self._mic_rate

    @property
    def loopback_sample_rate(self) -> int:
        return self._loopback_rate

    def _mic_callback(self, in_data, frame_count, time_info, status):
        """Callback PyAudio pour le microphone."""
        if status:
            logger.debug("Micro callback status: %s", status)
        if self._is_recording and self._mic_writer is not None:
            try:
                self._mic_writer.writeframes(in_data)
                self._mic_level = self._compute_rms_level(in_data)
            except Exception as e:
                logger.error("Erreur ecriture micro: %s", e)
        return (None, pyaudio.paContinue)

    def _loopback_callback(self, in_data, frame_count, time_info, status):
        """Callback PyAudio pour le loopback WASAPI."""
        if status:
            logger.debug("Loopback callback status: %s", status)
        if self._is_recording and self._loopback_writer is not None:
            try:
                self._loopback_writer.writeframes(in_data)
                self._loopback_level = self._compute_rms_level(in_data)
            except Exception as e:
                logger.error("Erreur ecriture loopback: %s", e)
        return (None, pyaudio.paContinue)

    @staticmethod
    def _compute_rms_level(audio_data: bytes) -> float:
        """Calcule le niveau RMS normalise (0.0 - 1.0) a partir de donnees PCM 16-bit."""
        try:
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            if len(samples) == 0:
                return 0.0
            rms = np.sqrt(np.mean(samples ** 2))
            # Normaliser sur la plage 16-bit (32768)
            level = min(rms / 32768.0 * 3.0, 1.0)  # x3 pour sensibilite
            return level
        except Exception:
            return 0.0

    def _get_mic_device(self) -> Optional[dict]:
        """Recupere le peripherique microphone configure ou par defaut."""
        if self._settings.mic_device_index is not None:
            try:
                return self._pa.get_device_info_by_index(self._settings.mic_device_index)
            except Exception:
                logger.warning("Peripherique micro %d introuvable, fallback sur defaut",
                               self._settings.mic_device_index)
        try:
            return self._pa.get_default_input_device_info()
        except Exception as e:
            logger.error("Aucun microphone disponible: %s", e)
            return None

    def _get_loopback_device(self) -> Optional[dict]:
        """Recupere le peripherique loopback configure ou par defaut."""
        if self._settings.loopback_device_index is not None:
            try:
                info = self._pa.get_device_info_by_index(self._settings.loopback_device_index)
                if info.get("isLoopbackDevice", False):
                    return info
            except Exception:
                logger.warning("Peripherique loopback %d introuvable, fallback sur defaut",
                               self._settings.loopback_device_index)
        try:
            return self._pa.get_default_wasapi_loopback()
        except Exception as e:
            logger.error("Aucun peripherique loopback WASAPI: %s", e)
            return None
