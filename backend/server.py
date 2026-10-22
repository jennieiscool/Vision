"""Vision local application. Bind to loopback; never expose the terminal publicly."""
import asyncio
import base64
import contextlib
import json
import os
import mimetypes
import re
import secrets
import tempfile
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .browser import Browser
from .gateway import HermesGateway
from .voice import Voice
from .previews import Previews
from .settings import install_settings
from .desktop_settings import install_desktop_settings
from .workspace_files import install_workspace_files
from .workspace_context import WorkspaceContext
from .workspace_projects import install_workspace_projects
from .application_library import install_application_library
from .app_control import install_app_control
from .document_editors import install_document_editors
from .conversations import install_conversations

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
RUNTIME.mkdir(exist_ok=True)
CONFIG_PATH = RUNTIME / "config.json"
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path(os.environ["LOCALAPPDATA"]) / "hermes")
CONFIG = {
    "hermes_path": str(HERMES_HOME / "hermes-agent"),
    "provider": "", "model": "", "cloud_first": True,
}
if CONFIG_PATH.exists():
    CONFIG.update(json.loads(CONFIG_PATH.read_text()))
else:
    CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2))
if CONFIG.get("model", "").startswith("vision-qwen") or CONFIG.get("provider", "").startswith("ollama"):
    CONFIG.update(provider="", model="", cloud_first=True)
    CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2))
TOKEN = secrets.token_urlsafe(32)
if os.environ.get("HERMES_HOME"):
    CONFIG['hermes_path'] = str(HERMES_HOME / "hermes-agent")
    CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2))
elif (RUNTIME / 'hermes/hermes-agent').is_dir():
    CONFIG['hermes_path'] = str(RUNTIME / 'hermes/hermes-agent')
    CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2))
os.environ['PATH'] = os.pathsep.join(str(p) for p in [RUNTIME / 'node', RUNTIME / 'ffmpeg', RUNTIME / 'computer-driver']) + os.pathsep + os.environ.get('PATH', '')
gateway = HermesGateway(ROOT, CONFIG)
gateway.app_bridge_token = TOKEN
browser = Browser(ROOT, gateway)
voice = Voice(ROOT)
previews = Previews(ROOT, gateway)
workspace_context = WorkspaceContext(ROOT, CONFIG, previews, gateway)
gateway.workspace_context = workspace_context
UPLOADS = RUNTIME / 'uploads'
UPLOADS.mkdir(exist_ok=True)
UPLOAD_MANIFEST = RUNTIME / 'uploads.json'
uploads = json.loads(UPLOAD_MANIFEST.read_text()) if UPLOAD_MANIFEST.exists() else {}
startup_error = None
PORT = 8787
ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
terminal_slots = asyncio.Semaphore(8)
model_terminal_lock = asyncio.Lock()


