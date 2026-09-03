"""Create the local runtime and databases from a fresh checkout."""

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def require_python_312() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit(
            f"Python 3.12 is required; this command is using {sys.version.split()[0]}."
        )


def create_environment() -> None:
    if VENV_PYTHON.is_file():
        return
    if VENV.exists():
        print("Removing an incomplete .venv from an earlier setup attempt...", flush=True)
        shutil.rmtree(VENV)
    print("Creating .venv...", flush=True)
    try:
        # Miniconda's ensurepip subprocess can stall on Windows. The parent
        # interpreter's pip installs directly into this environment below.
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(VENV)],
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise SystemExit("Could not create .venv. See the error above.") from error


def main() -> None:
    require_python_312()
    create_environment()
    print("Installing pinned dependencies...", flush=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "--python", str(VENV_PYTHON),
             "install", "pip", "-r", str(ROOT / "requirements.txt")],
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise SystemExit("Could not install dependencies. See the error above.") from error
    print("Initializing local databases...", flush=True)
    subprocess.run([str(VENV_PYTHON), str(ROOT / "setup_inventory.py")], check=True)
    print("InvoiceFlow setup complete.", flush=True)


if __name__ == "__main__":
    main()
