"""VU-metre audio temps reel."""

import tkinter as tk
import customtkinter as ctk


class AudioLevelMeter(ctk.CTkCanvas):
    """Barre horizontale indiquant le niveau audio en temps reel."""

    def __init__(self, parent, width=300, height=20, label="", **kwargs):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, **kwargs)
        self._width = width
        self._height = height
        self._level = 0.0
        self._label = label

        # Couleurs
        self._bg_color = "#2b2b2b"
        self._green = "#4CAF50"
        self._yellow = "#FFC107"
        self._red = "#F44336"

        self.configure(bg=self._bg_color)
        self._draw()

    @property
    def level(self) -> float:
        return self._level

    @level.setter
    def level(self, value: float):
        self._level = max(0.0, min(1.0, value))
        self._draw()

    def _draw(self):
        self.delete("all")

        # Fond
        self.create_rectangle(0, 0, self._width, self._height,
                              fill=self._bg_color, outline="")

        # Barre de niveau
        bar_width = int(self._level * self._width)
        if bar_width > 0:
            if self._level < 0.6:
                color = self._green
            elif self._level < 0.85:
                color = self._yellow
            else:
                color = self._red

            self.create_rectangle(0, 2, bar_width, self._height - 2,
                                  fill=color, outline="")

        # Label
        if self._label:
            self.create_text(5, self._height // 2, text=self._label,
                             fill="white", anchor="w", font=("Calibri", 9))
