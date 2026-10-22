"""Clear only an invalid selected Ollama provider; preserve provider definitions."""
import os
import re
import shutil
from pathlib import Path

home = Path(os.environ["LOCALAPPDATA"]) / "hermes"
path = home / "config.yaml"
text = path.read_text(encoding="utf-8")
match = re.search(r"^model:\s*\n(?:(?:[ \t]+.*|\s*)\n)*", text, re.M)
block = match.group(0) if match else ""
provider = re.search(r"^  provider:\s*(.+)$", block, re.M)
if provider and "ollama" in provider.group(1).lower():
    backup = home / "config.before-vision-cloud.yaml"
    if not backup.exists():
        shutil.copy2(path, backup)
    updated = re.sub(r"^  provider:.*$", "  provider: auto", block, flags=re.M)
    updated = re.sub(r"^  default:.*$", '  default: ""', updated, flags=re.M)
    updated = re.sub(r"^  base_url:.*(?:127\.0\.0\.1|localhost).*$\n?", "", updated, flags=re.M)
    path.write_text(text[:match.start()] + updated + text[match.end():], encoding="utf-8")
    print("Cleared the stale selected provider. Provider definitions and credentials preserved.")
else:
    print("No stale selected Ollama provider to clear.")
