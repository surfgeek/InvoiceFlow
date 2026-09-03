"""Create the local runtime and databases from a fresh checkout."""

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run_visible(command: list[str], failure_message: str) -> None:
    """Run setup work with an immediate heartbeat during silent startup."""
    try:
        process = subprocess.Popen(command, start_new_session=True)
    except OSError as error:
        raise SystemExit(f"{failure_message} {error}") from error
    elapsed = 0
    try:
        while True:
            try:
                return_code = process.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                elapsed += 1
                if elapsed == 1 or elapsed % 5 == 0:
                    print(f"  Setup is active ({elapsed}s elapsed)...", flush=True)
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise SystemExit("Setup cancelled before completion.") from None
    if return_code:
        raise SystemExit(failure_message)


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
    # Miniconda's ensurepip subprocess can stall on Windows. The parent
    # interpreter's pip installs directly into this environment below.
    run_visible(
        [sys.executable, "-m", "venv", "--without-pip", str(VENV)],
        "Could not create .venv. See the error above.",
    )


def main() -> None:
    require_python_312()
    create_environment()
    print("Installing pinned dependencies (pip may take a few seconds to display package output)...", flush=True)
    run_visible(
        [sys.executable, "-m", "pip", "--python", str(VENV_PYTHON),
         "install", "pip", "-r", str(ROOT / "requirements.txt")],
        "Could not install dependencies. See the error above.",
    )
    print("Initializing local databases...", flush=True)
    subprocess.run([str(VENV_PYTHON), str(ROOT / "setup_inventory.py")], check=True)
    print("InvoiceFlow setup complete.", flush=True)


if __name__ == "__main__":
    main()
