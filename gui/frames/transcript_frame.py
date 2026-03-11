"""Frame d'affichage de la transcription."""

import customtkinter as ctk
from tkinter import filedialog


class TranscriptFrame(ctk.CTkFrame):
    """Affiche la transcription avec locuteurs et timestamps."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._transcript = None
        self._build_ui()

    def _build_ui(self):
        # En-tete
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))

        ctk.CTkLabel(header, text="Transcription",
                      font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        self._export_btn = ctk.CTkButton(
            header, text="Exporter TXT", width=120,
            command=self._export_txt, state="disabled",
        )
        self._export_btn.pack(side="right", padx=5)

        # Info
        self._info_label = ctk.CTkLabel(
            self, text="Aucune transcription disponible",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self._info_label.pack(pady=5)

        # Zone de texte
        self._textbox = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word", state="disabled",
        )
        self._textbox.pack(fill="both", expand=True, padx=20, pady=(0, 20))

    def load_transcript(self, transcript):
        """Charge et affiche la transcription."""
        self._transcript = transcript

        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")

        if not transcript or not transcript.segments:
            self._textbox.insert("end", "Aucun segment transcrit.")
            self._textbox.configure(state="disabled")
            return

        duration_min = int(transcript.duration) // 60
        duration_sec = int(transcript.duration) % 60
        self._info_label.configure(
            text=f"Duree: {duration_min}min {duration_sec}s | "
                 f"{len(transcript.segments)} segments | "
                 f"Langue: {transcript.language}",
            text_color="white",
        )

        for seg in transcript.segments:
            speaker = seg.speaker or "Inconnu"
            minutes = int(seg.start) // 60
            seconds = int(seg.start) % 60
            timestamp = f"[{minutes:02d}:{seconds:02d}]"

            # Inserer avec couleurs
            self._textbox.insert("end", f"{timestamp} ")
            self._textbox.insert("end", f"{speaker}")
            self._textbox.insert("end", " :\n")
            self._textbox.insert("end", f"  {seg.text}\n\n")

        self._textbox.configure(state="disabled")
        self._export_btn.configure(state="normal")

    def _export_txt(self):
        """Exporte la transcription en fichier TXT."""
        if not self._transcript:
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Fichier texte", "*.txt")],
            title="Exporter la transcription",
        )
        if not path:
            return

        lines = []
        for seg in self._transcript.segments:
            speaker = seg.speaker or "Inconnu"
            minutes = int(seg.start) // 60
            seconds = int(seg.start) % 60
            lines.append(f"[{minutes:02d}:{seconds:02d}] {speaker} :")
            lines.append(f"  {seg.text}")
            lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