async def start_services():
    global startup_error
    app.state.desktop_task = asyncio.create_task(app.state.desktop_start())
    try:
        install_vision_prompt()
        await previews.start()
        try:
            await browser.start()
        except Exception as exc:
            await gateway.publish("browser.error", {"text": str(exc)})
        await gateway.start()
        if CONFIG.get("model") and gateway.session:
            await gateway.call("config.set", {"session_id": gateway.session["session_id"], "key": "model", "value": CONFIG["model"] + " --provider " + CONFIG["provider"]})
    except Exception as exc:
        startup_error = str(exc)
        await gateway.publish("bridge.error", {"text": startup_error})


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(start_services())
    yield
    task.cancel()
    if getattr(app.state, "desktop_task", None):
        app.state.desktop_task.cancel()
    if getattr(app.state, "detach_applications", None):
        await asyncio.to_thread(app.state.detach_applications)
    await gateway.close()
    await browser.close()
    await previews.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def local_access(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        if not (secrets.compare_digest(request.cookies.get("vision_session", ""), TOKEN) or (request.url.path.startswith("/api/app-control/agent/") and secrets.compare_digest(request.headers.get("x-vision-agent", ""), TOKEN))):
            return JSONResponse({"detail": "Open Vision locally to connect."}, status_code=401)
        if getattr(app.state, "vision_locked", False) and not request.url.path.startswith(("/api/desktop/security", "/api/app-control/desktop/", "/api/app-control/desktop-detach-all")):
            return JSONResponse({"detail": "Unlock Vision to continue."}, status_code=423)
        origin = request.headers.get("origin")
        if origin and origin not in ORIGINS:
            return JSONResponse({"detail": "Origin denied"}, status_code=403)
        if request.method not in {"GET", "HEAD"} and origin not in ORIGINS:
            return JSONResponse({"detail": "Origin required"}, status_code=403)
    response = await call_next(request)
    if request.url.path == "/":
        response.set_cookie("vision_session", TOKEN, httponly=True, samesite="strict")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path == '/' or request.url.path.endswith(('.js', '.css')):
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return response


def connected():
    if not gateway.session or not gateway.ready.is_set():
        raise HTTPException(503, startup_error or "Vision is starting")
    return gateway.session["session_id"]


def install_vision_prompt():
    """Append Vision's identity without discarding the user's existing instructions."""
    import yaml
    config_path = Path(CONFIG.get('hermes_home') or Path(CONFIG['hermes_path']).parent) / 'config.yaml'
    original = config_path.read_text(encoding='utf-8')
    native = yaml.safe_load(original) or {}
    agent = native.setdefault('agent', {})
    existing = str(agent.get('system_prompt') or '')
    existing = re.sub(r'\n?\[Vision desktop instructions\][\s\S]*?\[/Vision desktop instructions\]', '', existing).strip()
    overlay = (ROOT / 'backend/vision-prompt.txt').read_text(encoding='utf-8').replace('{VISION_ROOT}', str(ROOT)).strip()
    prompt = existing + ('\n\n' if existing else '') + '[Vision desktop instructions]\n' + overlay + '\n[/Vision desktop instructions]'
    if agent.get('system_prompt') != prompt:
        backup = RUNTIME / 'config-before-vision-prompt.yaml'
        if not backup.exists():
            backup.write_text(original, encoding='utf-8')
        agent['system_prompt'] = prompt
        config_path.write_text(yaml.safe_dump(native, sort_keys=False, allow_unicode=True), encoding='utf-8')


async def apply_hermes_configuration():
    import yaml
    config_path = Path(CONFIG.get("hermes_home") or Path(CONFIG["hermes_path"]).parent) / "config.yaml"
    native = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    selected = native.get("model") or {}
    if isinstance(selected, str):
        selected = {"default": selected}
    name, provider = selected.get("default", ""), selected.get("provider", "")
    base_url = selected.get("base_url", "")
    provider_definition = (native.get("providers") or {}).get(provider.removeprefix("custom:"), {})
    if isinstance(provider_definition, dict) and not base_url:
        base_url = provider_definition.get("base_url", "")
    is_local = "ollama" in provider.lower() or urlsplit(base_url).hostname in {"127.0.0.1", "localhost", "::1"}
    if not name or not provider or is_local:
        return {"configured": False, "message": "Choose a cloud provider using /model. No local model will be started."}
    await gateway.call("reload.env", {})
    if not gateway.session:
        gateway.session = await gateway.call("session.create", {"title": "Vision", "cwd": str(ROOT), "model": name, "provider": provider, "source": "web"})
    else:
        await gateway.call("config.set", {"session_id": connected(), "key": "model", "value": name + " --provider " + provider})
    CONFIG.update(model=name, provider=provider)
    CONFIG_PATH.write_text(json.dumps(CONFIG, indent=2))
    stored = gateway.session.get("stored_session_id")
    if stored:
        gateway.conversations.record()
    await gateway.publish("model.changed", {"model": name, "provider": provider})
    await gateway.publish("chat.reloaded", {})
    return {"configured": True, "model": name, "provider": provider}


@app.get("/api/status")
async def status():
    return {"connected": gateway.ready.is_set(), "configured": bool(CONFIG.get("model")), "busy": gateway.busy,
            "model": CONFIG["model"], "error": startup_error,
            "voice": {"tts": "Kokoro-82M", "blend": "bm_george 65% / bm_fable 35%", "speed": .93,
                      "installed": (RUNTIME / "kokoro-v1.0.onnx").exists() and (RUNTIME / "voices-v1.0.bin").exists()}}


@app.get("/api/history")
async def history():
    selected = gateway.session
    conversation = gateway.conversations.active
    result = await gateway.call("session.history", {"session_id": connected()}) if gateway.session else {"messages": []}
    sid = (selected or {}).get('stored_session_id') or (selected or {}).get('session_id')
    turns = [t for t in gateway.attachment_turns if t['session'] == sid]
    for message in reversed(result.get('messages', [])):
        if message.get('role') != 'user':
            continue
        text = message.get('text') or message.get('content') or ''
        if not isinstance(text, str):
            continue
        for index in range(len(turns) - 1, -1, -1):
            turn = turns[index]
            if text == turn['text'] or text.startswith(turn['text']):
                message.update(text=turn['display'], attachments=turn['attachments'])
                turns.pop(index)
                break
    return {**result, "conversation": conversation, "profile": CONFIG.get('profile', 'default'), "busy": gateway.busy, "stream": gateway.stream, "requests": gateway.requests, "logs": list(gateway.logs)}


@app.post("/api/chat")
async def chat(request: Request):
    if not CONFIG.get("model"):
        raise HTTPException(409, "Use /model to configure Vision with your chosen cloud provider first.")
    connected()
    body = await request.json()
    text = str(body.get("text", "")).strip()
    ids = body.get('attachments') or []
    if not isinstance(ids, list) or len(ids) > 10 or any(not isinstance(i, str) or i not in uploads for i in ids):
        raise HTTPException(400, 'Choose up to 10 valid attachments')
    if (not text and not ids) or len(text) > 50000:
        raise HTTPException(400, "Message must contain between 1 and 50,000 characters")
    try:
        await gateway.submit(text or 'Please review the attached files.', display=text or 'Attached files', attachments=[uploads[i] for i in ids])
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"accepted": True}


