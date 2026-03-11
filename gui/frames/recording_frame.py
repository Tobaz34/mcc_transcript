"""Frame d'enregistrement avec controles, VU-metres et indicateurs d'etat."""

import threading
import customtkinter as ctk
from gui.widgets.audio_level_meter import AudioLevelMeter


class RecordingFrame(ctk.CTkFrame):
    """Interface d'enregistrement : pastilles d'etat, selection peripheriques, VU-metres."""

    def __init__(self, parent, settings=None, device_manager=None,
                 on_start=None, on_stop=None, on_device_changed=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._settings = settings
        self._device_manager = device_manager
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_device_changed = on_device_changed
        self._is_recording = False
        self._ignore_combo_events = False
        self._mic_devices = []
        self._lb_devices = []

        self._build_ui()
        if device_manager:
            self.populate_devices()

    def _build_ui(self):
        # Titre
        ctk.CTkLabel(self, text="Enregistrement",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(15, 8))

        # === PASTILLES D'ETAT ===
        ind_frame = ctk.CTkFrame(self, fg_color=("gray90", "#1e1e1e"), corner_radius=8)
        ind_frame.pack(fill="x", padx=30, pady=(0, 10))

        self._indicators = {}
        for key, label in [("mic", "Micro"), ("loopback", "Son systeme"),
                           ("ollama", "Ollama"), ("whisper", "Whisper")]:
            f = ctk.CTkFrame(ind_frame, fg_color="transparent")
            f.pack(side="left", padx=15, pady=8)
            dot = ctk.CTkLabel(f, text="\u25CF", font=ctk.CTkFont(size=18),
                               text_color="gray")
            dot.pack(side="left", padx=(0, 4))
            ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=12)).pack(side="left")
            self._indicators[key] = dot

        # === PERIPHERIQUES ===
        dev_frame = ctk.CTkFrame(self, fg_color="transparent")
        dev_frame.pack(fill="x", padx=30, pady=5)

        mic_row = ctk.CTkFrame(dev_frame, fg_color="transparent")
        mic_row.pack(fill="x", pady=2)
        ctk.CTkLabel(mic_row, text="Microphone :", width=110, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self._mic_combo = ctk.CTkComboBox(mic_row, values=["Chargement..."],
                                          width=420, command=self._on_mic_changed)
        self._mic_combo.pack(side="left", padx=5)

        lb_row = ctk.CTkFrame(dev_frame, fg_color="transparent")
        lb_row.pack(fill="x", pady=2)
        ctk.CTkLabel(lb_row, text="Son systeme :", width=110, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self._lb_combo = ctk.CTkComboBox(lb_row, values=["Chargement..."],
                                         width=420, command=self._on_lb_changed)
        self._lb_combo.pack(side="left", padx=5)

        scan_row = ctk.CTkFrame(dev_frame, fg_color="transparent")
        scan_row.pack(fill="x", pady=3)
        self._scan_btn = ctk.CTkButton(
            scan_row, text="Scanner les peripheriques", width=220,
            font=ctk.CTkFont(size=11), command=self._scan_devices)
        self._scan_btn.pack(side="left")
        self._scan_label = ctk.CTkLabel(scan_row, text="",
                                        font=ctk.CTkFont(size=10), text_color="gray")
        self._scan_label.pack(side="left", padx=10)

        # === SESSION ===
        session_frame = ctk.CTkFrame(self, fg_color="transparent")
        session_frame.pack(fill="x", padx=30, pady=5)
        ctk.CTkLabel(session_frame, text="Session :",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        self._session_name = ctk.CTkEntry(session_frame, width=300,
                                          placeholder_text="reunion_projet")
        self._session_name.pack(side="left", padx=10)

        # === BOUTONS ===
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=12)

        self._start_btn = ctk.CTkButton(
            btn_frame, text="ENREGISTRER", width=200, height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#4CAF50", hover_color="#388E3C",
            command=self._on_start_click)
        self._start_btn.pack(side="left", padx=10)

        self._stop_btn = ctk.CTkButton(
            btn_frame, text="ARRETER", width=200, height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#F44336", hover_color="#D32F2F",
            command=self._on_stop_click, state="disabled")
        self._stop_btn.pack(side="left", padx=10)

        # === TIMER ===
        self._timer_label = ctk.CTkLabel(
            self, text="00:00:00",
            font=ctk.CTkFont(family="Consolas", size=36, weight="bold"))
        self._timer_label.pack(pady=6)

        # === VU-METRES ===
        meter_frame = ctk.CTkFrame(self, fg_color="transparent")
        meter_frame.pack(fill="x", padx=30, pady=5)

        m_row = ctk.CTkFrame(meter_frame, fg_color="transparent")
        m_row.pack(fill="x", pady=3)
        ctk.CTkLabel(m_row, text="Micro    :", width=80, anchor="w",
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self._mic_meter = AudioLevelMeter(m_row, width=500, height=22)
        self._mic_meter.pack(side="left", padx=10)

        s_row = ctk.CTkFrame(meter_frame, fg_color="transparent")
        s_row.pack(fill="x", pady=3)
        ctk.CTkLabel(s_row, text="Systeme :", width=80, anchor="w",
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self._sys_meter = AudioLevelMeter(s_row, width=500, height=22)
        self._sys_meter.pack(side="left", padx=10)

        # === TRANSCRIPTION EN DIRECT ===
        live_frame = ctk.CTkFrame(self, fg_color="transparent")
        live_frame.pack(fill="x", padx=30, pady=(5, 0))

        self._live_label = ctk.CTkLabel(
            live_frame, text="", font=ctk.CTkFont(size=11),
            text_color="gray", anchor="w")
        self._live_label.pack(fill="x")

        # Liste des morceaux avec leur etat
        self._chunks_frame = ctk.CTkScrollableFrame(
            live_frame, height=90, fg_color=("gray95", "#1a1a1a"))
        self._chunks_frame.pack(fill="x", pady=2)
        self._chunk_rows = {}  # chunk_num -> (row, dot, status_label, detail_label)

        # Apercu des derniers segments transcrits
        self._live_text = ctk.CTkTextbox(
            live_frame, height=55,
            font=ctk.CTkFont(family="Consolas", size=10),
            state="disabled", wrap="word")
        self._live_text.pack(fill="x", pady=2)

        # Cache par defaut, visible pendant l'enregistrement
        live_frame.pack_forget()
        self._live_frame = live_frame

        # === STATUS ===
        self._status_label = ctk.CTkLabel(
            self, text="Pret a enregistrer",
            font=ctk.CTkFont(size=12), text_color="gray")
        self._status_label.pack(pady=6)

        # === LISTE DES SESSIONS ===
        sessions_header = ctk.CTkFrame(self, fg_color="transparent")
        sessions_header.pack(fill="x", padx=30, pady=(8, 0))
        ctk.CTkLabel(sessions_header, text="Sessions",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        self._refresh_sessions_btn = ctk.CTkButton(
            sessions_header, text="Rafraichir", width=80,
            font=ctk.CTkFont(size=11), height=24,
            command=lambda: self._load_sessions())
        self._refresh_sessions_btn.pack(side="right")

        self._sessions_frame = ctk.CTkScrollableFrame(self, height=120)
        self._sessions_frame.pack(fill="both", expand=True, padx=30, pady=(4, 10))

        # Entete du tableau
        header = ctk.CTkFrame(self._sessions_frame, fg_color=("gray80", "gray25"))
        header.pack(fill="x", pady=(0, 2))
        for col, w in [("Session", 200), ("Duree", 80), ("Statut", 130),
                        ("Segments", 70), ("CR", 60)]:
            ctk.CTkLabel(header, text=col, width=w, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=4)

    # --- Peripheriques ---

    def populate_devices(self):
        """Peuple les listes de peripheriques."""
        if not self._device_manager:
            return

        self._ignore_combo_events = True
        try:
            self._mic_devices = self._device_manager.list_input_devices()
            mic_names = [f"{d.name} (#{d.index})" for d in self._mic_devices]
            if not mic_names:
                mic_names = ["Aucun microphone detecte"]
            self._mic_combo.configure(values=mic_names)

            selected_mic = None
            if self._settings and self._settings.mic_device_index is not None:
                for i, d in enumerate(self._mic_devices):
                    if d.index == self._settings.mic_device_index:
                        selected_mic = mic_names[i]
                        break
            if selected_mic:
                self._mic_combo.set(selected_mic)
            elif mic_names and mic_names[0] != "Aucun microphone detecte":
                self._mic_combo.set(mic_names[0])

            self._lb_devices = self._device_manager.list_wasapi_loopback_devices()
            lb_names = [f"{d.name} (#{d.index})" for d in self._lb_devices]
            if not lb_names:
                lb_names = ["Aucun peripherique loopback detecte"]
            self._lb_combo.configure(values=lb_names)

            selected_lb = None
            if self._settings and self._settings.loopback_device_index is not None:
                for i, d in enumerate(self._lb_devices):
                    if d.index == self._settings.loopback_device_index:
                        selected_lb = lb_names[i]
                        break
            if selected_lb:
                self._lb_combo.set(selected_lb)
            elif lb_names and lb_names[0] != "Aucun peripherique loopback detecte":
                self._lb_combo.set(lb_names[0])
        finally:
            self._ignore_combo_events = False

    def _extract_device_index(self, text):
        """Extrait l'index du peripherique depuis le texte du combo."""
        if "(#" in text:
            try:
                return int(text.split("(#")[-1].rstrip(")"))
            except (ValueError, IndexError):
                pass
        return None

    def _on_mic_changed(self, value):
        if self._is_recording or self._ignore_combo_events:
            return
        idx = self._extract_device_index(value)
        if idx is not None and self._on_device_changed:
            self._on_device_changed(mic_index=idx)

    def _on_lb_changed(self, value):
        if self._is_recording or self._ignore_combo_events:
            return
        idx = self._extract_device_index(value)
        if idx is not None and self._on_device_changed:
            self._on_device_changed(lb_index=idx)

    def _scan_devices(self):
        """Scanne les peripheriques et identifie ceux avec du signal actif."""
        if self._is_recording:
            return
        self._scan_btn.configure(state="disabled", text="Scan en cours...")
        self._scan_label.configure(text="")

        mic_devs = list(self._mic_devices)
        lb_devs = list(self._lb_devices)

        def worker():
            import numpy as np
            import pyaudiowpatch as pyaudio

            pa = pyaudio.PyAudio()
            active_indices = set()
            all_devs = mic_devs + lb_devs
            total = len(all_devs)

            for idx_i, device in enumerate(all_devs):
                self.after(0, lambda t=idx_i + 1, n=total:
                           self._scan_label.configure(text=f"Test {t}/{n}..."))
                try:
                    info = pa.get_device_info_by_index(device.index)
                    ch = max(min(info["maxInputChannels"], 2), 1)
                    rate = int(info["defaultSampleRate"])
                    stream = pa.open(
                        format=pyaudio.paInt16, channels=ch, rate=rate,
                        input=True, input_device_index=device.index,
                        frames_per_buffer=1024)
                    frames = b""
                    n_reads = max(int(rate / 1024 * 0.3), 3)
                    for _ in range(n_reads):
                        frames += stream.read(1024, exception_on_overflow=False)
                    stream.stop_stream()
                    stream.close()

                    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                    if len(samples) > 0:
                        rms = np.sqrt(np.mean(samples ** 2)) / 32768.0
                        if rms > 0.003:
                            active_indices.add(device.index)
                except Exception:
                    pass

            pa.terminate()
            self.after(0, lambda ai=active_indices: self._on_scan_done(ai))

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_done(self, active_indices):
        """Met a jour les combos avec les indicateurs d'activite."""
        current_mic = self._extract_device_index(self._mic_combo.get())
        current_lb = self._extract_device_index(self._lb_combo.get())

        self._ignore_combo_events = True
        try:
            mic_names = []
            for d in self._mic_devices:
                prefix = "\u25B6 " if d.index in active_indices else "  "
                mic_names.append(f"{prefix}{d.name} (#{d.index})")
            if not mic_names:
                mic_names = ["Aucun microphone detecte"]
            self._mic_combo.configure(values=mic_names)

            lb_names = []
            for d in self._lb_devices:
                prefix = "\u25B6 " if d.index in active_indices else "  "
                lb_names.append(f"{prefix}{d.name} (#{d.index})")
            if not lb_names:
                lb_names = ["Aucun peripherique loopback detecte"]
            self._lb_combo.configure(values=lb_names)

            for i, d in enumerate(self._mic_devices):
                if d.index == current_mic:
                    self._mic_combo.set(mic_names[i])
                    break
            for i, d in enumerate(self._lb_devices):
                if d.index == current_lb:
                    self._lb_combo.set(lb_names[i])
                    break
        finally:
            self._ignore_combo_events = False

        n_active = len(active_indices)
        self._scan_label.configure(
            text=f"Scan termine - {n_active} peripherique(s) actif(s)",
            text_color="#4CAF50" if n_active > 0 else "gray")
        self._scan_btn.configure(state="normal", text="Scanner les peripheriques")

    # --- Indicateurs ---

    def set_indicator(self, key, ok):
        """Met a jour une pastille d'etat. True=vert, False=rouge."""
        if key in self._indicators:
            color = "#4CAF50" if ok else "#F44336"
            self._indicators[key].configure(text_color=color)

    # --- Controles ---

    def _on_start_click(self):
        if self._on_start:
            session_name = self._session_name.get().strip()
            self._on_start(session_name)

    def _on_stop_click(self):
        if self._on_stop:
            self._on_stop()

    def set_recording_state(self, recording):
        """Met a jour l'interface selon l'etat d'enregistrement."""
        self._is_recording = recording
        if recording:
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._session_name.configure(state="disabled")
            self._mic_combo.configure(state="disabled")
            self._lb_combo.configure(state="disabled")
            self._scan_btn.configure(state="disabled")
            self._status_label.configure(text="Enregistrement en cours...",
                                         text_color="#F44336")
            # Afficher la zone de transcription en direct
            self._live_frame.pack(fill="x", padx=30, pady=(5, 0),
                                  before=self._status_label)
            self._live_label.configure(
                text="Transcription en direct (premier morceau dans 5 min)")
            self.clear_live_transcript()
        else:
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._session_name.configure(state="normal")
            self._mic_combo.configure(state="normal")
            self._lb_combo.configure(state="normal")
            self._scan_btn.configure(state="normal")
            self._status_label.configure(text="Pret a enregistrer",
                                         text_color="gray")
            self._live_frame.pack_forget()

    def update_levels(self, mic_level, sys_level):
        """Met a jour les VU-metres."""
        self._mic_meter.level = mic_level
        self._sys_meter.level = sys_level

    def update_timer(self, elapsed_seconds):
        """Met a jour le timer."""
        hours = int(elapsed_seconds) // 3600
        minutes = (int(elapsed_seconds) % 3600) // 60
        seconds = int(elapsed_seconds) % 60
        self._timer_label.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def set_status(self, text, color="gray"):
        self._status_label.configure(text=text, text_color=color)

    def get_session_name(self):
        return self._session_name.get().strip()

    # --- Transcription en direct ---

    def add_live_chunk(self, chunk_num):
        """Ajoute une ligne pour un nouveau morceau dans la liste."""
        row = ctk.CTkFrame(self._chunks_frame, fg_color="transparent", height=24)
        row.pack(fill="x", pady=1)
        row.pack_propagate(False)

        dot = ctk.CTkLabel(row, text="\u25CF", width=18,
                           font=ctk.CTkFont(size=12), text_color="#FF9800")
        dot.pack(side="left", padx=(4, 2))

        ctk.CTkLabel(row, text=f"Morceau {chunk_num}",
                     width=85, anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=2)

        status_label = ctk.CTkLabel(row, text="Transcription...",
                                    width=130, anchor="w",
                                    font=ctk.CTkFont(size=11),
                                    text_color="#FF9800")
        status_label.pack(side="left", padx=2)

        detail_label = ctk.CTkLabel(row, text="",
                                    width=250, anchor="w",
                                    font=ctk.CTkFont(size=10),
                                    text_color="gray")
        detail_label.pack(side="left", padx=2)

        self._chunk_rows[chunk_num] = (row, dot, status_label, detail_label)

        # Auto-scroll vers le bas
        try:
            self._chunks_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def update_live_chunk_status(self, chunk_num, status, detail=""):
        """Met a jour l'etat d'un morceau.

        status: 'transcription', 'diarisation', 'resume', 'termine', 'erreur'
        """
        if chunk_num not in self._chunk_rows:
            return
        _, dot, status_label, detail_label = self._chunk_rows[chunk_num]

        status_map = {
            "transcription": ("Transcription...", "#FF9800"),
            "diarisation": ("Diarisation...", "#FF9800"),
            "resume": ("Resume LLM...", "#2196F3"),
            "termine": ("Termine", "#4CAF50"),
            "erreur": ("Erreur", "#F44336"),
        }
        text, color = status_map.get(status, (status, "#FF9800"))
        dot.configure(text_color=color)
        status_label.configure(text=text, text_color=color)
        if detail:
            detail_label.configure(text=detail)

    def update_live_transcript(self, text, chunk_num):
        """Met a jour l'apercu de transcription en direct."""
        self._live_label.configure(
            text=f"Transcription en direct - {chunk_num} morceau(x) traite(s)",
            text_color="#4CAF50")
        self._live_text.configure(state="normal")
        self._live_text.delete("0.0", "end")
        self._live_text.insert("0.0", text)
        self._live_text.configure(state="disabled")
        self._live_text.see("end")

    def clear_live_transcript(self):
        """Efface la zone de transcription en direct et la liste des morceaux."""
        self._live_text.configure(state="normal")
        self._live_text.delete("0.0", "end")
        self._live_text.configure(state="disabled")
        # Nettoyer la liste des morceaux
        for widget in list(self._chunks_frame.winfo_children()):
            widget.destroy()
        self._chunk_rows.clear()

    # --- Liste des sessions ---

    def _load_sessions(self, output_dir=None):
        """Charge et affiche la liste des sessions depuis le dossier output."""
        import json
        from pathlib import Path

        # Nettoyer les anciennes lignes
        for widget in list(self._sessions_frame.winfo_children()):
            # Garder l'entete (premier widget)
            if widget == self._sessions_frame.winfo_children()[0]:
                continue
            widget.destroy()

        if output_dir is None:
            if self._settings:
                output_dir = Path(self._settings.output_directory)
                if not output_dir.is_absolute():
                    import os
                    app_dir = Path(os.path.dirname(os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__)))))
                    output_dir = app_dir / output_dir
            else:
                return

        if not output_dir.exists():
            return

        sessions = []
        for d in sorted(output_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            info = {"name": d.name, "path": d}

            # Verifier les fichiers presents
            has_mic = (d / "micro.wav").exists()
            has_transcript = (d / "transcription.json").exists()
            has_cr = (d / "compte_rendu.md").exists()
            has_marker = (d / ".recording_in_progress.json").exists()

            # Duree
            duration_str = "-"
            n_segments = "-"
            if has_transcript:
                try:
                    with open(d / "transcription.json", "r", encoding="utf-8") as f:
                        tdata = json.load(f)
                    dur = tdata.get("duration_seconds", 0)
                    if dur > 0:
                        duration_str = f"{int(dur // 60)}min"
                    segs = tdata.get("segments", [])
                    n_segments = str(len(segs))
                except Exception:
                    pass

            # Statut
            if has_marker:
                status_text = "Interrompu"
                status_color = "#FF9800"
            elif has_cr:
                status_text = "Termine"
                status_color = "#4CAF50"
            elif has_transcript:
                status_text = "Transcrit"
                status_color = "#2196F3"
            elif has_mic:
                status_text = "Enregistre"
                status_color = "#FF9800"
            else:
                status_text = "Vide"
                status_color = "gray"

            cr_text = "Oui" if has_cr else "Non"
            cr_color = "#4CAF50" if has_cr else "gray"

            info.update({
                "duration": duration_str,
                "status": status_text,
                "status_color": status_color,
                "n_segments": n_segments,
                "cr_text": cr_text,
                "cr_color": cr_color,
            })
            sessions.append(info)

        # Afficher (max 20)
        for s in sessions[:20]:
            row = ctk.CTkFrame(self._sessions_frame, fg_color="transparent",
                                height=26)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            # Nom (tronque si trop long)
            name = s["name"]
            if len(name) > 28:
                name = name[:25] + "..."
            ctk.CTkLabel(row, text=name, width=200, anchor="w",
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=4)

            ctk.CTkLabel(row, text=s["duration"], width=80, anchor="w",
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=4)

            ctk.CTkLabel(row, text=s["status"], width=130, anchor="w",
                         font=ctk.CTkFont(size=11),
                         text_color=s["status_color"]).pack(side="left", padx=4)

            ctk.CTkLabel(row, text=s["n_segments"], width=70, anchor="w",
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=4)

            ctk.CTkLabel(row, text=s["cr_text"], width=60, anchor="w",
                         font=ctk.CTkFont(size=11),
                         text_color=s["cr_color"]).pack(side="left", padx=4)
