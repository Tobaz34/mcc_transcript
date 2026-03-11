"""Point d'entree de l'application MCC - TRANSCRIPT."""

import logging
import os
import sys
from pathlib import Path

# Ajouter le repertoire racine au PYTHONPATH
APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(APP_DIR))


def setup_logging():
    """Configure le logging de l'application."""
    log_dir = APP_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Demarrage de MCC - TRANSCRIPT")

    # Charger la configuration
    config_dir = APP_DIR / "config"
    from config.settings import AppSettings
    settings = AppSettings.load(config_dir)

    # Creer les dossiers necessaires
    output_dir = Path(settings.output_directory)
    if not output_dir.is_absolute():
        output_dir = APP_DIR / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    models_dir = Path(settings.models_directory)
    if not models_dir.is_absolute():
        models_dir = APP_DIR / models_dir
    models_dir.mkdir(parents=True, exist_ok=True)

    # Lancer l'application
    from gui.app import MeetingAssistantApp
    app = MeetingAssistantApp(settings, config_dir)
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
