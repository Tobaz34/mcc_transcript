"""Dialogue de progression modale."""

import customtkinter as ctk


class ProgressDialog(ctk.CTkToplevel):
    """Fenetre modale affichant la progression du traitement."""

    def __init__(self, parent, title="Traitement en cours"):
        super().__init__(parent)
        self.title(title)
        self.geometry("500x200")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Centrer sur la fenetre parente
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 200) // 2
        self.geometry(f"+{x}+{y}")

        # Contenu
        self._frame = ctk.CTkFrame(self)
        self._frame.pack(fill="both", expand=True, padx=20, pady=20)

        self._status_label = ctk.CTkLabel(
            self._frame, text="Initialisation...",
            font=ctk.CTkFont(size=14),
        )
        self._status_label.pack(pady=(10, 5))

        self._progress_bar = ctk.CTkProgressBar(self._frame, width=400)
        self._progress_bar.pack(pady=10)
        self._progress_bar.set(0)

        self._detail_label = ctk.CTkLabel(
            self._frame, text="",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self._detail_label.pack(pady=(0, 10))

        self._cancel_requested = False
        self._cancel_btn = ctk.CTkButton(
            self._frame, text="Annuler", width=100,
            command=self._on_cancel,
            fg_color="#666", hover_color="#888",
        )
        self._cancel_btn.pack(pady=5)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def update_progress(self, message: str, progress: float):
        """Met a jour le message et la barre de progression."""
        self._status_label.configure(text=message)
        self._progress_bar.set(progress)

    def set_detail(self, text: str):
        """Met a jour le texte de detail."""
        self._detail_label.configure(text=text)

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def _on_cancel(self):
        self._cancel_requested = True
        self._status_label.configure(text="Annulation en cours...")
        self._cancel_btn.configure(state="disabled")

    def close(self):
        self.grab_release()
        self.destroy()
