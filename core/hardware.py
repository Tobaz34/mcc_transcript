"""Detection materielle et selection automatique du modele Whisper.

Detecte GPU NVIDIA (CUDA), VRAM, RAM systeme et recommande
le meilleur modele Whisper en fonction du materiel.
"""

import logging
import os
import platform
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GpuInfo:
    name: str
    vram_mb: int
    cuda_available: bool
    cuda_version: str = ""


@dataclass
class HardwareInfo:
    ram_mb: int
    cpu_name: str
    cpu_cores: int
    gpu: Optional[GpuInfo]
    os_name: str

    @property
    def has_cuda(self) -> bool:
        return self.gpu is not None and self.gpu.cuda_available

    @property
    def vram_mb(self) -> int:
        return self.gpu.vram_mb if self.gpu else 0

    def summary(self) -> str:
        lines = [
            f"CPU : {self.cpu_name} ({self.cpu_cores} coeurs)",
            f"RAM : {self.ram_mb // 1024} Go",
        ]
        if self.gpu:
            lines.append(f"GPU : {self.gpu.name} ({self.gpu.vram_mb // 1024} Go VRAM)")
            lines.append(f"CUDA : {'Oui' if self.gpu.cuda_available else 'Non'} {self.gpu.cuda_version}")
        else:
            lines.append("GPU : Non detecte (mode CPU)")
        return "\n".join(lines)


@dataclass
class ModelRecommendation:
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    reason: str
    estimated_speed: str  # ex: "~2x temps reel" ou "~0.3x temps reel"


# Modeles Whisper et leurs besoins en memoire
# (nom, vram_gpu_fp16_mb, ram_cpu_int8_mb, qualite_fr, vitesse_relative)
WHISPER_MODELS = {
    "large-v3":  {"vram_fp16": 3000, "ram_int8": 3000, "quality": 5, "speed_gpu": 0.5, "speed_cpu": 4.0},
    "medium":    {"vram_fp16": 1500, "ram_int8": 1500, "quality": 4, "speed_gpu": 0.25, "speed_cpu": 2.0},
    "small":     {"vram_fp16": 500,  "ram_int8": 500,  "quality": 3, "speed_gpu": 0.1, "speed_cpu": 1.0},
    "base":      {"vram_fp16": 300,  "ram_int8": 300,  "quality": 2, "speed_gpu": 0.05, "speed_cpu": 0.5},
    "tiny":      {"vram_fp16": 150,  "ram_int8": 150,  "quality": 1, "speed_gpu": 0.02, "speed_cpu": 0.2},
}


