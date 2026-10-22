"""Windows-friendly Python entry point for Vision's PowerShell setup."""

from pathlib import Path
import subprocess
import sys


def main() -> int:
    script = Path(__file__).with_name("setup.ps1")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        cwd=script.parent,
        check=False,
    )
    if sys.stdin.isatty():
        input("Press Enter to close this window...")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
