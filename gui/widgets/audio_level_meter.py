"""VU-metre audio temps reel avec affichage dB."""

import customtkinter as ctk


class AudioLevelMeter(ctk.CTkCanvas):
    """Barre horizontale indiquant le niveau audio en temps reel avec valeur dB."""

    def __init__(self, parent, width=400, height=24, **kwargs):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, **kwargs)
        self._width = width
        self._height = height
        self._level = 0.0
        self._peak = 0.0
        self._peak_decay = 0.95  # Vitesse de descente du peak

        # Couleurs
        self._bg_color = "#1a1a1a"
        self._green = "#4CAF50"
        self._yellow = "#FFC107"
        self._red = "#F44336"
        self._peak_color = "#FFFFFF"
        self._text_color = "#CCCCCC"
        self._grid_color = "#333333"

        self.configure(bg=self._bg_color)
        self._draw()

    @property
    def level(self) -> float:
        return self._level

    @level.setter
    def level(self, value: float):
        self._level = max(0.0, min(1.0, value))
        # Peak hold avec decay
        if self._level > self._peak:
            self._peak = self._level
        else:
            self._peak *= self._peak_decay
            if self._peak < 0.01:
                self._peak = 0.0
        self._draw()

    def _draw(self):
        self.delete("all")

        h = self._height
        w = self._width
        bar_margin = 2
        text_width = 45  # Espace pour le texte dB
        bar_w = w - text_width - 4

        # Fond
        self.create_rectangle(0, 0, w, h, fill=self._bg_color, outline="")

        # Graduations de fond
        for pct in (0.25, 0.5, 0.6, 0.75, 0.85):
            x = int(pct * bar_w)
            self.create_line(x, 0, x, h, fill=self._grid_color, width=1)

        # Barre de niveau segmentee
        bar_width = int(self._level * bar_w)
        if bar_width > 0:
            # Zone verte (0 - 60%)
            green_end = min(bar_width, int(0.6 * bar_w))
            if green_end > 0:
                self.create_rectangle(
                    0, bar_margin, green_end, h - bar_margin,
                    fill=self._green, outline="")

            # Zone jaune (60% - 85%)
            if bar_width > int(0.6 * bar_w):
                yellow_start = int(0.6 * bar_w)
                yellow_end = min(bar_width, int(0.85 * bar_w))
                self.create_rectangle(
                    yellow_start, bar_margin, yellow_end, h - bar_margin,
                    fill=self._yellow, outline="")

            # Zone rouge (85% - 100%)
            if bar_width > int(0.85 * bar_w):
                red_start = int(0.85 * bar_w)
                self.create_rectangle(
                    red_start, bar_margin, bar_width, h - bar_margin,
                    fill=self._red, outline="")

        # Marqueur peak
        if self._peak > 0.02:
            peak_x = int(self._peak * bar_w)
            self.create_line(
                peak_x, bar_margin, peak_x, h - bar_margin,
                fill=self._peak_color, width=2)

        # Valeur dB
        if self._level > 0.001:
            import math
            db = 20 * math.log10(self._level + 1e-10)
            db_text = f"{db:+.0f} dB"
        else:
            db_text = "-inf"

        self.create_text(
            bar_w + text_width // 2 + 2, h // 2,
            text=db_text, fill=self._text_color,
            font=("Consolas", 9), anchor="center")
