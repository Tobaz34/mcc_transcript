"""Cree un raccourci sur le bureau Windows vers LANCER.bat."""

import os
import sys
from pathlib import Path


def create_shortcut():
    app_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    lancer_bat = app_dir / "LANCER.bat"
    desktop = Path(os.path.expanduser("~")) / "Desktop"

    if not desktop.exists():
        # Essayer le chemin francais
        desktop = Path(os.path.expanduser("~")) / "Bureau"

    if not desktop.exists():
        # Fallback: utiliser le registre Windows
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
            winreg.CloseKey(key)
        except Exception:
            print("Impossible de trouver le dossier Bureau.")
            return False

    shortcut_path = desktop / "MCC - TRANSCRIPT.lnk"

    try:
        # Utiliser PowerShell pour creer le raccourci
        ps_script = f'''
$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{lancer_bat}"
$Shortcut.WorkingDirectory = "{app_dir}"
$Shortcut.Description = "MCC - TRANSCRIPT - Enregistrement et compte rendu de reunions"
$Shortcut.WindowStyle = 1
$Shortcut.Save()
'''
        import subprocess
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"Raccourci cree : {shortcut_path}")
            return True
        else:
            print(f"Erreur PowerShell : {result.stderr}")
            return False
    except Exception as e:
        print(f"Erreur : {e}")
        return False


if __name__ == "__main__":
    success = create_shortcut()
    sys.exit(0 if success else 1)
