"""Small platform boundary for paths and process options shared by Vision."""
import os
import shutil
import sys
from pathlib import Path


IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")


def hermes_python(home: Path) -> Path:
    root = home / "hermes-agent"
    candidates = ([root / "venv/Scripts/python.exe", root / ".hermes/bin/hermes"] if IS_WINDOWS else
                  [root / ".hermes/bin/hermes", root / "venv/bin/python"])
    return next((path for path in candidates if path.is_file()), candidates[0])


def hermes_command(home: Path, *args: str) -> list[str]:
    """Build a command for both current Hermes PM installs and legacy venv installs."""
    root = home / "hermes-agent"
    launcher = root / ".hermes/bin/hermes"
    if launcher.is_file():
        return [str(launcher), *args]
    python = root / ("venv/Scripts/python.exe" if IS_WINDOWS else "venv/bin/python")
    if args and args[0] == "--run-module":
        return [str(python), "-u", "-m", *args[1:]]
    return [str(python), "-u", "-m", "hermes_cli.main", *args]


def hermes_uv(home: Path) -> Path | None:
    name = "uv.exe" if IS_WINDOWS else "uv"
    candidate = home / "bin" / name
    return candidate if candidate.is_file() else Path(shutil.which(name)) if shutil.which(name) else None


def user_data_home() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def process_options(**kwargs):
    """Return subprocess options valid on the current OS."""
    if IS_WINDOWS:
        kwargs.setdefault("creationflags", 0x08000000)
    return kwargs


def hermes_home_candidates(root: Path) -> list[Path]:
    values = []
    if os.environ.get("HERMES_HOME"):
        values.append(Path(os.environ["HERMES_HOME"]).expanduser())
    values.append(root / "runtime/hermes")
    values.append(Path.home() / ("AppData/Local/hermes" if IS_WINDOWS else ".hermes"))
    result = []
    for value in values:
        normalized = value.resolve(strict=False)
        if normalized not in result:
            result.append(normalized)
    return result
