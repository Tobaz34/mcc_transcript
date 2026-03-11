"""Barre d'etat en bas de la fenetre."""

import customtkinter as ctk


class StatusBar(ctk.CTkFrame):
    """Barre d'etat avec message et indicateur."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, height=30, **kwargs)
        self.pack_propagate(False)

        self._label = ctk.CTkLabel(
            self, text="Pret",
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self._label.pack(side="left", padx=10, fill="x", expand=True)

        self._indicator = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=11),
            anchor="e",
        )
        self._indicator.pack(side="right", padx=10)

    def set_status(self, text: str, color: str = "gray"):
        self._label.configure(text=text, text_color=color)

    def set_indicator(self, text: str, color: str = "gray"):
        self._indicator.configure(text=text, text_color=color)
