"""Enregistrement dual-stream : microphone + son systeme (WASAPI loopback)."""

import json
import logging
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

# Fichier marqueur pour la recuperation apres crash
RECORDING_MARKER = ".recording_in_progress.json"


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

        # Buffer pour transcription en direct (mic + loopback)
        self._live_chunks: list = []
        self._live_loopback_chunks: list = []
        self._live_lock = threading.Lock()

        # Detection de silence pour le decoupage intelligent
        self._silence_threshold = 0.01  # Niveau RMS sous lequel on considere silence
        self._silence_frames = 0  # Nombre de callbacks consecutifs en silence
        self._silence_frames_required = 15  # ~0.5 sec de silence (a 30 callbacks/sec)

        # Dossier de sortie (pour le marqueur de crash)
        self._output_dir: Optional[Path] = None

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
            self._output_dir = output_dir
            self._pa = pyaudio.PyAudio()

            # Vider le buffer live
            with self._live_lock:
                self._live_chunks.clear()
                self._live_loopback_chunks.clear()

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

            # Marqueur de crash recovery
            self._write_recording_marker(output_dir, mic_path, loopback_path)

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

            # Supprimer le marqueur de crash
            if self._output_dir:
                self._remove_recording_marker(self._output_dir)

            duration = time.time() - self._start_time
            logger.info("Enregistrement arrete apres %.1f secondes", duration)
            self._mic_level = 0.0
            self._loopback_level = 0.0

            return mic_path, loopback_path

    # --- Live transcription buffer ---

    def flush_live_audio(self) -> Optional[dict]:
        """Retourne l'audio micro + loopback accumule depuis le dernier flush.

        Returns {'mic': (pcm, rate, ch), 'loopback': (pcm, rate, ch)} or None.
        """
        with self._live_lock:
            has_mic = len(self._live_chunks) > 0
            has_lb = len(self._live_loopback_chunks) > 0
            if not has_mic and not has_lb:
                return None
            mic_data = b"".join(self._live_chunks) if has_mic else None
            lb_data = b"".join(self._live_loopback_chunks) if has_lb else None
            self._live_chunks.clear()
            self._live_loopback_chunks.clear()
        result = {}
        if mic_data:
            result['mic'] = (mic_data, self._mic_rate, self._mic_channels)
        if lb_data:
            result['loopback'] = (lb_data, self._loopback_rate, self._loopback_channels)
        return result if result else None

    # --- Niveaux et temps ---

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
    def is_in_silence(self) -> bool:
        """True si le micro ET le loopback sont en silence (~0.5s)."""
        return (self._silence_frames >= self._silence_frames_required
                and self._loopback_level < self._silence_threshold)

    @property
    def mic_sample_rate(self) -> int:
        return self._mic_rate

    @property
    def loopback_sample_rate(self) -> int:
        return self._loopback_rate

    # --- Callbacks ---

    def _mic_callback(self, in_data, frame_count, time_info, status):
        """Callback PyAudio pour le microphone."""
        if status:
            logger.debug("Micro callback status: %s", status)
        if self._is_recording and self._mic_writer is not None:
            try:
                self._mic_writer.writeframes(in_data)
                level = self._compute_rms_level(in_data)
                self._mic_level = level
                # Tracker le silence pour le decoupage intelligent
                if level < self._silence_threshold:
                    self._silence_frames += 1
                else:
                    self._silence_frames = 0
                # Buffer pour transcription en direct
                with self._live_lock:
                    self._live_chunks.append(in_data)
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
                # Buffer pour transcription en direct
                with self._live_lock:
                    self._live_loopback_chunks.append(in_data)
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
            level = min(rms / 32768.0 * 3.0, 1.0)
            return level
        except Exception:
            return 0.0

    # --- Crash recovery ---

    @staticmethod
    def _write_recording_marker(output_dir: Path, mic_path: Path, loopback_path: Path):
        """Ecrit un fichier marqueur pour la recuperation en cas de crash."""
        marker = output_dir / RECORDING_MARKER
        data = {
            "start_time": time.time(),
            "output_dir": str(output_dir),
            "mic_path": str(mic_path),
            "loopback_path": str(loopback_path),
        }
        try:
            with open(marker, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning("Impossible d'ecrire le marqueur de crash: %s", e)

    @staticmethod
    def _remove_recording_marker(output_dir: Path):
        """Supprime le fichier marqueur apres un arret propre."""
        marker = output_dir / RECORDING_MARKER
        try:
            if marker.exists():
                marker.unlink()
        except Exception:
            pass

    @staticmethod
    def fix_wav_header(wav_path: Path) -> bool:
        """Repare l'en-tete WAV d'un fichier non ferme proprement."""
        try:
            file_size = wav_path.stat().st_size
            if file_size < 44:
                return False
            with open(wav_path, "r+b") as f:
                f.seek(0)
                riff = f.read(4)
                if riff != b"RIFF":
                    return False
                data_size = file_size - 44
                # RIFF chunk size
                f.seek(4)
                f.write((data_size + 36).to_bytes(4, "little"))
                # data chunk size
                f.seek(40)
                f.write(data_size.to_bytes(4, "little"))
            logger.info("En-tete WAV repare: %s (%d octets)", wav_path.name, file_size)
            return True
        except Exception as e:
            logger.error("Echec reparation WAV %s: %s", wav_path, e)
            return False

    @staticmethod
    def find_crashed_sessions(output_base: Path) -> list:
        """Cherche des sessions d'enregistrement interrompues."""
        crashed = []
        if not output_base.exists():
            return crashed
        for session_dir in output_base.iterdir():
            if not session_dir.is_dir():
                continue
            marker = session_dir / RECORDING_MARKER
            if marker.exists():
                try:
                    with open(marker, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["session_dir"] = str(session_dir)
                    data["session_name"] = session_dir.name
                    crashed.append(data)
                except Exception:
                    crashed.append({"session_dir": str(session_dir),
                                    "session_name": session_dir.name})
        return crashed

    # --- Devices ---

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
