"""Frame de parametres avec detection automatique du materiel."""

import threading
import customtkinter as ctk
from typing import Optional

from config.settings import AppSettings
from core.audio_devices import AudioDeviceManager


class SettingsFrame(ctk.CTkFrame):
    """Configuration des peripheriques audio, modeles et chemins."""

    def __init__(self, parent, settings: AppSettings,
                 device_manager: AudioDeviceManager,
                 on_save=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._settings = settings
        self._device_manager = device_manager
        self._on_save = on_save
        self._current_recommendation = None
        self._build_ui()

    def _build_ui(self):
        # Titre
        ctk.CTkLabel(self, text="Parametres",
                      font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(20, 15))

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # === MATERIEL ===
        self._add_section(scroll, "Materiel detecte")

        self._hw_info_label = ctk.CTkLabel(
            scroll, text="Cliquez sur 'Detecter' pour analyser votre materiel.",
            font=ctk.CTkFont(family="Consolas", size=11),
            justify="left", anchor="w",
        )
        self._hw_info_label.pack(fill="x", pady=3)

        hw_btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        hw_btn_frame.pack(fill="x", pady=5)

        self._detect_btn = ctk.CTkButton(
            hw_btn_frame, text="Detecter le materiel", width=200,
            command=self._detect_hardware,
        )
        self._detect_btn.pack(side="left", padx=5)

        self._apply_reco_btn = ctk.CTkButton(
            hw_btn_frame, text="Appliquer la recommandation", width=220,
            command=self._apply_recommendation,
            fg_color="#4CAF50", hover_color="#388E3C",
            state="disabled",
        )
        self._apply_reco_btn.pack(side="left", padx=5)

        # === AUDIO ===
        self._add_section(scroll, "Peripheriques Audio")

        mic_devices = self._device_manager.list_input_devices()
        mic_names = [f"{d.name} (#{d.index})" for d in mic_devices]
        if not mic_names:
            mic_names = ["Aucun microphone detecte"]

        mic_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        mic_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(mic_frame, text="Microphone :", width=150, anchor="w").pack(side="left")
        self._mic_combo = ctk.CTkComboBox(mic_frame, values=mic_names, width=400)
        self._mic_combo.pack(side="left", padx=10)

        if self._settings.mic_device_index is not None:
            for i, d in enumerate(mic_devices):
                if d.index == self._settings.mic_device_index:
                    self._mic_combo.set(mic_names[i])
                    break

        lb_devices = self._device_manager.list_wasapi_loopback_devices()
        lb_names = [f"{d.name} (#{d.index})" for d in lb_devices]
        if not lb_names:
            lb_names = ["Aucun peripherique loopback detecte"]

        lb_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        lb_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(lb_frame, text="Son systeme :", width=150, anchor="w").pack(side="left")
        self._lb_combo = ctk.CTkComboBox(lb_frame, values=lb_names, width=400)
        self._lb_combo.pack(side="left", padx=10)

        if self._settings.loopback_device_index is not None:
            for i, d in enumerate(lb_devices):
                if d.index == self._settings.loopback_device_index:
                    self._lb_combo.set(lb_names[i])
                    break

        ctk.CTkButton(scroll, text="Rafraichir les peripheriques", width=200,
                       command=self._refresh_devices).pack(pady=10)

        # === TRANSCRIPTION ===
        self._add_section(scroll, "Transcription (Whisper)")

        model_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        model_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(model_frame, text="Modele :", width=150, anchor="w").pack(side="left")
        self._model_combo = ctk.CTkComboBox(
            model_frame,
            values=["large-v3", "medium", "small", "base", "tiny"],
            width=200,
        )
        self._model_combo.set(self._settings.whisper_model)
        self._model_combo.pack(side="left", padx=10)

        self._model_info = ctk.CTkLabel(model_frame, text="",
                                         font=ctk.CTkFont(size=11), text_color="gray")
        self._model_info.pack(side="left", padx=5)
        self._model_combo.configure(command=self._on_model_changed)
        self._on_model_changed(self._settings.whisper_model)

        device_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        device_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(device_frame, text="Acceleration :", width=150, anchor="w").pack(side="left")
        self._device_combo = ctk.CTkComboBox(
            device_frame, values=["auto", "cuda", "cpu"], width=200,
        )
        self._device_combo.set(self._settings.whisper_device)
        self._device_combo.pack(side="left", padx=10)

        compute_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        compute_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(compute_frame, text="Precision :", width=150, anchor="w").pack(side="left")
        self._compute_combo = ctk.CTkComboBox(
            compute_frame,
            values=["float16", "int8_float16", "int8", "float32"],
            width=200,
        )
        self._compute_combo.set(self._settings.whisper_compute_type)
        self._compute_combo.pack(side="left", padx=10)

        lang_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        lang_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(lang_frame, text="Langue :", width=150, anchor="w").pack(side="left")
        self._lang_combo = ctk.CTkComboBox(
            lang_frame, values=["fr", "en", "de", "es", "it"], width=200,
        )
        self._lang_combo.set(self._settings.language)
        self._lang_combo.pack(side="left", padx=10)

        # === LLM ===
        self._add_section(scroll, "Compte Rendu (Ollama)")

        ollama_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        ollama_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(ollama_frame, text="Modele LLM :", width=150, anchor="w").pack(side="left")
        self._ollama_model = ctk.CTkEntry(ollama_frame, width=200)
        self._ollama_model.insert(0, self._settings.ollama_model)
        self._ollama_model.pack(side="left", padx=10)

        host_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        host_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(host_frame, text="Ollama host :", width=150, anchor="w").pack(side="left")
        self._ollama_host = ctk.CTkEntry(host_frame, width=300)
        self._ollama_host.insert(0, self._settings.ollama_host)
        self._ollama_host.pack(side="left", padx=10)

        self._ollama_status = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=11))
        self._ollama_status.pack(pady=3)

        ollama_btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        ollama_btn_frame.pack(fill="x", pady=5)

        ctk.CTkButton(ollama_btn_frame, text="Tester la connexion", width=180,
                       command=self._test_ollama).pack(side="left", padx=5)

        self._pull_btn = ctk.CTkButton(
            ollama_btn_frame, text="Telecharger le modele", width=200,
            command=self._pull_ollama_model,
            fg_color="#FF9800", hover_color="#F57C00",
        )
        self._pull_btn.pack(side="left", padx=5)

        self._pull_progress = ctk.CTkLabel(
            scroll, text="", font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._pull_progress.pack(fill="x", pady=2)

        # === THEME ===
        self._add_section(scroll, "Apparence")

        theme_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        theme_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(theme_frame, text="Theme :", width=150, anchor="w").pack(side="left")
        self._theme_combo = ctk.CTkComboBox(
            theme_frame, values=["dark", "light"], width=200,
        )
        self._theme_combo.set(self._settings.theme)
        self._theme_combo.pack(side="left", padx=10)

        # === MISE A JOUR ===
        self._add_section(scroll, "Mise a jour")

        self._update_label = ctk.CTkLabel(
            scroll, text="Cliquez pour verifier si une mise a jour est disponible.",
            font=ctk.CTkFont(size=11), justify="left", anchor="w",
        )
        self._update_label.pack(fill="x", pady=3)

        update_btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        update_btn_frame.pack(fill="x", pady=5)

        self._check_update_btn = ctk.CTkButton(
            update_btn_frame, text="Verifier les mises a jour", width=220,
            command=self._check_for_updates,
        )
        self._check_update_btn.pack(side="left", padx=5)

        from config.constants import APP_VERSION
        ctk.CTkLabel(
            update_btn_frame, text=f"Version actuelle : {APP_VERSION}",
            font=ctk.CTkFont(size=11), text_color="gray",
        ).pack(side="left", padx=15)

        # Sauvegarder
        ctk.CTkButton(self, text="Sauvegarder", width=200, height=40,
                       font=ctk.CTkFont(size=14, weight="bold"),
                       command=self._save).pack(pady=15)

    @staticmethod
    def _add_section(parent, title: str):
        ctk.CTkLabel(parent, text=title,
                      font=ctk.CTkFont(size=15, weight="bold")).pack(
            fill="x", pady=(15, 5), anchor="w",
        )
        sep = ctk.CTkFrame(parent, height=2, fg_color="gray")
        sep.pack(fill="x", pady=(0, 8))

    def _on_model_changed(self, model_name: str):
        info_map = {
            "large-v3": "Qualite excellente | ~3 Go | Lent sur CPU",
            "medium":   "Bonne qualite | ~1.5 Go | Correct sur CPU",
            "small":    "Qualite correcte | ~500 Mo | Rapide",
            "base":     "Qualite basique | ~150 Mo | Tres rapide",
            "tiny":     "Qualite faible | ~75 Mo | Instantane",
        }
        self._model_info.configure(text=info_map.get(model_name, ""))

    def _detect_hardware(self):
        self._detect_btn.configure(state="disabled", text="Detection en cours...")
        self._hw_info_label.configure(text="Analyse du materiel...")

        def worker():
            try:
                from core.hardware import detect_hardware, recommend_model, format_recommendation
                hw = detect_hardware()
                rec = recommend_model(hw)
                summary = f"{hw.summary()}\n\n{format_recommendation(rec)}"
                self.after(0, lambda: self._on_hw_detected(summary, rec))
            except Exception as e:
                self.after(0, lambda: self._on_hw_detected(f"Erreur: {e}", None))

        threading.Thread(target=worker, daemon=True).start()

    def _on_hw_detected(self, summary: str, recommendation):
        self._hw_info_label.configure(text=summary)
        self._detect_btn.configure(state="normal", text="Detecter le materiel")
        self._current_recommendation = recommendation
        if recommendation:
            self._apply_reco_btn.configure(state="normal")

    def _apply_recommendation(self):
        rec = self._current_recommendation
        if not rec:
            return
        self._model_combo.set(rec.whisper_model)
        self._device_combo.set(rec.whisper_device)
        self._compute_combo.set(rec.whisper_compute_type)
        self._on_model_changed(rec.whisper_model)

    def _refresh_devices(self):
        self._device_manager.terminate()
        self._device_manager = AudioDeviceManager()

        mic_devices = self._device_manager.list_input_devices()
        mic_names = [f"{d.name} (#{d.index})" for d in mic_devices]
        if not mic_names:
            mic_names = ["Aucun microphone detecte"]
        self._mic_combo.configure(values=mic_names)

        lb_devices = self._device_manager.list_wasapi_loopback_devices()
        lb_names = [f"{d.name} (#{d.index})" for d in lb_devices]
        if not lb_names:
            lb_names = ["Aucun peripherique loopback detecte"]
        self._lb_combo.configure(values=lb_names)

    def _test_ollama(self):
        from core.summarizer import MeetingSummarizer
        model = self._ollama_model.get().strip()
        host = self._ollama_host.get().strip()
        summarizer = MeetingSummarizer(model=model, host=host)
        ok, msg = summarizer.check_available()
        if ok:
            self._ollama_status.configure(text="Connexion OK !", text_color="#4CAF50")
        else:
            self._ollama_status.configure(text=msg, text_color="#F44336")

    def _pull_ollama_model(self):
        model = self._ollama_model.get().strip()
        if not model:
            self._ollama_status.configure(
                text="Entrez un nom de modele.", text_color="#F44336")
            return

        self._pull_btn.configure(state="disabled", text="Telechargement...")
        self._pull_progress.configure(text=f"Telechargement de '{model}'...", text_color="gray")
        self._ollama_status.configure(text="")

        def worker():
            try:
                import subprocess
                host = self._ollama_host.get().strip()

                # Verifier qu'Ollama tourne, sinon le demarrer
                try:
                    import urllib.request
                    urllib.request.urlopen(host, timeout=3)
                except Exception:
                    self.after(0, lambda: self._pull_progress.configure(
                        text="Demarrage d'Ollama..."))
                    subprocess.Popen(
                        ["ollama", "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    import time
                    time.sleep(5)

                # Lancer ollama pull avec suivi
                process = subprocess.Popen(
                    ["ollama", "pull", model],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )

                for line in process.stdout:
                    line = line.strip()
                    if line:
                        self.after(0, lambda l=line: self._pull_progress.configure(text=l))

                process.wait()
                if process.returncode == 0:
                    self.after(0, lambda: self._on_pull_done(model, True, ""))
                else:
                    self.after(0, lambda: self._on_pull_done(
                        model, False, "Le telechargement a echoue."))
            except FileNotFoundError:
                self.after(0, lambda: self._on_pull_done(
                    model, False, "Ollama n'est pas installe. Installez-le depuis ollama.com"))
            except Exception as e:
                self.after(0, lambda: self._on_pull_done(model, False, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_pull_done(self, model, success, error_msg):
        self._pull_btn.configure(state="normal", text="Telecharger le modele")
        if success:
            self._pull_progress.configure(
                text=f"Modele '{model}' telecharge avec succes !",
                text_color="#4CAF50")
            self._ollama_status.configure(
                text="Pret a utiliser.", text_color="#4CAF50")
        else:
            self._pull_progress.configure(
                text=f"Echec : {error_msg}", text_color="#F44336")

    def _check_for_updates(self):
        self._check_update_btn.configure(state="disabled", text="Verification...")
        self._update_label.configure(text="Connexion a GitHub...")

        def worker():
            try:
                import sys, os
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))))
                from updater import (
                    get_current_version, get_github_config, check_internet,
                    fetch_latest_release, fetch_latest_from_main, compare_versions,
                )

                current = get_current_version()
                repo, api_url, zip_url = get_github_config()

                if not repo or "VOTRE-PSEUDO" in repo:
                    self.after(0, lambda: self._on_update_checked(
                        "URL GitHub non configuree. Editez config/constants.py.", None))
                    return

                if not check_internet():
                    self.after(0, lambda: self._on_update_checked(
                        "Pas de connexion internet.", None))
                    return

                release = fetch_latest_release(api_url)
                latest = None
                if release and release["version"]:
                    latest = release["version"]
                else:
                    latest = fetch_latest_from_main(repo)

                if not latest:
                    self.after(0, lambda: self._on_update_checked(
                        "Impossible de verifier (depot introuvable ou vide).", None))
                    return

                if compare_versions(current, latest):
                    self.after(0, lambda: self._on_update_checked(
                        f"Nouvelle version disponible : {latest} (actuelle: {current})\n"
                        f"Fermez l'application et lancez MISE_A_JOUR.bat",
                        "#FF9800"))
                else:
                    self.after(0, lambda: self._on_update_checked(
                        f"Vous etes a jour ! (version {current})", "#4CAF50"))
            except Exception as e:
                self.after(0, lambda: self._on_update_checked(
                    f"Erreur: {e}", "#F44336"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_checked(self, message, color):
        self._update_label.configure(text=message)
        if color:
            self._update_label.configure(text_color=color)
        self._check_update_btn.configure(state="normal", text="Verifier les mises a jour")

    def _save(self):
        mic_text = self._mic_combo.get()
        if "(#" in mic_text:
            try:
                self._settings.mic_device_index = int(
                    mic_text.split("(#")[1].rstrip(")")
                )
            except (ValueError, IndexError):
                pass

        lb_text = self._lb_combo.get()
        if "(#" in lb_text:
            try:
                self._settings.loopback_device_index = int(
                    lb_text.split("(#")[1].rstrip(")")
                )
            except (ValueError, IndexError):
                pass

        self._settings.whisper_model = self._model_combo.get()
        self._settings.whisper_device = self._device_combo.get()
        self._settings.whisper_compute_type = self._compute_combo.get()
        self._settings.language = self._lang_combo.get()
        self._settings.ollama_model = self._ollama_model.get().strip()
        self._settings.ollama_host = self._ollama_host.get().strip()
        self._settings.theme = self._theme_combo.get()

        if self._on_save:
            self._on_save(self._settings)
