#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

fail() { printf 'Vision setup: %s\n' "$*" >&2; exit 1; }
command -v python3 >/dev/null || fail 'Install Python 3.11 or newer.'
command -v node >/dev/null || fail 'Install Node.js 24 LTS or newer.'
command -v npm >/dev/null || fail 'Install npm with Node.js.'
command -v curl >/dev/null || fail 'Install curl.'
command -v git >/dev/null || fail 'Install git.'
[[ "$(uname -m)" == x86_64 || "$(uname -m)" == aarch64 ]] || fail "Unsupported Linux architecture: $(uname -m)."

if [[ -r /etc/os-release ]]; then . /etc/os-release; else fail 'Cannot identify this Linux distribution.'; fi
if [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" != 24.04 ]]; then
  printf 'Vision currently targets Ubuntu 24.04 LTS; detected Ubuntu %s. Continuing best-effort.\n' "${VERSION_ID:-unknown}" >&2
fi
if [[ "${ID:-}" != ubuntu && "${ID_LIKE:-}" != *debian* ]]; then
  printf 'Vision setup is first-class on Ubuntu 24.04; %s is best-effort and may need system libraries installed manually.\n' "${ID:-unknown}" >&2
fi

runtime="$PWD/runtime"
mkdir -p "$runtime/whisper"

# Detect Hermes before downloading its official installer.
hermes_home=''
hermes_root=''
for candidate in "${HERMES_HOME:-}" "$runtime/hermes" "$HOME/.hermes"; do
  [[ -n "$candidate" ]] || continue
  candidate="$(realpath -m "$candidate")"
  if [[ -d "$candidate/hermes-agent" ]]; then
    [[ -x "$candidate/hermes-agent/.hermes/bin/hermes" || -x "$candidate/hermes-agent/venv/bin/python" ]] || fail "Hermes exists at $candidate/hermes-agent but its launcher is incomplete. Repair that Hermes install and rerun setup."
    hermes_home="$candidate"
    hermes_root="$candidate/hermes-agent"
    printf 'Using existing Hermes Agent at %s.\n' "$hermes_root"
    break
  fi
done

if [[ -z "$hermes_root" ]]; then
  hermes_home="$runtime/hermes"
  hermes_root="$hermes_home/hermes-agent"
  mkdir -p "$hermes_home"
  installer="$(mktemp "$runtime/hermes-install.XXXXXX.sh")"
  trap 'rm -f "$installer"' EXIT
  printf 'Downloading the official Hermes Agent Linux installer...\n'
  curl --fail --location --silent --show-error https://hermes-agent.nousresearch.com/install.sh -o "$installer"
  HERMES_HOME="$hermes_home" bash "$installer" --dir "$hermes_root" --non-interactive || true
fi
export HERMES_HOME="$hermes_home"
printf '%s' "$hermes_home" > "$runtime/hermes-home.txt"
[[ -x "$hermes_root/.hermes/bin/hermes" || -x "$hermes_root/venv/bin/python" ]] || fail "Hermes did not provide a usable Linux launcher at $hermes_root."

# Ubuntu's Electron/Chromium shared libraries and media tools. Request
# privilege only after presenting the exact missing package list.
if command -v apt-get >/dev/null && [[ "${ID:-}" == ubuntu ]]; then
  packages=(python3-venv python3-pip libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libcups2t64 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64 libgtk-3-0t64 libx11-xcb1 libxss1 libxext6 libxrender1 libfontconfig1 libfreetype6 libpango-1.0-0 libpangocairo-1.0-0 libxcb1 ffmpeg xdotool wmctrl x11-utils xprintidle xdg-desktop-portal xdg-desktop-portal-gnome)
  missing=()
  for package in "${packages[@]}"; do dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' || missing+=("$package"); done
  if ((${#missing[@]})); then
    printf 'Vision setup needs these Ubuntu packages: %s\n' "${missing[*]}"
    [[ -t 0 ]] || fail 'Run setup.sh from a terminal so sudo can request your password.'
    sudo apt-get update
    sudo apt-get install -y "${missing[@]}"
  fi
fi

vision_python="$PWD/.venv/bin/python"
if [[ ! -x "$vision_python" ]]; then python3 -m venv .venv || fail 'Could not create .venv. Install python3-venv and rerun setup.'; fi
"$vision_python" -m pip install --upgrade pip
"$vision_python" -m pip install -r backend/requirements.txt

save_asset() {
  local url="$1" destination="$2" min_bytes="$3" partial="$2.part"
  if [[ -f "$destination" && $(stat -c %s "$destination") -ge $min_bytes ]]; then return; fi
  rm -f "$partial"
  printf 'Downloading %s...\n' "$(basename "$destination")"
  curl --fail --location --retry 3 --silent --show-error "$url" -o "$partial"
  [[ $(stat -c %s "$partial") -ge $min_bytes ]] || { rm -f "$partial"; fail "Incomplete download: $destination"; }
  mv -f "$partial" "$destination"
}
voice_release='https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'
save_asset "$voice_release/kokoro-v1.0.onnx" "$runtime/kokoro-v1.0.onnx" 300000000
save_asset "$voice_release/voices-v1.0.bin" "$runtime/voices-v1.0.bin" 25000000
"$vision_python" -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8', download_root=r'$runtime/whisper')"
"$vision_python" -m playwright install chromium
npm ci --prefix desktop

mkdir -p "$HOME/.local/share/applications"
python3 - "$PWD" "$HOME/.local/share/applications/vision.desktop" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`') + '"'
entry = "[Desktop Entry]\nVersion=1.0\nType=Application\nName=Vision\nComment=Hermes desktop interface\nTerminal=false\nCategories=Utility;\nExec=" + quote(root / 'launch-vision.sh') + "\nIcon=" + quote(root / 'desktop/assets/vision.png') + "\n"
pathlib.Path(sys.argv[2]).write_text(entry, encoding='utf-8')
PY
chmod +x launch-vision.sh
printf '\nVision setup is complete. Run ./launch-vision.sh to open the desktop app.\n'
