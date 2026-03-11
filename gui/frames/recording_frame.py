"""Frame d'enregistrement avec controles et VU-metres."""

import customtkinter as ctk
from gui.widgets.audio_level_meter import AudioLevelMeter


class RecordingFrame(ctk.CTkFrame):
    """Interface d'enregistrement : boutons, VU-metres, timer."""

    def __init__(self, parent, on_start=None, on_stop=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._on_start = on_start
        self._on_stop = on_stop
        self._is_recording = False

        self._build_ui()

    def _build_ui(self):
        # Titre
        title = ctk.CTkLabel(self, text="Enregistrement",
                              font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=(20, 10))

        # Nom de la session
        session_frame = ctk.CTkFrame(self, fg_color="transparent")
        session_frame.pack(fill="x", padx=30, pady=5)

        ctk.CTkLabel(session_frame, text="Nom de la session :").pack(side="left")
        self._session_name = ctk.CTkEntry(session_frame, width=300,
                                           placeholder_text="reunion_projet")
        self._session_name.pack(side="left", padx=10)

        # Boutons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20)

        self._start_btn = ctk.CTkButton(
            btn_frame, text="ENREGISTRER", width=200, height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#4CAF50", hover_color="#388E3C",
            command=self._on_start_click,
        )
        self._start_btn.pack(side="left", padx=10)

        self._stop_btn = ctk.CTkButton(
            btn_frame, text="ARRETER", width=200, height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#F44336", hover_color="#D32F2F",
            command=self._on_stop_click,
            state="disabled",
        )
        self._stop_btn.pack(side="left", padx=10)

        # Timer
        self._timer_label = ctk.CTkLabel(
            self, text="00:00:00",
            font=ctk.CTkFont(family="Consolas", size=36, weight="bold"),
        )
        self._timer_label.pack(pady=10)

        # VU-metres
        meter_frame = ctk.CTkFrame(self, fg_color="transparent")
        meter_frame.pack(fill="x", padx=30, pady=10)

        # Micro
        mic_row = ctk.CTkFrame(meter_frame, fg_color="transparent")
        mic_row.pack(fill="x", pady=5)
        ctk.CTkLabel(mic_row, text="Micro    :", width=80, anchor="w",
                      font=ctk.CTkFont(size=13)).pack(side="left")
        self._mic_meter = AudioLevelMeter(mic_row, width=500, height=22)
        self._mic_meter.pack(side="left", padx=10)

        # Systeme
        sys_row = ctk.CTkFrame(meter_frame, fg_color="transparent")
        sys_row.pack(fill="x", pady=5)
        ctk.CTkLabel(sys_row, text="Systeme :", width=80, anchor="w",
                      font=ctk.CTkFont(size=13)).pack(side="left")
        self._sys_meter = AudioLevelMeter(sys_row, width=500, height=22)
        self._sys_meter.pack(side="left", padx=10)

        # Etat
        self._status_label = ctk.CTkLabel(
            self, text="Pret a enregistrer",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self._status_label.pack(pady=10)

    def _on_start_click(self):
        if self._on_start:
            session_name = self._session_name.get().strip()
            self._on_start(session_name)

    def _on_stop_click(self):
        if self._on_stop:
            self._on_stop()

    def set_recording_state(self, recording: bool):
        """Met a jour l'interface selon l'etat d'enregistrement."""
        self._is_recording = recording
        if recording:
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
            self._session_name.configure(state="disabled")
            self._status_label.configure(text="Enregistrement en cours...",
                                          text_color="#F44336")
        else:
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")
            self._session_name.configure(state="normal")
            self._status_label.configure(text="Pret a enregistrer",
                                          text_color="gray")

    def update_levels(self, mic_level: float, sys_level: float):
        """Met a jour les VU-metres."""
        self._mic_meter.level = mic_level
        self._sys_meter.level = sys_level

    def update_timer(self, elapsed_seconds: float):
        """Met a jour le timer."""
        hours = int(elapsed_seconds) // 3600
        minutes = (int(elapsed_seconds) % 3600) // 60
        seconds = int(elapsed_seconds) % 60
        self._timer_label.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def set_status(self, text: str, color: str = "gray"):
        self._status_label.configure(text=text, text_color=color)

    def get_session_name(self) -> str:
        return self._session_name.get().strip()