@app.post('/api/attachments')
async def upload_attachment(file: UploadFile):
    connected()
    data = await file.read(20 * 1024 * 1024 + 1)
    if not data or len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Choose a non-empty file smaller than 20 MB')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(file.filename or 'attachment').name).strip(' .')[:180] or 'attachment'
    identity = secrets.token_urlsafe(18)
    directory = UPLOADS / identity
    directory.mkdir()
    path = directory / name
    path.write_bytes(data)
    media_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    if media_type.startswith('image/') and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}:
        try:
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(400, 'The image file could not be read') from exc
    entry = {'id': identity, 'path': str(path), 'name': name, 'media_type': media_type, 'size': len(data)}
    uploads[identity] = entry
    UPLOAD_MANIFEST.write_text(json.dumps(uploads), encoding='utf-8')
    return {k: v for k, v in entry.items() if k != 'path'}


@app.get('/api/attachments/{identity}')
async def attachment(identity: str):
    entry = uploads.get(identity)
    if not entry or not Path(entry['path']).is_file():
        raise HTTPException(404, 'Attachment not found')
    inline = entry['media_type'].startswith('image/') and entry['media_type'] != 'image/svg+xml'
    return FileResponse(entry['path'], media_type=entry['media_type'], filename=entry['name'],
                        content_disposition_type='inline' if inline else 'attachment',
                        headers={'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'"})


@app.get('/api/artifacts')
async def artifacts():
    closed = app.state.closed_previews()
    return {'files': [previews.public(entry) for entry in previews.files.values() if closed.get(entry['id']) != entry.get('modified')], 'dismissed': closed}


@app.post('/api/browser/control')
async def browser_control(request: Request):
    try:
        return await browser.control(await request.json())
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, 'Browser action failed: ' + str(exc)) from exc


@app.get('/api/artifacts/{identity}/file')
async def artifact_file(identity: str, download: bool = False):
    entry = previews.files.get(identity)
    if not entry or not Path(entry['path']).is_file():
        raise HTTPException(404, 'Artifact not found')
    # HTML is an isolated preview. It cannot access the parent app or its local APIs.
    headers = {'Content-Security-Policy': "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'"}
    return FileResponse(entry['path'], media_type='text/plain' if entry['text'] else entry['media_type'],
                        filename=entry['name'], content_disposition_type='attachment' if download else 'inline', headers=headers)


@app.get('/preview/{token}/{resource:path}')
async def preview_resource(token: str, resource: str):
    """Read-only artifact bundle behind an unguessable URL, with an opaque sandbox origin.

    Relative assets work without giving an artifact the application's API cookie.
    The HTML sandbox cannot read the parent; CSP confines network access to its bundle.
    """
    entry = next((f for f in previews.files.values() if secrets.compare_digest(f.get('preview_token', ''), token)), None)
    if not entry:
        raise HTTPException(404, 'Preview not found')
    base = Path(entry['path']).resolve().parent
    path = (base / resource).resolve()
    allowed = {'.html', '.htm', '.css', '.js', '.mjs', '.json', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.mp3', '.wav', '.ogg', '.mp4', '.webm'}
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise HTTPException(404, 'Resource not found') from exc
    if not path.is_file() or path.suffix.lower() not in allowed or any(p.startswith('.') or p in {'runtime', 'backend', 'desktop', 'node_modules'} for p in relative.parts) or path.name.lower() in {'auth.json', 'config.json', 'credentials.json'}:
        raise HTTPException(404, 'Resource not found')
    prefix = f'http://127.0.0.1:{PORT}/preview/{token}/'
    csp = f"sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob: {prefix}; style-src 'unsafe-inline' {prefix}; img-src data: blob: {prefix}; media-src data: blob: {prefix}; font-src data: {prefix}; connect-src {prefix}; form-action 'none'; base-uri 'none'"
    return FileResponse(path, headers={'Content-Security-Policy': csp, 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store'}, media_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')


@app.post("/api/stop")
async def stop():
    return await gateway.call("session.interrupt", {"session_id": connected()})


@app.get("/api/commands")
async def commands():
    return await gateway.call("commands.catalog", {"session_id": (gateway.session or {}).get("session_id", "")})


@app.post("/api/configuration/apply")
async def apply_configuration():
    return await apply_hermes_configuration()


async def execute_slash(command, depth=0):
    if depth > 5:
        raise HTTPException(400, "Command alias recursion limit reached")
    raw = command.lstrip("/").strip()
    if not raw:
        raise HTTPException(400, "Enter a command")
    name, _, arg = raw.partition(" ")
    if not gateway.session:
        if name == "help":
            data = await commands()
            await gateway.publish("command.output", {"text": "\n".join(f"{row[0]}  {row[1]}" for row in data.get("pairs", []))})
            return {"ok": True}
        raise HTTPException(409, "Use /model to configure Vision first. The terminal supports the complete agent CLI.")
    sid = connected()
    if name in {"new", "clear", "resume", "branch"}:
        if gateway.busy:
            raise HTTPException(409, "Stop the current task before changing the main conversation")
        if name == "resume" and not arg.strip():
            result = await gateway.call("session.list", {})
            await gateway.publish("command.output", {"text": json.dumps(result, indent=2) + "\nUse /resume <session ID or name> to load one into the main chat."})
            return result
        if name == "branch":
            result = await gateway.call("session.branch", {"session_id": sid, "title": arg.strip()})
        elif name == "resume":
            result = await gateway.call("session.resume", {"session_id": arg.strip(), "cwd": str(ROOT)})
        else:
            result = await gateway.call("session.create", {"title": arg.strip() or "Vision", "cwd": str(ROOT), "model": CONFIG["model"], "provider": CONFIG["provider"], "source": "web"})
        gateway.session = result
        if result.get("stored_session_id"):
            gateway.conversations.record()
        gateway.requests.clear()
        await gateway.publish("chat.reloaded", {})
        return {"updated": True}
    try:
        result = await gateway.call("slash.exec", {"session_id": sid, "command": raw})
    except RuntimeError:
        name, _, arg = raw.partition(" ")
        result = await gateway.call("command.dispatch", {"session_id": sid, "name": name, "arg": arg.strip()})
    kind = result.get("type")
    if kind == "alias":
        _, _, arg = raw.partition(" ")
        return await execute_slash("/" + result["target"] + (" " + arg if arg else ""), depth + 1)
    if kind in {"skill", "send"}:
        if result.get("notice"):
            await gateway.publish("command.output", {"text": result["notice"]})
        await gateway.submit(result.get("message", ""), display=result.get("display", command), queued=name in {"queue", "q"})
    else:
        await gateway.publish("command.output", {"text": result.get("output", ""), "warning": result.get("warning", "")})
    return result


@app.post("/api/command")
async def command(request: Request):
    raw = str((await request.json()).get("command", ""))
    if not raw.startswith("/") or len(raw) > 20000:
        raise HTTPException(400, "Enter a slash command")
    try:
        return await execute_slash(raw)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/respond")
async def respond(request: Request):
    body = await request.json()
    method = body.get("method")
    if method not in {"approval.respond", "clarify.respond", "sudo.respond", "secret.respond"}:
        raise HTTPException(400, "Unsupported response")
    params = {**body.get("params", {}), "session_id": connected()}
    result = await gateway.call(method, params)
    if gateway.requests:
        gateway.requests.pop(0)
    await gateway.publish("request.resolved", {"method": method})
    return result


@app.get("/api/models")
async def models():
    return {"current": CONFIG.get("model", ""), "provider": CONFIG.get("provider", "")}


@app.post("/api/voice/speak")
async def speak(request: Request):
    body = await request.json()
    text = str(body.get("text", ""))
    with_timing = bool(body.get('timings'))
    if not text or len(text) > 6000:
        raise HTTPException(400, "Speech must contain between 1 and 6,000 characters")
    try:
        data = await asyncio.to_thread(voice.speak, text, with_timing)
    except Exception as exc:
        await gateway.publish("voice.error", {"text": str(exc)})
        raise HTTPException(503, "Local voice synthesis failed. See the logs.") from exc
    if with_timing:
        return {'audio': base64.b64encode(data['audio']).decode('ascii'), 'words': data['words'], 'duration': data['duration'], 'silent': data.get('silent', False)}
    if not data:
        return Response(status_code=204)
    return Response(data, media_type="audio/wav")


@app.post("/api/voice/transcribe")
async def transcribe(audio: UploadFile):
    data = await audio.read(12 * 1024 * 1024 + 1)
    if not data or len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "Audio recording is empty or exceeds 12 MB")
    path = None
    try:
        suffix = ".wav" if audio.content_type == "audio/wav" else ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, dir=RUNTIME, delete=False) as handle:
            path = Path(handle.name)
            handle.write(data)
        text = await asyncio.to_thread(voice.transcribe, path)
        await gateway.publish("voice.transcribed", {"recognized": bool(text), "characters": len(text)})
        return {"text": text}
    except Exception as exc:
        await gateway.publish("voice.error", {"text": "Transcription failed: " + str(exc)})
        raise HTTPException(503, "Local speech recognition failed. See Activity.") from exc
    finally:
        if path:
            path.unlink(missing_ok=True)


async def authorize_ws(ws):
    if getattr(app.state, "vision_locked", False):
        await ws.close(code=4423)
        return False
    if ws.headers.get("origin") not in ORIGINS or not secrets.compare_digest(ws.cookies.get("vision_session", ""), TOKEN):
        await ws.close(code=4403)
        return False
    await ws.accept()
    app.state.open_sockets.add(ws)
    return True


@app.websocket("/api/events")
async def events(ws: WebSocket):
    if not await authorize_ws(ws):
        return
    queue = asyncio.Queue(maxsize=1000)
    gateway.clients.add(queue)
    try:
        await ws.send_json({"type": "bridge.status", "payload": await status()})
        if browser.latest:
            await ws.send_json({"type": "browser.state", "payload": browser.latest})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), 20)
            except asyncio.TimeoutError:
                event = {"type": "heartbeat", "payload": {}}
            await ws.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        gateway.clients.discard(queue)


