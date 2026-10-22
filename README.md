# Vision

Vision is a desktop interface for Hermes Agent on Windows and Linux. Its local bridge, chat, speech, browser, workspace previews, terminal, and application library run on your computer. Setup reuses an existing Hermes installation or downloads Hermes from its official installer when none is found. Vision does not choose a model provider, include credentials, install Ollama, or download a local chat model.

## Linux quick start

The first-class Linux target is Ubuntu 24.04 LTS on x86_64 with a GNOME desktop. X11 is the supported session for live native application capture and AI control. Other Debian-family distributions and Wayland sessions may work with reduced application-control capability.

1. Install Node.js 24 LTS and Git.
2. Clone or download this repository and open a terminal in its folder.
3. Run `./setup.sh`. Setup checks for Hermes in `$HERMES_HOME`, `runtime/hermes`, and `~/.hermes` before downloading the official installer. It creates Vision's `.venv`, installs the desktop packages, and downloads Kokoro and Whisper speech assets. If Ubuntu packages are missing, setup lists them and uses your normal interactive `sudo` prompt.
4. Run `./launch-vision.sh` or open Vision from your desktop application menu.
5. In Vision, select a cloud provider and sign in through Hermes.

Setup requires an internet connection and downloads several hundred megabytes. Keep the repository in a writable folder; generated environments, Hermes files, models, logs, and user data stay in ignored local directories.

Linux application preview uses live window capture in the Vision grid and coordinates input with the AI through the application-control setting. On X11 this uses the window manager and Hermes's CUA driver when available. Wayland restricts cross-application window discovery and input; Vision follows the desktop's capture and input permission model and may report those capabilities as unavailable. Native package files such as `.deb` and `.rpm` are never installed by Vision. The application library supports Linux `.desktop` entries, ELF executables, and AppImages; its hash check records file identity and is not an antivirus scan or safety verdict.

## Windows quick start

1. Install Node.js 24 LTS on Windows 10 or 11.
2. Download or clone this repository.
3. Double-click `Setup.cmd`. It reuses a Hermes Agent installation it finds; only if none exists does it download Hermes from the official installer. It also installs Vision's Python and Electron dependencies and downloads speech assets.
4. Double-click `Launch Vision.cmd`.
5. In Vision, choose a cloud provider and sign in through Hermes.

You can also run `python setup.py` from a terminal if Python 3.11–3.13 is installed. If PowerShell blocks the script, use the included command file; it starts PowerShell with a process-only execution-policy override.

## Voice models

Vision uses Kokoro-82M for speech synthesis through `kokoro-onnx` and Faster Whisper `base` for local speech recognition. Setup downloads `kokoro-v1.0.onnx` (about 326 MB) and `voices-v1.0.bin` (about 28 MB) from the [Kokoro ONNX model release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0), then stores them under the ignored `runtime/` directory. Faster Whisper downloads its `base` recognition model into `runtime/whisper/` during setup.

The configured voice combines British English `bm_george` at 65% and `bm_fable` at 35%, with speech speed around 0.93× and restrained audio processing. The ONNX conversion project is MIT licensed; the Kokoro-82M model is Apache-2.0. See [third-party notices](THIRD_PARTY_NOTICES.md) and the upstream model pages for their current terms.

## Data and credentials

The repository does not include runtime environments, downloaded models, local databases, app profiles, conversation history, browser profiles, uploads, logs, environment files, or Hermes source snapshots. Cloud credentials are entered by each user through Hermes and are not stored in frontend source.

Vision runs its local bridge on `127.0.0.1`. Hermes, speech recognition, speech synthesis, the browser, and terminal tools run on the user's computer. Cloud model requests go to the provider the user selects in Hermes and may incur that provider's charges.

## Development

The Windows setup is `setup.ps1`; its desktop entry is `desktop/main.cjs`. Linux setup is `setup.sh`, and `launch-vision.sh` opens the Electron desktop app. `launch.ps1` is the browser-based development launcher. Backend dependencies are listed in `backend/requirements.txt`; desktop dependencies are pinned in `desktop/package-lock.json`.

Vision source currently has no separate license file. Hermes Agent is an independent MIT-licensed upstream project, downloaded at setup time. Its trademarks, source, licenses, and service terms remain those of their owners.

## Upstream projects

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) and its [installation instructions](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
- [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) and [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
- [Electron](https://www.electronjs.org/)
