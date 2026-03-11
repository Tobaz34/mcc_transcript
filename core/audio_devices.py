"""Enumeration et gestion des peripheriques audio via PyAudioWPatch."""

import logging
from dataclasses import dataclass
from typing import List, Optional

import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    is_loopback: bool = False


class AudioDeviceManager:
    """Enumere et valide les peripheriques audio."""

    def __init__(self):
        self._pa = pyaudio.PyAudio()

    def list_input_devices(self) -> List[DeviceInfo]:
        """Liste les peripheriques d'entree (microphones)."""
        devices = []
        for i in range(self._pa.get_device_count()):
            try:
                info = self._pa.get_device_info_by_index(i)
                if info["maxInputChannels"] > 0 and not info.get("isLoopbackDevice", False):
                    devices.append(DeviceInfo(
                        index=i,
                        name=info["name"],
                        max_input_channels=info["maxInputChannels"],
                        max_output_channels=info["maxOutputChannels"],
                        default_sample_rate=info["defaultSampleRate"],
                        is_loopback=False,
                    ))
            except Exception:
                continue
        return devices

    def list_wasapi_loopback_devices(self) -> List[DeviceInfo]:
        """Liste les peripheriques WASAPI loopback (son systeme)."""
        devices = []
        for i in range(self._pa.get_device_count()):
            try:
                info = self._pa.get_device_info_by_index(i)
                if info.get("isLoopbackDevice", False):
                    devices.append(DeviceInfo(
                        index=i,
                        name=info["name"],
                        max_input_channels=info["maxInputChannels"],
                        max_output_channels=info["maxOutputChannels"],
                        default_sample_rate=info["defaultSampleRate"],
                        is_loopback=True,
                    ))
            except Exception:
                continue
        return devices

    def get_default_microphone(self) -> Optional[DeviceInfo]:
        """Retourne le microphone par defaut."""
        try:
            info = self._pa.get_default_input_device_info()
            return DeviceInfo(
                index=info["index"],
                name=info["name"],
                max_input_channels=info["maxInputChannels"],
                max_output_channels=info["maxOutputChannels"],
                default_sample_rate=info["defaultSampleRate"],
                is_loopback=False,
            )
        except Exception as e:
            logger.warning("Aucun microphone par defaut: %s", e)
            return None

    def get_default_loopback(self) -> Optional[DeviceInfo]:
        """Retourne le peripherique WASAPI loopback par defaut."""
        try:
            info = self._pa.get_default_wasapi_loopback()
            return DeviceInfo(
                index=info["index"],
                name=info["name"],
                max_input_channels=info["maxInputChannels"],
                max_output_channels=info["maxOutputChannels"],
                default_sample_rate=info["defaultSampleRate"],
                is_loopback=True,
            )
        except Exception as e:
            logger.warning("Aucun peripherique loopback par defaut: %s", e)
            return None

    def get_device_info(self, device_index: int) -> Optional[DeviceInfo]:
        """Retourne les informations d'un peripherique par son index."""
        try:
            info = self._pa.get_device_info_by_index(device_index)
            return DeviceInfo(
                index=info["index"],
                name=info["name"],
                max_input_channels=info["maxInputChannels"],
                max_output_channels=info["maxOutputChannels"],
                default_sample_rate=info["defaultSampleRate"],
                is_loopback=info.get("isLoopbackDevice", False),
            )
        except Exception as e:
            logger.error("Peripherique %d introuvable: %s", device_index, e)
            return None

    def validate_device(self, device_index: int, is_loopback: bool = False) -> bool:
        """Teste si un peripherique peut etre ouvert."""
        try:
            info = self._pa.get_device_info_by_index(device_index)
            if is_loopback and not info.get("isLoopbackDevice", False):
                return False
            if not is_loopback and info["maxInputChannels"] <= 0:
                return False
            return True
        except Exception:
            return False

    def terminate(self):
        """Libere les ressources PyAudio."""
        try:
            self._pa.terminate()
        except Exception:
            pass
