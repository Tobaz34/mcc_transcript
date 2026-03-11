"""Frame d'affichage et d'export du compte rendu."""

import customtkinter as ctk
from tkinter import filedialog


class MinutesFrame(ctk.CTkFrame):
    """Affiche le compte rendu genere et permet l'export."""

    def __init__(self, parent, on_regenerate=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._minutes_text = ""
        self._on_regenerate = on_regenerate
        self._build_ui()

    def _build_ui(self):
        # En-tete
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))

        ctk.CTkLabel(header, text="Compte Rendu",
                      font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")

        self._export_md_btn = ctk.CTkButton(
            btn_frame, text="Exporter MD", width=100,
            command=self._export_md, state="disabled",
        )
        self._export_md_btn.pack(side="left", padx=3)

        self._export_docx_btn = ctk.CTkButton(
            btn_frame, text="Exporter DOCX", width=110,
            command=self._export_docx, state="disabled",
        )
        self._export_docx_btn.pack(side="left", padx=3)

        self._regen_btn = ctk.CTkButton(
            btn_frame, text="Regenerer", width=100,
            command=self._on_regen_click, state="disabled",
            fg_color="#FF9800", hover_color="#F57C00",
        )
        self._regen_btn.pack(side="left", padx=3)

        # Instructions supplementaires
        instr_frame = ctk.CTkFrame(self, fg_color="transparent")
        instr_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(instr_frame, text="Instructions supplementaires :",
                      font=ctk.CTkFont(size=11)).pack(side="left")
        self._custom_instructions = ctk.CTkEntry(
            instr_frame, width=400,
            placeholder_text="Ex: Insister sur les decisions budgetaires...",
        )
        self._custom_instructions.pack(side="left", padx=10)

        # Zone de texte
        self._textbox = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Calibri", size=13),
            wrap="word", state="disabled",
        )
        self._textbox.pack(fill="both", expand=True, padx=20, pady=(5, 20))

    def load_minutes(self, text: str):
        """Affiche le compte rendu."""
        self._minutes_text = text
        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")
        self._textbox.insert("end", text)
        self._textbox.configure(state="disabled")

        self._export_md_btn.configure(state="normal")
        self._export_docx_btn.configure(state="normal")
        self._regen_btn.configure(state="normal")

    def append_token(self, token: str):
        """Ajoute un token au compte rendu (mode streaming)."""
        self._textbox.configure(state="normal")
        self._textbox.insert("end", token)
        self._textbox.see("end")
        self._textbox.configure(state="disabled")
        self._minutes_text += token

    def clear(self):
        """Vide le contenu."""
        self._minutes_text = ""
        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")
        self._textbox.configure(state="disabled")

    def _on_regen_click(self):
        if self._on_regenerate:
            instructions = self._custom_instructions.get().strip()
            self._on_regenerate(instructions)

    def _export_md(self):
        if not self._minutes_text:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Texte", "*.txt")],
            title="Exporter le compte rendu",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._minutes_text)

    def _export_docx(self):
        if not self._minutes_text:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".docx",
            filetypes=[("Word", "*.docx")],
            title="Exporter le compte rendu en Word",
        )
        if not path:
            return

        try:
            from core.pipeline import ProcessingPipeline
            # Reutiliser la logique d'export DOCX du pipeline
            pipeline = ProcessingPipeline.__new__(ProcessingPipeline)
            pipeline._export_minutes_docx(self._minutes_text, None, path)
        except Exception as e:
            # Fallback: sauver en texte
            txt_path = path.replace(".docx", ".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(self._minutes_text)
