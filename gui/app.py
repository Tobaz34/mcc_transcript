"""Fenetre principale de l'application."""

import logging
import os
import tempfile
import threading
import queue
import wave
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
from core.transcriber import Transcriber
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

        # Transcripteur partage (live + pipeline)
        self._shared_transcriber: Optional[Transcriber] = None
        self._transcriber_loading = False

        # Transcription en direct
        self._live_transcripts = []
        self._live_chunk_count = 0
        self._live_transcribing = False
        self._live_total_offset = 0.0
        self._live_waiting_silence = False  # Attend un silence pour couper
        self._live_silence_wait_count = 0  # Compteur d'attente silence (max ~20 = 10s)
        self._live_chunk_summaries = []  # Resumes LLM partiels par morceau

        # Queue pour communication thread -> GUI
        self._msg_queue: queue.Queue = queue.Queue()

        # Construire l'interface
        self._build_ui()

        # Verification au demarrage + crash recovery + sessions
        self.after(500, self._check_prerequisites)
        self.after(600, self._check_crashed_sessions)
        self.after(700, self._refresh_sessions_list)

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
            settings=self._settings,
            device_manager=self._device_manager,
            on_start=self._on_start_recording,
            on_stop=self._on_stop_recording,
            on_device_changed=self._on_device_changed,
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

        for frame in self._frames.values():
            frame.pack_forget()

        self._frames[key].pack(fill="both", expand=True)
        self._current_frame = key

        for nav_key, btn in self._nav_buttons.items():
            if nav_key == key:
                btn.configure(fg_color=("gray75", "gray30"))
            else:
                btn.configure(fg_color="transparent")

    # --- Prerequis ---

    def _check_prerequisites(self):
        """Verifie les prerequis au demarrage et met a jour les pastilles."""
        rec = self._frames["record"]

        has_mic = len(self._device_manager.list_input_devices()) > 0
        has_lb = len(self._device_manager.list_wasapi_loopback_devices()) > 0
        rec.set_indicator("mic", has_mic)
        rec.set_indicator("loopback", has_lb)

        warnings = []
        if not has_mic:
            warnings.append("Pas de micro")
        if not has_lb:
            warnings.append("Pas de loopback")
        if warnings:
            self._status_bar.set_status(" | ".join(warnings), "#FF9800")

        def check_backends():
            ollama_ok = False
            try:
                from core.summarizer import MeetingSummarizer
                s = MeetingSummarizer(
                    model=self._settings.ollama_model,
                    host=self._settings.ollama_host)
                ollama_ok, _ = s.check_available()
            except Exception:
                pass

            whisper_ok = False
            try:
                models_dir = Path(self._settings.models_directory)
                if not models_dir.is_absolute():
                    models_dir = self._app_dir / models_dir
                model = self._settings.whisper_model
                if models_dir.exists():
                    for p in models_dir.iterdir():
                        if model in p.name and p.is_dir():
                            try:
                                if any(p.iterdir()):
                                    whisper_ok = True
                                    break
                            except Exception:
                                pass
            except Exception:
                pass

            self.after(0, lambda o=ollama_ok, w=whisper_ok:
                       self._on_backends_checked(o, w))

        threading.Thread(target=check_backends, daemon=True).start()

    def _on_backends_checked(self, ollama_ok, whisper_ok):
        rec = self._frames["record"]
        rec.set_indicator("ollama", ollama_ok)
        rec.set_indicator("whisper", whisper_ok)

        warnings = []
        if not ollama_ok:
            warnings.append("Ollama non disponible")
        if not whisper_ok:
            warnings.append("Modele Whisper manquant")
        has_mic = len(self._device_manager.list_input_devices()) > 0
        has_lb = len(self._device_manager.list_wasapi_loopback_devices()) > 0
        if not has_mic:
            warnings.append("Pas de micro")
        if not has_lb:
            warnings.append("Pas de loopback")

        if warnings:
            self._status_bar.set_status(" | ".join(warnings), "#FF9800")
        else:
            self._status_bar.set_status(
                "Pret - Tous les composants operationnels", "#4CAF50")

    # --- Crash recovery ---

    def _check_crashed_sessions(self):
        """Verifie s'il y a des sessions interrompues a recuperer."""
        output_base = Path(self._settings.output_directory)
        if not output_base.is_absolute():
            output_base = self._app_dir / output_base

        crashed = DualStreamRecorder.find_crashed_sessions(output_base)
        if not crashed:
            return

        for session in crashed:
            session_name = session.get("session_name", "Inconnue")
            session_dir = Path(session["session_dir"])

            # Reparer les WAV
            mic_wav = session_dir / "micro.wav"
            sys_wav = session_dir / "systeme.wav"
            recovered = False

            if mic_wav.exists() and mic_wav.stat().st_size > 44:
                DualStreamRecorder.fix_wav_header(mic_wav)
                recovered = True
            if sys_wav.exists() and sys_wav.stat().st_size > 44:
                DualStreamRecorder.fix_wav_header(sys_wav)
                recovered = True

            # Supprimer le marqueur
            marker = session_dir / ".recording_in_progress.json"
            if marker.exists():
                try:
                    marker.unlink()
                except Exception:
                    pass

            if recovered:
                self._status_bar.set_status(
                    f"Session recuperee : {session_name} - Allez dans Parametres pour traiter",
                    "#FF9800")
                self._current_output_dir = session_dir
                logger.info("Session interrompue recuperee : %s", session_dir)

    # --- Changement de peripherique ---

    def _on_device_changed(self, mic_index=None, lb_index=None):
        if mic_index is not None:
            self._settings.mic_device_index = mic_index
        if lb_index is not None:
            self._settings.loopback_device_index = lb_index
        self._settings.save(self._config_dir)

        if self._recorder.is_monitoring:
            self._recorder.stop_monitoring()
            self.after(300, self._start_monitoring)

    # --- Monitoring audio ---

    def _start_monitoring(self):
        self._recorder.start_monitoring()
        self._update_monitoring_levels()

    def _update_monitoring_levels(self):
        if self._recorder.is_monitoring:
            mic_lvl, sys_lvl = self._recorder.get_levels()
            self._frames["record"].update_levels(mic_lvl, sys_lvl)
            self.after(LEVEL_UPDATE_INTERVAL_MS, self._update_monitoring_levels)

    # --- Enregistrement ---

    def _on_start_recording(self, session_name: str):
        if not session_name:
            session_name = "reunion"

        timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")
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
            self._update_levels()
            self._update_timer()

            # Reset transcription en direct
            self._live_transcripts = []
            self._live_chunk_count = 0
            self._live_transcribing = False
            self._live_total_offset = 0.0
            self._live_waiting_silence = False
            self._live_silence_wait_count = 0
            self._live_chunk_summaries = []

            # Charger le modele Whisper en avance
            self._ensure_transcriber_loaded()

            # Programmer la premiere transcription en direct (intervalle en minutes)
            interval_ms = self._settings.live_chunk_interval_min * 60 * 1000
            self.after(interval_ms, self._do_live_transcription)

            logger.info("Enregistrement demarre dans %s", self._current_output_dir)
        except RuntimeError as e:
            self._frames["record"].set_status(str(e), "#F44336")
            self._status_bar.set_status(f"Erreur: {e}", "#F44336")
            logger.error("Erreur demarrage enregistrement: %s", e)

    def _on_stop_recording(self):
        mic_path, loopback_path = self._recorder.stop_recording()
        self._frames["record"].set_recording_state(False)
        self._frames["record"].set_status("Traitement en cours...", "#FF9800")

        self.after(500, self._start_monitoring)

        if mic_path and loopback_path:
            self._run_pipeline(mic_path, loopback_path)
        else:
            self._frames["record"].set_status("Erreur: fichiers manquants", "#F44336")

    def _update_levels(self):
        if self._recorder.is_recording:
            mic_lvl, sys_lvl = self._recorder.get_levels()
            self._frames["record"].update_levels(mic_lvl, sys_lvl)
            self.after(LEVEL_UPDATE_INTERVAL_MS, self._update_levels)

    def _update_timer(self):
        if self._recorder.is_recording:
            elapsed = self._recorder.get_elapsed_time()
            self._frames["record"].update_timer(elapsed)
            self.after(TIMER_UPDATE_INTERVAL_MS, self._update_timer)

    # --- Transcription en direct ---

    def _ensure_transcriber_loaded(self):
        """Charge le modele Whisper en arriere-plan si necessaire."""
        if self._shared_transcriber is not None or self._transcriber_loading:
            return
        self._transcriber_loading = True
        self._msg_queue.put(("live_status", "Chargement du modele Whisper..."))

        def worker():
            try:
                import time as _time
                t0 = _time.time()
                t = Transcriber(
                    model_size=self._settings.whisper_model,
                    device=self._settings.whisper_device,
                    compute_type=self._settings.whisper_compute_type,
                    models_dir=self._settings.models_directory,
                )
                t.load_model()
                elapsed = _time.time() - t0
                self._shared_transcriber = t
                device_info = t._actual_device or "inconnu"
                logger.info("Modele Whisper charge en %.1fs sur %s", elapsed, device_info)
                self.after(0, lambda: self._frames["record"].set_indicator("whisper", True))
                self._msg_queue.put(("live_status",
                    f"Whisper pret ({device_info}, {elapsed:.0f}s)"))
            except Exception as e:
                logger.error("Echec chargement Whisper: %s", e)
                self._msg_queue.put(("live_status", f"Erreur Whisper: {str(e)[:60]}"))
            finally:
                self._transcriber_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def _do_live_transcription(self):
        """Transcrit le dernier morceau audio accumule.

        Attend un silence avant de couper pour ne pas couper un mot/phrase.
        Si pas de silence apres ~10s, coupe quand meme.
        """
        if not self._recorder.is_recording:
            return
        if self._live_transcribing:
            # Transcription precedente pas finie, reessayer dans 10s
            self.after(10000, self._do_live_transcription)
            return
        if self._shared_transcriber is None or not self._shared_transcriber.is_loaded:
            # Modele pas encore charge, reessayer dans 5s
            self.after(5000, self._do_live_transcription)
            return

        # Attendre un silence avant de couper
        if not self._recorder.is_in_silence:
            self._live_silence_wait_count += 1
            if self._live_silence_wait_count < 20:  # Max ~10s d'attente (20 x 500ms)
                self.after(500, self._do_live_transcription)
                return
            # Pas de silence apres 10s, on coupe quand meme
            logger.info("Pas de silence detecte apres 10s, decoupage force")

        self._live_silence_wait_count = 0

        audio_data = self._recorder.flush_live_audio()
        if audio_data is None:
            interval_ms = self._settings.live_chunk_interval_min * 60 * 1000
            self.after(interval_ms, self._do_live_transcription)
            return

        self._live_chunk_count += 1
        chunk_num = self._live_chunk_count
        self._live_transcribing = True

        self._msg_queue.put(("chunk_add", chunk_num))

        def worker():
            tmp_path = None
            try:
                import numpy as np
                from core.audio_processor import resample_audio
                from config.constants import WHISPER_SAMPLE_RATE, ENERGY_RATIO_THRESHOLD

                mic_info = audio_data.get('mic')
                lb_info = audio_data.get('loopback')

                mic_16k = np.array([], dtype=np.float32)
                lb_16k = np.array([], dtype=np.float32)

                # Convertir micro en float32 mono 16kHz
                if mic_info:
                    mic_pcm, mic_rate, mic_ch = mic_info
                    mic_s = np.frombuffer(mic_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                    if mic_ch > 1:
                        mic_s = mic_s.reshape(-1, mic_ch).mean(axis=1)
                    mic_16k = resample_audio(mic_s, mic_rate, WHISPER_SAMPLE_RATE) if mic_rate != WHISPER_SAMPLE_RATE else mic_s

                # Convertir loopback en float32 mono 16kHz
                if lb_info:
                    lb_pcm, lb_rate, lb_ch = lb_info
                    lb_s = np.frombuffer(lb_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                    if lb_ch > 1:
                        lb_s = lb_s.reshape(-1, lb_ch).mean(axis=1)
                    lb_16k = resample_audio(lb_s, lb_rate, WHISPER_SAMPLE_RATE) if lb_rate != WHISPER_SAMPLE_RATE else lb_s

                # Mixer mic + loopback
                if len(mic_16k) > 0 and len(lb_16k) > 0:
                    max_len = max(len(mic_16k), len(lb_16k))
                    if len(mic_16k) < max_len:
                        mic_16k = np.pad(mic_16k, (0, max_len - len(mic_16k)))
                    if len(lb_16k) < max_len:
                        lb_16k = np.pad(lb_16k, (0, max_len - len(lb_16k)))
                    mixed = 0.5 * mic_16k + 0.5 * lb_16k
                elif len(lb_16k) > 0:
                    mixed = lb_16k
                elif len(mic_16k) > 0:
                    mixed = mic_16k
                else:
                    self._live_transcribing = False
                    return

                # Normaliser
                peak = np.max(np.abs(mixed))
                if peak > 0:
                    mixed = mixed / peak * 0.95

                # Ecrire le WAV mixe en 16kHz mono
                fd, tmp_name = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                tmp_path = Path(tmp_name)

                mixed_int16 = (np.clip(mixed, -1.0, 1.0) * 32767).astype(np.int16)
                wf = wave.open(str(tmp_path), "wb")
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(WHISPER_SAMPLE_RATE)
                wf.writeframes(mixed_int16.tobytes())
                wf.close()

                # 1. Transcription du mix
                self._msg_queue.put(("chunk_status", chunk_num, "transcription", ""))
                result = self._shared_transcriber.transcribe(
                    tmp_path, language=self._settings.language, use_vad=False)

                n_segs = len(result.segments)
                self._msg_queue.put(("chunk_status", chunk_num, "diarisation",
                                     f"{n_segs} segment(s)"))

                # 2. Diarisation par comparaison d'energie mic vs loopback
                for seg in result.segments:
                    s0 = int(seg.start * WHISPER_SAMPLE_RATE)
                    s1 = int(seg.end * WHISPER_SAMPLE_RATE)
                    mic_w = mic_16k[max(0, s0):min(len(mic_16k), s1)]
                    lb_w = lb_16k[max(0, s0):min(len(lb_16k), s1)]
                    mic_rms = float(np.sqrt(np.mean(mic_w**2))) if len(mic_w) > 0 else 0.0
                    lb_rms = float(np.sqrt(np.mean(lb_w**2))) if len(lb_w) > 0 else 0.0
                    if mic_rms > lb_rms * ENERGY_RATIO_THRESHOLD:
                        seg.speaker = "Vous"
                    elif lb_rms > mic_rms * ENERGY_RATIO_THRESHOLD:
                        seg.speaker = "Distant"
                    else:
                        seg.speaker = "Vous" if mic_rms >= lb_rms else "Distant"

                # Ajuster les timestamps avec l'offset global
                offset = self._live_total_offset
                for seg in result.segments:
                    seg.start += offset
                    seg.end += offset

                chunk_duration = len(mixed) / WHISPER_SAMPLE_RATE
                self._live_total_offset += chunk_duration
                self._live_transcripts.extend(result.segments)

                # 3. Formater le texte du morceau
                chunk_transcript_text = "\n".join(
                    f"[{int(s.start // 60):02d}:{int(s.start % 60):02d}] "
                    f"{s.speaker or 'Inconnu'} : {s.text}"
                    for s in result.segments
                )

                # Apercu transcription (avec locuteur)
                recent = self._live_transcripts[-8:]
                preview = "\n".join(
                    f"[{int(s.start // 60):02d}:{int(s.start % 60):02d}] "
                    f"{s.speaker or '?'} : {s.text}"
                    for s in recent
                )
                self._msg_queue.put(("live_transcript", preview, chunk_num))

                # 4. Resume LLM du morceau (si Ollama disponible)
                if result.segments and chunk_transcript_text.strip():
                    self._msg_queue.put(("chunk_status", chunk_num, "resume",
                                         f"{n_segs} segment(s)"))
                    try:
                        from core.summarizer import (
                            MeetingSummarizer, SYSTEM_PROMPT,
                            CHUNK_SUMMARY_TEMPLATE,
                        )
                        summarizer = MeetingSummarizer(
                            model=self._settings.ollama_model,
                            host=self._settings.ollama_host,
                        )
                        ok, _ = summarizer.check_available()
                        if ok:
                            start_min = int(result.segments[0].start / 60)
                            end_min = int(result.segments[-1].end / 60)
                            prompt = CHUNK_SUMMARY_TEMPLATE.format(
                                part_num=chunk_num,
                                total_parts="?",
                                start_min=start_min,
                                end_min=end_min,
                                chunk_text=chunk_transcript_text,
                            )
                            summary = summarizer._get_response(
                                summarizer._get_client(),
                                [{"role": "system", "content": SYSTEM_PROMPT},
                                 {"role": "user", "content": prompt}],
                            )
                            self._live_chunk_summaries.append(
                                f"### Minutes {start_min}-{end_min}\n{summary}"
                            )
                            logger.info("Resume LLM morceau %d OK (%d car.)",
                                        chunk_num, len(summary))
                            self._msg_queue.put(("chunk_status", chunk_num,
                                "termine", f"{n_segs} seg. + resume"))
                        else:
                            self._msg_queue.put(("chunk_status", chunk_num,
                                "termine", f"{n_segs} seg. (Ollama indispo.)"))
                    except Exception as e:
                        logger.warning("Resume LLM morceau %d echoue: %s",
                                       chunk_num, e)
                        self._msg_queue.put(("chunk_status", chunk_num,
                            "termine", f"{n_segs} seg. (resume echoue)"))
                else:
                    self._msg_queue.put(("chunk_status", chunk_num,
                        "termine", "0 segment"))

            except Exception as e:
                logger.error("Erreur transcription en direct morceau %d: %s", chunk_num, e)
                self._msg_queue.put(("chunk_status", chunk_num, "erreur", str(e)[:50]))
            finally:
                if tmp_path and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                self._live_transcribing = False

        threading.Thread(target=worker, daemon=True).start()

        # Programmer le prochain morceau
        interval_ms = self._settings.live_chunk_interval_min * 60 * 1000
        self.after(interval_ms, self._do_live_transcription)

    # --- Pipeline ---

    def _build_live_transcript_result(self) -> Optional['TranscriptionResult']:
        """Construit un TranscriptionResult a partir des segments live."""
        if not self._live_transcripts:
            return None
        from core.transcriber import TranscriptionResult
        return TranscriptionResult(
            language=self._settings.language,
            segments=list(self._live_transcripts),
            duration=self._live_total_offset,
        )

    def _run_pipeline(self, mic_path: Path, loopback_path: Path):
        # Reutiliser le transcripteur deja charge
        self._pipeline = ProcessingPipeline(
            self._settings, transcriber=self._shared_transcriber)

        # Utiliser les transcripts live si disponibles
        live_result = self._build_live_transcript_result()
        chunk_summaries = list(self._live_chunk_summaries) if self._live_chunk_summaries else None

        if live_result:
            logger.info("Pipeline rapide: %d segments live, %d resumes partiels",
                        len(live_result.segments),
                        len(chunk_summaries) if chunk_summaries else 0)

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
                    existing_transcript=live_result,
                    existing_chunk_summaries=chunk_summaries,
                )
                self._msg_queue.put(("done", result))
            except Exception as e:
                logger.error("Erreur pipeline: %s", e, exc_info=True)
                self._msg_queue.put(("error", str(e)))

        self._processing_thread = threading.Thread(target=pipeline_worker, daemon=True)
        self._processing_thread.start()

    def _process_queue(self):
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

                elif msg_type == "live_transcript":
                    _, preview_text, chunk_num = msg
                    self._frames["record"].update_live_transcript(
                        preview_text, chunk_num)

                elif msg_type == "live_status":
                    _, text = msg
                    self._frames["record"]._live_label.configure(
                        text=text, text_color="#FF9800")

                elif msg_type == "chunk_add":
                    _, chunk_num = msg
                    self._frames["record"].add_live_chunk(chunk_num)

                elif msg_type == "chunk_status":
                    _, chunk_num, status, detail = msg
                    self._frames["record"].update_live_chunk_status(
                        chunk_num, status, detail)

        except queue.Empty:
            pass

        self.after(100, self._process_queue)

    def _on_pipeline_done(self, result: PipelineResult):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

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

        # Copier le dossier sur le Bureau
        self._copy_session_to_desktop(result)

        self._show_frame("minutes")
        self._refresh_sessions_list()

    def _on_pipeline_error(self, error_msg: str):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

        self._frames["record"].set_status(f"Erreur: {error_msg}", "#F44336")
        self._status_bar.set_status(f"Erreur: {error_msg}", "#F44336")

    # --- Regeneration ---

    def _on_regenerate_minutes(self, custom_instructions: str):
        if not self._pipeline or not hasattr(self._pipeline, '_transcriber'):
            return

        self._frames["minutes"].clear()
        self._status_bar.set_status("Regeneration du compte rendu...", "#FF9800")

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
                md_path = self._current_output_dir / "compte_rendu.md"
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(minutes)
                self._msg_queue.put(("status", "Compte rendu regenere", 1.0))
            except Exception as e:
                self._msg_queue.put(("error", str(e)))

        threading.Thread(target=regen_worker, daemon=True).start()

    # --- Parametres ---

    def _on_settings_saved(self, settings: AppSettings):
        self._settings = settings
        settings.save(self._config_dir)
        ctk.set_appearance_mode(settings.theme)
        self._status_bar.set_status("Parametres sauvegardes", "#4CAF50")

        rec = self._frames["record"]
        rec._settings = settings
        rec.populate_devices()

        self.after(500, self._check_prerequisites)

    def _copy_session_to_desktop(self, result: PipelineResult):
        """Copie le dossier de session sur le Bureau (si active)."""
        if not self._settings.desktop_copy_enabled:
            return
        if not self._current_output_dir:
            return

        try:
            import shutil
            import subprocess

            desktop = None

            # 1. Chemin personnalise dans les parametres
            if self._settings.desktop_copy_path:
                p = Path(self._settings.desktop_copy_path)
                if p.exists():
                    desktop = p

            # 2. Methode fiable : demander a Windows le vrai chemin du Bureau
            # (gere OneDrive, profils rediriges, etc.)
            if desktop is None:
                try:
                    r = subprocess.run(
                        ["powershell", "-Command",
                         "[Environment]::GetFolderPath('Desktop')"],
                        capture_output=True, text=True, timeout=5)
                    p = Path(r.stdout.strip())
                    if p.exists():
                        desktop = p
                except Exception:
                    pass

            # 3. Fallback classique
            if desktop is None:
                for name in ("Desktop", "Bureau"):
                    p = Path.home() / name
                    if p.exists():
                        desktop = p
                        break

            if desktop is not None and desktop.exists():
                dest = desktop / self._current_output_dir.name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(self._current_output_dir, dest)
                logger.info("Session copiee : %s", dest)
                self._status_bar.set_status(
                    f"Termine - Copie dans : {dest}", "#4CAF50")
            else:
                logger.warning("Dossier de copie introuvable")
        except Exception as e:
            logger.warning("Impossible de copier la session: %s", e)

    def _refresh_sessions_list(self):
        """Rafraichit la liste des sessions sur l'ecran d'enregistrement."""
        output_base = Path(self._settings.output_directory)
        if not output_base.is_absolute():
            output_base = self._app_dir / output_base
        self._frames["record"]._load_sessions(output_base)

    def on_closing(self):
        if self._recorder.is_monitoring:
            self._recorder.stop_monitoring()
        if self._recorder.is_recording:
            self._recorder.stop_recording()
        self._device_manager.terminate()
        self.destroy()
