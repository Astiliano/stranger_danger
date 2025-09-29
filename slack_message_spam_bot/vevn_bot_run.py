"""Utility script to bootstrap a virtual environment and run the Slack bot."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict


VENV_DIR = Path("slack_adder_env")
ENV_FILE = Path(".env")
REQUIRED_ENV_VARS = ("SLACK_BOT_TOKEN",)
REQUIREMENTS_FILE = Path("requirements.txt")


def _read_env_file(path: Path) -> Dict[str, str]:
    contents = path.read_text(encoding="utf-8")
    env_data: Dict[str, str] = {}
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_data[key.strip()] = value.strip().strip('"').strip("'")
    return env_data


def _ensure_env_vars() -> None:
    env_values: Dict[str, str] = {}
    if ENV_FILE.exists():
        env_values = _read_env_file(ENV_FILE)
        for key, value in env_values.items():
            os.environ.setdefault(key, value)
    else:
        print(f"Warning: {ENV_FILE} not found. Relying on existing environment variables.")

    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + f". Create {ENV_FILE} or export them before running."
        )

    if not os.environ.get("SLACK_APP_TOKEN") and not os.environ.get("SLACK_SIGNING_SECRET"):
        raise RuntimeError(
            "Either SLACK_APP_TOKEN (Socket Mode) or SLACK_SIGNING_SECRET (HTTP events) must be set."
        )


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _ensure_venv() -> None:
    if _venv_python().exists():
        return
    print(f"Creating virtual environment at {VENV_DIR.resolve()}")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])


def _pip_install_requirements() -> None:
    python_path = _venv_python()
    if not python_path.exists():
        raise RuntimeError("Virtual environment Python executable not found")

    print("Upgrading pip inside the slack_adder_env virtual environment")
    subprocess.check_call([str(python_path), "-m", "pip", "install", "--upgrade", "pip"])

    if not REQUIREMENTS_FILE.exists():
        raise RuntimeError(
            f"Requirements file '{REQUIREMENTS_FILE}' not found. Create it before running the bot."
        )

    print(f"Installing required packages from {REQUIREMENTS_FILE} into slack_adder_env")
    subprocess.check_call([str(python_path), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])


def _run_bot(args: Iterable[str]) -> int:
    python_path = _venv_python()
    command = [str(python_path), "bot.py", *args]
    print("Running bot with:", " ".join(command))
    return subprocess.call(command)


def main(argv: list[str]) -> int:
    _ensure_env_vars()
    _ensure_venv()
    _pip_install_requirements()
    return _run_bot(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
