# Vision Linux Desktop Support Design

## Intent

Make Vision installable and usable as a native desktop application on Linux while retaining the existing Windows release. Linux users should get the same core Vision experience, including Hermes chat, local speech, browser and terminal panels, settings, file previews, and a Linux-native application library with live preview and AI control.

## First supported target

- Ubuntu 24.04 LTS, x86_64, with GNOME on X11. Wayland remains best-effort while portal-based native app input and capture are completed.
- Other glibc Linux distributions may work when their package manager and desktop portal implementations meet the documented requirements; they are best-effort until explicitly listed as supported.
- Hermes is installed through its official Linux installer only when Vision cannot find a usable install. Reuse `$HERMES_HOME`, Vision's existing runtime, or the official per-user `~/.hermes` installation in that order.
- Vision does not install or execute Windows applications on Linux. Linux launch support covers installed desktop entries and user-provided native portable applications such as AppImage; package files such as `.deb` and `.rpm` are viewable/importable but are never silently installed.

## User experience

Linux gets `setup.sh` and `launch-vision.sh`, plus a desktop entry/icon. Setup checks required tools and Hermes before downloading anything, installs missing runtime assets into ignored local folders, builds the Python environment, downloads Kokoro and Whisper models from their upstream sources, and installs the Electron package for the current Linux architecture. It must explain any system packages it needs and obtain privilege through the user's distro package manager only when required.

The app keeps the existing Vision layout and core chat, voice, browser, file-preview, workspace, and terminal workflows. It uses the user's configured POSIX shell for terminal tabs. Linux system inventory is gathered from Linux interfaces and desktop metadata rather than invoking Windows PowerShell. Platform-specific actions that do not exist on Linux are shown as unavailable with a useful explanation.

The application library lists installed `.desktop` applications and accepts Linux-native portable programs. It does not elevate privileges or install packages. Before a portable binary can be launched, Vision verifies its file identity and offers the available local scanner result; it must not claim a scan proves a file is completely safe.

Applications launched from Vision should appear as a live, interactive surface in the center preview and remain ordinary native Linux processes. This release implements X11 window discovery, capture and placement. Wayland support remains best-effort; Electron and desktop portal availability varies, and this release does not promise arbitrary native-app input or capture for every compositor. Wayland does not permit arbitrary reparenting of foreign native windows. When the desktop does not expose a supported live source, Vision should report that limitation instead of showing an unrelated static screenshot or implying that control is active.

AI and human input remain coordinated through the existing application-control preference. Human takeover, idle detection, and the setting's automatic mode continue to apply. The desktop portal's own permission prompt is never skipped by the automatic mode.

## Architecture and boundaries

- Keep `desktop/main.cjs` as the Electron entry point, but use OS-aware executable, process, icon, data-directory, and shutdown helpers.
- Move platform choices behind Python adapters selected at startup: system inventory, terminal PTY, app-library scan/launch, application-window discovery/capture/input, and file operations.
- Keep shared HTTP routes and UI payloads stable where possible. An adapter reports its capabilities so unsupported capture/control features can be disabled with a direct explanation.
- Make Windows-only modules lazy imports in Windows adapter code; importing the backend on Linux must not import `ctypes.WinDLL`, `pywinpty`, Windows environment variables, or PowerShell helpers.
- Use Linux `pexpect`/PTY support in place of `pywinpty`, and gate dependencies with platform markers.
- Preserve the existing Hermes home selection behavior and add the standard Linux per-user home. Use the official `install.sh` only after all existing-install candidates have been checked.
- Keep model weights, Hermes source/runtime, credentials, app state, and logs outside Git in ignored runtime folders.

## Setup requirements

- Detect Linux architecture, distribution ID/version, package manager, XDG session type, display server, and user shell; fail early with actionable messages for unsupported architectures or missing desktop sessions.
- On Ubuntu 24.04, setup installs only missing documented system packages through `apt`. Before invoking `sudo`, show the exact package list and let the user's normal interactive privilege prompt authorize installation. Do not run package installation in a non-interactive session.
- Use the official Hermes Linux installer URL. Do not pipe an unverified redirect into a shell; download to a temporary file, run only that official installer after printing what it will do, and clean up the temporary file.
- Detect an existing Hermes checkout from `$HERMES_HOME`, `runtime/hermes`, and `~/.hermes`, and validate its Linux venv (`venv/bin/python`). Reuse a usable install and report a broken detected install rather than silently creating a second one.
- Install Vision's Python dependencies with the selected Hermes `uv` when available, otherwise the official setup's managed Python/uv tools. Use `venv/bin` paths on Linux and `venv/Scripts` paths on Windows.
- Keep model downloads resumable/validated and skip assets already present at expected sizes.
- Use npm's lockfile with `npm ci`; Electron's Linux dependencies and Chromium shared libraries must be documented for Ubuntu 24.04.

## Non-goals

- Linux support does not mean running Windows `.exe`, `.msi`, or `.lnk` files through Wine.
- Vision does not silently install `.deb`, `.rpm`, Flatpak, or Snap packages and does not claim arbitrary binaries are "100% safe".
- No arbitrary system-wide changes, root daemon, hidden privilege escalation, or disabled compositor security controls.
- Do not redesign the Vision interface or introduce Ollama/local chat model installation as part of this port.
- Other distros and desktop environments are best-effort until documented support is added.

## Acceptance criteria

- A clean Ubuntu 24.04 desktop can run setup and launch Vision without PowerShell, Windows paths, or Windows-only Python imports.
- Setup reuses a valid existing Hermes install and does not download/install a second Hermes copy; absent Hermes is installed from the official Linux source.
- Linux starts chat, browser, voice input/output, workspaces/file previews, settings, and interactive terminal tabs using Linux-native paths and processes.
- Installed Linux apps and supported portable apps can be launched into a live center preview, selected/observed/controlled through the adapter, paused for human input, and detached when Vision closes.
- X11 provides live application preview/control for supported desktop windows. Wayland permission prompts are respected, and unsupported capture/input leaves the rest of Vision usable.
- Windows setup, launch, system settings, and native app control continue through their existing adapters.
- No model weights, user data, or Hermes source snapshot are committed.

## Implementation calls

- First-class validation target is Ubuntu 24.04 LTS on x86_64; supporting every Linux distro at once is not a release criterion.
- Native apps remain native host processes. Vision owns the live preview/control adapter, not the app process's package installation or security boundary.
- If a compositor cannot provide a supported live capture/control surface, Vision reports that capability as unavailable instead of pretending an overlay is an embedded preview.