@app.websocket('/api/browser/stream')
async def browser_stream(ws: WebSocket):
    if not await authorize_ws(ws):
        return
    queue = asyncio.Queue(maxsize=1)
    browser.stream_clients.add(queue)
    if browser.latest_frame:
        queue.put_nowait(browser.latest_frame)

    async def output():
        previous = None
        while True:
            packet = await queue.get()
            metadata = {key: value for key, value in packet.items() if key != 'image'}
            if metadata != previous:
                await ws.send_json(metadata)
                previous = metadata
            await ws.send_bytes(packet['image'])

    async def disconnected():
        while True:
            if (await ws.receive())['type'] == 'websocket.disconnect':
                return

    tasks = [asyncio.create_task(output()), asyncio.create_task(disconnected())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        browser.stream_clients.discard(queue)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@app.websocket("/api/terminal")
async def terminal(ws: WebSocket):
    if not await authorize_ws(ws):
        return
    if terminal_slots.locked():
        await ws.send_text("\r\nEight terminals are already open. Close a terminal tab to start another.\r\n")
        await ws.close(code=4409)
        return
    async with terminal_slots:
        from winpty import PtyProcess
        env = dict(os.environ)
        env["PATH"] = str(Path(CONFIG["hermes_path"]) / "venv/Scripts") + os.pathsep + env.get("PATH", "")
        env["HERMES_HOME"] = str(Path(CONFIG.get("hermes_home") or Path(CONFIG["hermes_path"]).parent))
        mode = ws.query_params.get("mode", "shell")
        if mode == 'model':
            if model_terminal_lock.locked():
                await ws.send_text('\r\nModel setup is already open in another terminal.\r\n')
                await ws.close(code=4409)
                return
            await model_terminal_lock.acquire()
        shell = os.environ.get("COMSPEC", "C:/Windows/System32/cmd.exe")
        if mode == "model":
            shell = [str(Path(CONFIG["hermes_path"]) / "venv/Scripts/python.exe"), "-m", "hermes_cli.main", "model"]
        try:
            process = await asyncio.to_thread(PtyProcess.spawn, shell, cwd=str(ROOT), env=env, dimensions=(24, 120))
        except Exception as exc:
            if mode == 'model':
                model_terminal_lock.release()
            await ws.send_text("\r\nCould not start the terminal: " + str(exc) + "\r\n")
            await ws.close(code=1011)
            return
        await gateway.publish("terminal.open", {"text": "Interactive local terminal opened"})

        async def output():
            while process.isalive():
                try:
                    data = await asyncio.to_thread(process.read, 4096)
                    if data:
                        await ws.send_text(data)
                except (EOFError, OSError):
                    return

        async def input_data():
            while True:
                message = await ws.receive_json()
                if message.get("type") == "resize":
                    rows = max(4, min(200, int(message.get("rows", 24))))
                    cols = max(20, min(500, int(message.get("cols", 120))))
                    await asyncio.to_thread(process.setwinsize, rows, cols)
                elif message.get("type") == "input":
                    await asyncio.to_thread(process.write, str(message.get("data", ""))[:16384])
        tasks = [asyncio.create_task(output()), asyncio.create_task(input_data())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.to_thread(process.close, True)
            await gateway.publish("terminal.close", {"text": "Interactive terminal closed"})
            if mode == "model":
                try:
                    result = await apply_hermes_configuration()
                    if not result.get("configured"):
                        await gateway.publish("command.output", {"text": result["message"]})
                except Exception as exc:
                    await gateway.publish("bridge.error", {"text": str(exc)})
                finally:
                    model_terminal_lock.release()
            with contextlib.suppress(Exception):
                await ws.close()


@app.get("/")
async def index():
    return FileResponse(ROOT / "dist/index.html", headers={"Cache-Control": "no-store"})


install_settings(app, gateway, CONFIG, ROOT, connected, execute_slash, apply_hermes_configuration, install_vision_prompt)
app.state.open_sockets = weakref.WeakSet()
app.state.has_open_terminals = lambda: terminal_slots._value < 8
install_desktop_settings(app, gateway, CONFIG, ROOT, connected, apply_hermes_configuration, install_vision_prompt)

install_workspace_files(app, previews, ROOT, workspace_context)
install_workspace_projects(app, previews, ROOT, workspace_context)
install_app_control(app, ROOT, workspace_context)
install_application_library(app, ROOT, workspace_context)
install_document_editors(app, previews, ROOT, workspace_context)
install_conversations(app, gateway, connected, lambda: gateway.call('vision.prompt.reload', {'session_id': connected()}))

app.mount("/", StaticFiles(directory=ROOT / "dist"), name="frontend")
