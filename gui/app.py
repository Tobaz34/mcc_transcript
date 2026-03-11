"""Fenetre principale de l'application."""

import logging
import os
import threading
import queue
from datetime import datetime
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from config.constants import (
    APP_NAME, APP_VERSION, DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT, LEVEL_UPDATE_INTERVAL_MS,
    TIMER_UPDATE_INTERVAL_MS,
)
from config.settings import AppSettings
from core.audio_devices import AudioDeviceManager
from core.audio_recorder import DualStreamRecorder
from core.pipeline import ProcessingPipeline, PipelineResult
from gui.frames.recording_frame import RecordingFrame
from gui.frames.transcript_frame import TranscriptFrame
from gui.frames.minutes_frame import MinutesFrame
from gui.frames.settings_frame import SettingsFrame
from gui.frames.status_bar import StatusBar
from gui.widgets.progress_dialog import ProgressDialog

logger = logging.getLogger(__name__)


class MeetingAssistantApp(ctk.CTk):
    """Application principale."""

    def __init__(self, settings: AppSettings, config_dir: Path):
        super().__init__()

        self._settings = settings
        self._config_dir = config_dir
        self._app_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Configurer le theme
        ctk.set_appearance_mode(settings.theme)
        ctk.set_default_color_theme("blue")

        # Fenetre
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry(f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}")
        self.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        # Core
        self._device_manager = AudioDeviceManager()
        self._recorder = DualStreamRecorder(settings, self._device_manager)
        self._pipeline: Optional[ProcessingPipeline] = None
        self._current_output_dir: Optional[Path] = None
        self._processing_thread: Optional[threading.Thread] = None
        self._progress_dialog: Optional[ProgressDialog] = None

        # Queue pour communication thread -> GUI
        self._msg_queue: queue.Queue = queue.Queue()

        # Construire l'interface
        self._build_ui()

        # Verification au demarrage
        self.after(500, self._check_prerequisites)

        # Demarrer le monitoring audio (VU-metres en permanence)
        self.after(1000, self._start_monitoring)

        # Boucle de traitement de la queue
        self._process_queue()

    def _build_ui(self):
        # Layout : sidebar + zone principale
        self._sidebar = ctk.CTkFrame(self, width=180, corner_radius=0)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # Logo / titre dans la sidebar
        ctk.CTkLabel(
            self._sidebar, text="MCC",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(20, 5))
        ctk.CTkLabel(
            self._sidebar, text="TRANSCRIPT",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="gray",
        ).pack(pady=(0, 20))

        # Boutons de navigation
        self._nav_buttons = {}
        nav_items = [
            ("record", "Enregistrement"),
            ("transcript", "Transcription"),
            ("minutes", "Compte Rendu"),
            ("settings", "Parametres"),
        ]
        for key, label in nav_items:
            btn = ctk.CTkButton(
                self._sidebar, text=label, width=160, height=38,
                font=ctk.CTkFont(size=13),
                fg_color="transparent", text_color="white",
                hover_color=("gray75", "gray30"),
                anchor="w",
                command=lambda k=key: self._show_frame(k),
            )
            btn.pack(pady=2, padx=10)
            self._nav_buttons[key] = btn

        # Zone principale
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(side="left", fill="both", expand=True)

        # Conteneur des frames (stack)
        self._frame_container = ctk.CTkFrame(main_container, fg_color="transparent")
        self._frame_container.pack(fill="both", expand=True)

        # Status bar
        self._status_bar = StatusBar(main_container)
        self._status_bar.pack(fill="x", side="bottom")

        # Creer les frames
        self._frames = {}
        self._frames["record"] = RecordingFrame(
            self._frame_container,
            on_start=self._on_start_recording,
            on_stop=self._on_stop_recording,
        )
        self._frames["transcript"] = TranscriptFrame(self._frame_container)
        self._frames["minutes"] = MinutesFrame(
            self._frame_container,
            on_regenerate=self._on_regenerate_minutes,
        )
        self._frames["settings"] = SettingsFrame(
            self._frame_container,
            settings=self._settings,
            device_manager=self._device_manager,
            on_save=self._on_settings_saved,
        )

        # Afficher la frame d'enregistrement par defaut
        self._current_frame = None
        self._show_frame("record")

    def _show_frame(self, key: str):
        """Affiche la frame selectionnee."""
        if self._current_frame == key:
            return

        # Cacher la frame actuelle
        for frame in self._frames.values():
            frame.pack_forget()

        # Afficher la nouvelle
        self._frames[key].pack(fill="both", expand=True)
        self._current_frame = key

        # Mettre a jour les boutons de navigation
        for nav_key, btn in self._nav_buttons.items():
            if nav_key == key:
                btn.configure(fg_color=("gray75", "gray30"))
            else:
                btn.configure(fg_color="transparent")

    def _check_prerequisites(self):
        """Verifie les prerequis au demarrage."""
        warnings = []

        # Microphone
        mic = self._device_manager.get_default_microphone()
        if mic is None:
            warnings.append("Aucun microphone detecte")
        else:
            self._status_bar.set_indicator(f"Micro: {mic.name[:30]}")

        # Loopback
        lb = self._device_manager.get_default_loopback()
        if lb is None:
            warnings.append("Aucun peripherique loopback WASAPI detecte")

        if warnings:
            self._status_bar.set_status(
                " | ".join(warnings), "#FF9800"
            )
        else:
            self._status_bar.set_status("Pret", "#4CAF50")

    # --- Monitoring audio ---

    def _start_monitoring(self):
        """Demarre le monitoring audio pour les VU-metres."""
        self._recorder.start_monitoring()
        self._update_monitoring_levels()

    def _update_monitoring_levels(self):
        """Met a jour les VU-metres en mode monitoring (avant enregistrement)."""
        if self._recorder.is_monitoring:
            mic_lvl, sys_lvl = self._recorder.get_levels()
            self._frames["record"].update_levels(mic_lvl, sys_lvl)
            self.after(LEVEL_UPDATE_INTERVAL_MS, self._update_monitoring_levels)

    # --- Enregistrement ---

    def _on_start_recording(self, session_name: str):
        """Demarre l'enregistrement."""
        if not session_name:
            session_name = "reunion"

        # Creer le dossier de session
        timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")
        # Nettoyer le nom
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_name)
        folder_name = f"{timestamp}_{safe_name}"

        output_base = Path(self._settings.output_directory)
        if not output_base.is_absolute():
            output_base = self._app_dir / output_base

        self._current_output_dir = output_base / folder_name

        try:
            self._recorder.start_recording(self._current_output_dir)
            self._frames["record"].set_recording_state(True)
            self._status_bar.set_status("Enregistrement en cours...", "#F44336")
            # Demarrer les mises a jour des niveaux et du timer
            self._update_levels()
            self._update_timer()
            logger.info("Enregistrement demarre dans %s", self._current_output_dir)
        except RuntimeError as e:
            self._frames["record"].set_status(str(e), "#F44336")
            self._status_bar.set_status(f"Erreur: {e}", "#F44336")
            logger.error("Erreur demarrage enregistrement: %s", e)

    def _on_stop_recording(self):
        """Arrete l'enregistrement et lance le pipeline."""
        mic_path, loopback_path = self._recorder.stop_recording()
        self._frames["record"].set_recording_state(False)
        self._frames["record"].set_status("Traitement en cours...", "#FF9800")

        # Relancer le monitoring pour les VU-metres
        self.after(500, self._start_monitoring)

        if mic_path and loopback_path:
            # Lancer le pipeline en arriere-plan
            self._run_pipeline(mic_path, loopback_path)
        else:
            self._frames["record"].set_status("Erreur: fichiers manquants", "#F44336")

    def _update_levels(self):
        """Met a jour les VU-metres toutes les 50ms."""
        if self._recorder.is_recording:
            mic_lvl, sys_lvl = self._recorder.get_levels()
            self._frames["record"].update_levels(mic_lvl, sys_lvl)
            self.after(LEVEL_UPDATE_INTERVAL_MS, self._update_levels)

    def _update_timer(self):
        """Met a jour le timer toutes les secondes."""
        if self._recorder.is_recording:
            elapsed = self._recorder.get_elapsed_time()
            self._frames["record"].update_timer(elapsed)
            self.after(TIMER_UPDATE_INTERVAL_MS, self._update_timer)

    # --- Pipeline ---

    def _run_pipeline(self, mic_path: Path, loopback_path: Path):
        """Lance le pipeline de traitement en arriere-plan."""
        self._pipeline = ProcessingPipeline(self._settings)

        # Ouvrir le dialogue de progression
        self._progress_dialog = ProgressDialog(self, title="Traitement de l'enregistrement")

        def on_status(msg: str, progress: float):
            self._msg_queue.put(("status", msg, progress))

        def on_token(token: str):
            self._msg_queue.put(("token", token))

        def pipeline_worker():
            try:
                result = self._pipeline.process(
                    mic_path, loopback_path, self._current_output_dir,
                    on_status=on_status,
                    on_token=on_token,
                )
                self._msg_queue.put(("done", result))
            except Exception as e:
                logger.error("Erreur pipeline: %s", e, exc_info=True)
                self._msg_queue.put(("error", str(e)))

        self._processing_thread = threading.Thread(target=pipeline_worker, daemon=True)
        self._processing_thread.start()

    def _process_queue(self):
        """Traite les messages de la queue (appele toutes les 100ms)."""
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == "status":
                    _, text, progress = msg
                    if self._progress_dialog:
                        self._progress_dialog.update_progress(text, progress)
                    self._status_bar.set_status(text)

                elif msg_type == "token":
                    _, token = msg
                    self._frames["minutes"].append_token(token)

                elif msg_type == "done":
                    _, result = msg
                    self._on_pipeline_done(result)

                elif msg_type == "error":
                    _, error_msg = msg
                    self._on_pipeline_error(error_msg)

        except queue.Empty:
            pass

        self.after(100, self._process_queue)

    def _on_pipeline_done(self, result: PipelineResult):
        """Appele quand le pipeline est termine."""
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

        # Charger les resultats dans les frames
        self._frames["transcript"].load_transcript(result.transcript)
        self._frames["minutes"].load_minutes(result.minutes_text)

        self._frames["record"].set_status(
            f"Termine en {result.processing_time:.0f}s | "
            f"Fichiers dans {self._current_output_dir}",
            "#4CAF50",
        )
        self._status_bar.set_status(
            f"Traitement termine ({result.processing_time:.0f}s)", "#4CAF50"
        )

        # Basculer sur l'onglet compte rendu
        self._show_frame("minutes")

    def _on_pipeline_error(self, error_msg: str):
        """Appele en cas d'erreur dans le pipeline."""
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

        self._frames["record"].set_status(f"Erreur: {error_msg}", "#F44336")
        self._status_bar.set_status(f"Erreur: {error_msg}", "#F44336")

    # --- Regeneration ---

    def _on_regenerate_minutes(self, custom_instructions: str):
        """Regenere le compte rendu avec des instructions supplementaires."""
        if not self._pipeline or not hasattr(self._pipeline, '_transcriber'):
            return

        self._frames["minutes"].clear()
        self._status_bar.set_status("Regeneration du compte rendu...", "#FF9800")

        # Relire la transcription
        transcript_json = self._current_output_dir / "transcription.json"
        if not transcript_json.exists():
            self._status_bar.set_status("Transcription introuvable", "#F44336")
            return

        import json
        from core.transcriber import TranscriptionResult, TranscriptSegment, Word

        with open(transcript_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        segments = []
        for seg_data in data.get("segments", []):
            words = [
                Word(w["start"], w["end"], w["word"], w["probability"])
                for w in seg_data.get("words", [])
            ]
            segments.append(TranscriptSegment(
                start=seg_data["start"],
                end=seg_data["end"],
                text=seg_data["text"],
                words=words,
                speaker=seg_data.get("speaker"),
            ))

        transcript = TranscriptionResult(
            language=data.get("language", "fr"),
            segments=segments,
            duration=data.get("duration_seconds", 0),
        )

        from core.summarizer import MeetingSummarizer

        def regen_worker():
            try:
                summarizer = MeetingSummarizer(
                    model=self._settings.ollama_model,
                    host=self._settings.ollama_host,
                )
                minutes = summarizer.generate_minutes(
                    transcript,
                    custom_instructions=custom_instructions,
                    on_token=lambda t: self._msg_queue.put(("token", t)),
                )
                # Sauvegarder
                md_path = self._current_output_dir / "compte_rendu.md"
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(minutes)
                self._msg_queue.put(("status", "Compte rendu regenere", 1.0))
            except Exception as e:
                self._msg_queue.put(("error", str(e)))

        threading.Thread(target=regen_worker, daemon=True).start()

    # --- Parametres ---

    def _on_settings_saved(self, settings: AppSettings):
        """Appele quand les parametres sont sauvegardes."""
        self._settings = settings
        settings.save(self._config_dir)
        ctk.set_appearance_mode(settings.theme)
        self._status_bar.set_status("Parametres sauvegardes", "#4CAF50")

    def on_closing(self):
        """Nettoyage a la fermeture."""
        if self._recorder.is_monitoring:
            self._recorder.stop_monitoring()
        if self._recorder.is_recording:
            self._recorder.stop_recording()
        self._device_manager.terminate()
        self.destroy()
