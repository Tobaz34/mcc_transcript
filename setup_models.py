"""Script de telechargement des modeles pour utilisation hors-ligne.

Executez ce script une fois sur une machine avec acces internet :
    python setup_models.py

Detecte automatiquement votre materiel (GPU/RAM) et telecharge
le modele Whisper le plus adapte.
"""

import os
import sys
from pathlib import Path

# Ajouter le repertoire racine au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def detect_and_recommend():
    """Detecte le materiel et recommande un modele."""
    print("Detection du materiel...")
    try:
        from core.hardware import detect_hardware, recommend_model
        hw = detect_hardware()
        rec = recommend_model(hw)

        print(f"\n  {hw.summary()}")
        print(f"\n  Modele recommande : {rec.whisper_model}")
        print(f"  Acceleration : {rec.whisper_device} ({rec.whisper_compute_type})")
        print(f"  Vitesse estimee : {rec.estimated_speed}")
        print(f"  Raison : {rec.reason}")
        return rec.whisper_model
    except Exception as e:
        print(f"  Detection echouee ({e}), modele par defaut: medium")
        return "medium"


def download_whisper_model(model_size: str, models_dir: str = "./models"):
    """Telecharge le modele faster-whisper."""
    size_map = {
        "large-v3": "~3 Go",
        "medium": "~1.5 Go",
        "small": "~500 Mo",
        "base": "~150 Mo",
        "tiny": "~75 Mo",
    }
    size_str = size_map.get(model_size, "?")

    print(f"\nTelechargement du modele Whisper '{model_size}' ({size_str})...")
    print("Cela peut prendre plusieurs minutes.\n")

    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=models_dir,
        )
        del model
        print(f"\n  Modele Whisper '{model_size}' telecharge dans {models_dir}/")
        return True
    except ImportError:
        print("ERREUR: faster-whisper n'est pas installe.")
        print("Installez-le avec: pip install faster-whisper")
        return False
    except Exception as e:
        print(f"ERREUR lors du telechargement: {e}")
        return False


def check_ollama():
    """Verifie qu'Ollama est lance et que le modele est disponible."""
    print("\nVerification d'Ollama...")
    try:
        import ollama
        client = ollama.Client()
        models = client.list()
        model_names = [m.get("name", "").split(":")[0] for m in models.get("models", [])]

        if model_names:
            print(f"  Modeles disponibles: {', '.join(model_names)}")
        else:
            print("  Aucun modele Ollama installe.")

        if "mistral" not in model_names:
            print("\n  ATTENTION: Le modele 'mistral' n'est pas installe.")
            print("  Executez: ollama pull mistral")
            return False
        else:
            print("  Modele 'mistral' disponible.")
            return True
    except ImportError:
        print("ERREUR: le package 'ollama' n'est pas installe.")
        return False
    except Exception as e:
        print(f"ERREUR: Impossible de se connecter a Ollama: {e}")
        print("Assurez-vous qu'Ollama est lance (ollama serve).")
        return False


def main():
    print("=" * 60)
    print("  MCC - TRANSCRIPT - Configuration des modeles")
    print("=" * 60)
    print()

    models_dir = "./models"
    Path(models_dir).mkdir(parents=True, exist_ok=True)

    # 1. Detection materielle
    recommended_model = detect_and_recommend()

    # 2. Sauvegarder la config auto-detectee
    try:
        from config.settings import AppSettings
        config_dir = Path("./config")
        settings = AppSettings()
        settings.auto_configure_hardware()
        settings.save(config_dir)
        print(f"\n  Configuration sauvegardee (modele: {settings.whisper_model}, "
              f"device: {settings.whisper_device})")
    except Exception as e:
        print(f"  Avertissement: sauvegarde config echouee ({e})")

    # 3. Telecharger le modele Whisper recommande
    whisper_ok = download_whisper_model(recommended_model, models_dir)

    # 4. Ollama
    ollama_ok = check_ollama()

    # Resume
    print("\n" + "=" * 60)
    print("  RESUME")
    print("=" * 60)
    print(f"  Whisper {recommended_model:10s} : {'OK' if whisper_ok else 'ECHEC'}")
    print(f"  Ollama + Mistral    : {'OK' if ollama_ok else 'ECHEC'}")

    if not whisper_ok or not ollama_ok:
        print("\n  Certains elements ne sont pas prets. Voir les erreurs ci-dessus.")
        sys.exit(1)
    else:
        print("\n  Tout est pret ! Lancez l'application avec: python main.py")
        print("  Ou double-cliquez sur LANCER.bat")


if __name__ == "__main__":
    main()
