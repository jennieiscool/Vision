# Vision

Vision is a Windows desktop interface for Hermes Agent. The repository contains Vision's desktop shell, local bridge, interface, and document tools. Setup downloads the official Hermes Agent runtime and the speech models into ignored folders on your computer; no provider credentials, conversations, logs, or model weights are included in this repository.

## Quick start

1. Install Node.js 24 LTS on Windows 10 or 11.
2. Download or clone this repository.
3. Double-click `Setup.cmd`. It installs Hermes Agent under `runtime/hermes`, installs Vision's Python and Electron dependencies, and downloads the speech assets.
4. Double-click `Launch Vision.cmd`.
5. In Vision, choose a cloud provider and sign in through Hermes. Vision does not choose a provider, include API keys, install Ollama, or download a local chat model.

You can also run `python setup.py` from a terminal if Python 3.11–3.13 is installed. If PowerShell blocks the script, use the included command file; it starts PowerShell with a process-only execution-policy override.

The first setup needs an internet connection and downloads several hundred megabytes. Keep this repository in a writable folder because generated environments and user state live under `runtime/` and `.venv/`.

## Voice models

Vision uses Kokoro-82M for speech synthesis through `kokoro-onnx` and Faster Whisper `base` for local speech recognition. The setup downloads `kokoro-v1.0.onnx` (about 326 MB) and `voices-v1.0.bin` (about 28 MB) from the [Kokoro ONNX model release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0), then stores them under the ignored `runtime/` directory. Faster Whisper downloads its `base` recognition model into `runtime/whisper/` during setup.

The configured voice combines British English `bm_george` at 65% and `bm_fable` at 35%, with speech speed around 0.93× and restrained audio processing. The ONNX conversion project is MIT licensed; the Kokoro-82M model is Apache-2.0. See [third-party notices](THIRD_PARTY_NOTICES.md) and the upstream model pages for their current terms.

## Data and credentials

The public source does not include `runtime/`, `.venv/`, `node_modules/`, downloaded model files, local databases, app profiles, conversation history, browser profiles, uploads, logs, environment files, or the private planning notes. The setup and launch scripts put generated state under the ignored runtime folder. Cloud credentials are entered by each user through Hermes and are not stored in frontend source.

Vision runs its local bridge on `127.0.0.1`. Hermes, speech recognition, speech synthesis, the browser, and terminal tools run on the user's computer. Cloud model requests go to the provider the user selects in Hermes and may incur that provider's charges.

## Development

The supported interface is the Windows desktop app. `setup.ps1` installs the dependencies; `launch-desktop.ps1` launches Electron. `launch.ps1` is the browser-based development launcher. Backend dependencies are listed in `backend/requirements.txt`; desktop dependencies are pinned in `desktop/package-lock.json`.

Vision source currently has no separate license file. Hermes Agent is an independent MIT-licensed upstream project, downloaded at setup time. Its trademarks, source, licenses, and service terms remain those of their owners.

## Upstream projects

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) and its [Windows installation instructions](https://hermes-agent.nousresearch.com/docs/getting-started/installation)
- [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) and [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
- [Electron](https://www.electronjs.org/)
