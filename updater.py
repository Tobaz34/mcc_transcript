"""Systeme de mise a jour automatique depuis GitHub.

Telecharge la derniere version depuis GitHub et met a jour les fichiers
de l'application sans toucher aux donnees utilisateur.

Fichiers/dossiers PRESERVES (jamais ecrases) :
  - output/          (enregistrements et transcriptions)
  - models/          (modeles Whisper telecharges)
  - config/settings.json (preferences utilisateur)
  - venv/            (environnement Python)
  - logs/            (journaux)
"""

import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

# Dossiers racine
APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(APP_DIR))


# Fichiers et dossiers a ne JAMAIS ecraser
PRESERVE = {
    "output",
    "models",
    "venv",
    "logs",
    ".git",
    "__pycache__",
    "config/settings.json",
}

# Extensions a ne pas copier depuis le ZIP
SKIP_EXTENSIONS = {".pyc", ".pyo"}


def get_current_version():
    """Lit la version actuelle depuis constants.py."""
    try:
        from config.constants import APP_VERSION
        return APP_VERSION
    except Exception:
        return "0.0.0"


def get_github_config():
    """Lit la config GitHub depuis constants.py."""
    try:
        from config.constants import GITHUB_REPO, GITHUB_API_URL, GITHUB_ZIP_URL
        return GITHUB_REPO, GITHUB_API_URL, GITHUB_ZIP_URL
    except Exception:
        return None, None, None


def check_internet():
    """Verifie la connexion internet."""
    try:
        urllib.request.urlopen("https://api.github.com", timeout=5)
        return True
    except Exception:
        return False


def fetch_latest_release(api_url):
    """Recupere les infos de la derniere release GitHub."""
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "MCC-TRANSCRIPT-Updater"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "version": data.get("tag_name", "").lstrip("v"),
            "name": data.get("name", ""),
            "body": data.get("body", ""),
            "zip_url": data.get("zipball_url", ""),
            "published": data.get("published_at", ""),
        }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # Pas de release publiee
        raise
    except Exception:
        return None