def detect_hardware() -> HardwareInfo:
    """Detecte le materiel de la machine."""
    # RAM
    try:
        import psutil
        ram_mb = psutil.virtual_memory().total // (1024 * 1024)
    except ImportError:
        # Fallback sans psutil
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            c_ulong = ctypes.c_ulonglong
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", c_ulong),
                    ("ullAvailPhys", c_ulong),
                    ("ullTotalPageFile", c_ulong),
                    ("ullAvailPageFile", c_ulong),
                    ("ullTotalVirtual", c_ulong),
                    ("ullAvailVirtual", c_ulong),
                    ("ullAvailExtendedVirtual", c_ulong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            ram_mb = stat.ullTotalPhys // (1024 * 1024)
        except Exception:
            ram_mb = 8192  # Fallback 8 Go

    # CPU
    cpu_name = platform.processor() or "Inconnu"
    cpu_cores = os.cpu_count() or 4

    # GPU NVIDIA via torch
    gpu = _detect_nvidia_gpu()

    return HardwareInfo(
        ram_mb=ram_mb,
        cpu_name=cpu_name,
        cpu_cores=cpu_cores,
        gpu=gpu,
        os_name=f"{platform.system()} {platform.release()}",
    )


def _detect_nvidia_gpu() -> Optional[GpuInfo]:
    """Detecte le GPU NVIDIA via torch ou nvidia-smi."""
    # Methode 1 : via torch (le plus fiable)
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram_bytes = torch.cuda.get_device_properties(0).total_mem
            vram_mb = vram_bytes // (1024 * 1024)
            cuda_ver = torch.version.cuda or ""
            logger.info("GPU detecte via torch: %s (%d Mo VRAM, CUDA %s)", name, vram_mb, cuda_ver)
            return GpuInfo(name=name, vram_mb=vram_mb, cuda_available=True, cuda_version=cuda_ver)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Erreur detection torch CUDA: %s", e)

    # Methode 2 : via ctranslate2 (installe avec faster-whisper)
    try:
        import ctranslate2
        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            logger.info("CUDA detecte via ctranslate2 (VRAM inconnue)")
            return GpuInfo(name="GPU NVIDIA (details inconnus)", vram_mb=4096,
                          cuda_available=True)
    except Exception:
        pass

    # Methode 3 : via nvidia-smi (fallback)
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            name = parts[0]
            vram_mb = int(parts[1]) if len(parts) > 1 else 4096
            logger.info("GPU detecte via nvidia-smi: %s (%d Mo)", name, vram_mb)
            return GpuInfo(name=name, vram_mb=vram_mb, cuda_available=True)
    except Exception:
        pass

    logger.info("Aucun GPU NVIDIA detecte, mode CPU")
    return None


def recommend_model(hw: HardwareInfo) -> ModelRecommendation:
    """Recommande le meilleur modele Whisper selon le materiel detecte."""

    if hw.has_cuda:
        # Mode GPU : choisir selon la VRAM
        vram = hw.vram_mb

        if vram >= 8000:
            # 8 Go+ : large-v3 en float16, confortable
            return ModelRecommendation(
                whisper_model="large-v3",
                whisper_device="cuda",
                whisper_compute_type="float16",
                reason=f"GPU {hw.gpu.name} avec {vram // 1024} Go de VRAM — qualite maximale",
                estimated_speed="~2x temps reel (1h audio = ~30 min)",
            )
        elif vram >= 6000:
            # 6-8 Go : large-v3 en int8 (moins de VRAM ~3-4 Go)
            return ModelRecommendation(
                whisper_model="large-v3",
                whisper_device="cuda",
                whisper_compute_type="int8",
                reason=f"GPU {hw.gpu.name} avec {vram // 1024} Go — large-v3 en int8",
                estimated_speed="~2x temps reel (1h audio = ~30 min)",
            )
        elif vram >= 3000:
            # 3-6 Go (Quadro P600 4 Go, GTX 1050 Ti, etc.)
            # int8 pour tenir en VRAM, medium pour la securite
            return ModelRecommendation(
                whisper_model="medium",
                whisper_device="cuda",
                whisper_compute_type="int8",
                reason=f"GPU {hw.gpu.name} avec {vram // 1024} Go — medium en int8 (VRAM limitee)",
                estimated_speed="~3x temps reel (1h audio = ~20 min)",
            )
        elif vram >= 2000:
            # 2-3 Go : small en int8
            return ModelRecommendation(
                whisper_model="small",
                whisper_device="cuda",
                whisper_compute_type="int8",
                reason=f"GPU {hw.gpu.name} avec {vram // 1024} Go — small pour la VRAM limitee",
                estimated_speed="~6x temps reel (1h audio = ~10 min)",
            )
        else:
            # <2 Go : base sur GPU
            return ModelRecommendation(
                whisper_model="base",
                whisper_device="cuda",
                whisper_compute_type="int8",
                reason=f"GPU {hw.gpu.name} — VRAM tres limitee, modele base",
                estimated_speed="~10x temps reel (1h audio = ~6 min)",
            )
    else:
        # Mode CPU : choisir selon la RAM
        ram = hw.ram_mb

        if ram >= 16000:
            # 16 Go+ : medium en int8 (compromis qualite/vitesse)
            return ModelRecommendation(
                whisper_model="medium",
                whisper_device="cpu",
                whisper_compute_type="int8",
                reason=f"{ram // 1024} Go RAM, pas de GPU — medium en int8 (bon compromis)",
                estimated_speed="~0.5x temps reel (1h audio = ~2h)",
            )
        elif ram >= 8000:
            # 8-16 Go : small en int8
            return ModelRecommendation(
                whisper_model="small",
                whisper_device="cpu",
                whisper_compute_type="int8",
                reason=f"{ram // 1024} Go RAM, pas de GPU — small pour limiter la RAM",
                estimated_speed="~1x temps reel (1h audio = ~1h)",
            )
        else:
            # <8 Go : base
            return ModelRecommendation(
                whisper_model="base",
                whisper_device="cpu",
                whisper_compute_type="int8",
                reason=f"RAM limitee ({ram // 1024} Go), pas de GPU — modele base",
                estimated_speed="~2x temps reel (1h audio = ~30 min)",
            )


def format_recommendation(rec: ModelRecommendation) -> str:
    """Formate la recommandation pour l'affichage."""
    quality_map = {
        "large-v3": "Excellente",
        "medium": "Bonne",
        "small": "Correcte",
        "base": "Basique",
        "tiny": "Faible",
    }
    quality = quality_map.get(rec.whisper_model, "?")

    return (
        f"Modele recommande : {rec.whisper_model}\n"
        f"Acceleration : {rec.whisper_device} ({rec.whisper_compute_type})\n"
        f"Qualite transcription : {quality}\n"
        f"Vitesse estimee : {rec.estimated_speed}\n"
        f"Raison : {rec.reason}"
    )