def fetch_latest_from_main(repo):
    """Recupere la version depuis le fichier constants.py de la branche main."""
    raw_url = f"https://raw.githubusercontent.com/{repo}/main/config/constants.py"
    try:
        req = urllib.request.Request(raw_url, headers={"User-Agent": "MCC-TRANSCRIPT-Updater"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
        # Extraire APP_VERSION du fichier
        for line in content.splitlines():
            if line.strip().startswith("APP_VERSION"):
                # APP_VERSION = "1.2.3"
                version = line.split("=", 1)[1].strip().strip('"').strip("'")
                return version
    except Exception:
        pass
    return None


def compare_versions(current, latest):
    """Compare deux versions semver. Retourne True si latest > current."""
    def parse(v):
        parts = v.replace("-", ".").split(".")
        result = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                result.append(0)
        while len(result) < 3:
            result.append(0)
        return tuple(result[:3])

    return parse(latest) > parse(current)


def download_and_extract(zip_url, dest_dir):
    """Telecharge le ZIP et l'extrait dans dest_dir."""
    print(f"  Telechargement depuis GitHub...")
    req = urllib.request.Request(zip_url, headers={"User-Agent": "MCC-TRANSCRIPT-Updater"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()

    size_mb = len(data) / (1024 * 1024)
    print(f"  Telecharge : {size_mb:.1f} Mo")

    print(f"  Extraction...")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest_dir)

    # Le ZIP contient un dossier racine (ex: "user-repo-hash/")
    extracted = list(Path(dest_dir).iterdir())
    if len(extracted) == 1 and extracted[0].is_dir():
        return extracted[0]
    return Path(dest_dir)


def should_preserve(rel_path):
    """Verifie si un chemin relatif doit etre preserve."""
    rel_str = str(rel_path).replace("\\", "/")

    for p in PRESERVE:
        if rel_str == p or rel_str.startswith(p + "/"):
            return True

    # Ne pas copier les fichiers compiles
    if Path(rel_str).suffix in SKIP_EXTENSIONS:
        return True

    return False


def apply_update(source_dir, target_dir):
    """Copie les fichiers mis a jour depuis source vers target."""
    updated = 0
    skipped = 0

    for src_path in source_dir.rglob("*"):
        if src_path.is_dir():
            continue

        rel = src_path.relative_to(source_dir)

        if should_preserve(rel):
            skipped += 1
            continue

        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Copier le fichier
        shutil.copy2(src_path, dest)
        updated += 1

    return updated, skipped


def update_dependencies():
    """Met a jour les dependances si requirements.txt a change."""
    req_file = APP_DIR / "requirements.txt"
    python = APP_DIR / "venv" / "Scripts" / "python.exe"

    if not python.exists():
        print("  Environnement virtuel non trouve, dependances non mises a jour.")
        return False

    if not req_file.exists():
        return True

    print("  Mise a jour des dependances Python...")
    import subprocess
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(req_file), "-q"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ATTENTION: Erreur pip : {result.stderr[:200]}")
        return False

    print("  Dependances a jour.")
    return True


def main():
    print("=" * 60)
    print("  MCC - TRANSCRIPT - Mise a jour")
    print("=" * 60)
    print()

    # Config
    repo, api_url, zip_url = get_github_config()
    if not repo or "VOTRE-PSEUDO" in repo:
        print("  ERREUR: L'URL GitHub n'est pas configuree.")
        print("  Editez config/constants.py et renseignez GITHUB_REPO.")
        return False

    current = get_current_version()
    print(f"  Version actuelle : {current}")

    # Connexion
    if not check_internet():
        print("  ERREUR: Pas de connexion internet.")
        return False

    # Verifier la derniere version
    print("  Verification des mises a jour...")

    # Essayer d'abord les releases
    release = fetch_latest_release(api_url)
    latest_version = None
    download_url = None

    if release and release["version"]:
        latest_version = release["version"]
        download_url = release["zip_url"]
        print(f"  Derniere release : {latest_version}")
        if release["name"]:
            print(f"  Nom : {release['name']}")
    else:
        # Pas de release, verifier la branche main directement
        print("  Aucune release trouvee, verification de la branche main...")
        latest_version = fetch_latest_from_main(repo)
        download_url = zip_url
        if latest_version:
            print(f"  Version sur main : {latest_version}")

    if not latest_version:
        print("  Impossible de determiner la derniere version.")
        print(f"  Verifiez que le depot {repo} existe et est accessible.")
        return False

    # Comparer
    if not compare_versions(current, latest_version):
        print(f"\n  Votre version ({current}) est a jour !")
        return True

    print(f"\n  Nouvelle version disponible : {latest_version}")
    if release and release.get("body"):
        notes = release["body"][:300]
        print(f"  Notes : {notes}")
    print()

    # Confirmation
    response = input("  Voulez-vous mettre a jour ? (O/n) : ").strip().lower()
    if response in ("n", "non", "no"):
        print("  Mise a jour annulee.")
        return True

    # Telechargement
    print()
    temp_dir = tempfile.mkdtemp(prefix="mcc_update_")
    try:
        source = download_and_extract(download_url, temp_dir)

        # Sauvegarder les fichiers critiques
        backup_dir = APP_DIR / "_backup_update"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        backup_dir.mkdir()

        for f in ["config/constants.py", "requirements.txt", "main.py"]:
            src = APP_DIR / f
            if src.exists():
                dest = backup_dir / f
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

        print("  Sauvegarde des fichiers critiques effectuee.")

        # Appliquer la mise a jour
        print("  Application de la mise a jour...")
        updated, skipped = apply_update(source, APP_DIR)
        print(f"  {updated} fichier(s) mis a jour, {skipped} preserve(s).")

        # Mettre a jour les dependances
        print()
        update_dependencies()

        # Nettoyage backup si tout s'est bien passe
        shutil.rmtree(backup_dir, ignore_errors=True)

        print()
        print("=" * 60)
        print(f"  Mise a jour vers {latest_version} terminee !")
        print("  Relancez l'application avec LANCER.bat")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n  ERREUR lors de la mise a jour : {e}")
        print()

        # Tenter la restauration
        backup_dir = APP_DIR / "_backup_update"
        if backup_dir.exists():
            print("  Restauration des fichiers de sauvegarde...")
            for f in backup_dir.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(backup_dir)
                    dest = APP_DIR / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
            shutil.rmtree(backup_dir, ignore_errors=True)
            print("  Restauration terminee.")

        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    success = main()
    print()
    input("Appuyez sur Entree pour fermer...")
    sys.exit(0 if success else 1)
