"""One persistent Vision conversation over Hermes's official stdio JSON-RPC."""
import asyncio
import json
import os
import time
from collections import deque
from pathlib import Path
from .conversations import Conversations


class HermesGateway:
    def __init__(self, root: Path, config: dict):
        self.root, self.config = root, config
        self.process = None
        self.pending = {}
        self.clients = set()
        self.logs = deque(maxlen=350)
        self.requests = []
        self.session = None
        self.conversations = Conversations(self)
        self.busy = False
        self.stream = ""
        self.counter = 0
        self.ready = asyncio.Event()
        self.lock = asyncio.Lock()
        self.tasks = []
        self.observers = []
        self.computer_process = None
        self.turns_path = root / 'runtime/attachment-turns.json'
        self.attachment_turns = json.loads(self.turns_path.read_text()) if self.turns_path.exists() else []

    async def publish(self, kind, payload):
        event = {"type": kind, "payload": payload, "time": time.time()}
        for observer in self.observers:
            observer(event)
        if kind not in {"message.delta", "browser.frame", "reasoning.delta", "thinking.delta", "session.info"}:
            # Keep binary captures out of reconnect history; preview registration receives the original.
            def compact(value):
                if isinstance(value, str) and (value.startswith('data:image/') or len(value) > 30000):
                    return '[Large tool content available in workspace preview]'
                if isinstance(value, dict):
                    return {k: compact(v) for k, v in value.items() if not any(s in k.lower() for s in ('password', 'api_key', 'token', 'secret', 'system_prompt'))}
                if isinstance(value, list):
                    return [compact(v) for v in value]
                return value
            self.logs.append({**event, 'payload': compact(payload)})
        for queue in tuple(self.clients):
            if queue.full():
                self.clients.discard(queue)
                continue
            queue.put_nowait(event)

    @property
    def state_path(self):
        profile = self.config.get("profile", "default")
        return self.root / ("runtime/session.json" if profile == "default" else f"runtime/session-{profile}.json")

    async def start(self):
        self.conversations.active = 'main'
        hermes = Path(self.config["hermes_path"])
        python = hermes / "venv/Scripts/python.exe"
        if not python.is_file():
            raise RuntimeError(f"Vision engine interpreter missing: {python}")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        env["VISION_APP_BRIDGE_TOKEN"] = getattr(self, "app_bridge_token", "")
        env["HERMES_HOME"] = str(Path(self.config.get("hermes_home") or hermes.parent))
        env['PYTHONPATH'] = str(self.root) + os.pathsep + env.get('PYTHONPATH', '')
        env["BROWSER_CDP_URL"] = "http://127.0.0.1:9227"
        # Desktop processes can retain an older PATH after a per-user driver install.
        driver = self.root / 'runtime/computer-driver/cua-driver.exe'
        if not driver.is_file():
            driver = Path(os.environ['LOCALAPPDATA']) / 'Programs/Cua/cua-driver/bin/cua-driver.exe'
        if driver.is_file() and not env.get('HERMES_CUA_DRIVER_CMD'):
            env['HERMES_CUA_DRIVER_CMD'] = str(driver)
        env.setdefault('CUA_DRIVER_RS_TELEMETRY_ENABLED', '0')
        env.setdefault('CUA_TELEMETRY_ENABLED', '0')
        if driver.is_file():
            # Start the driver only with Vision; no logon task or elevation bypass.
            # If an existing daemon owns the endpoint, this invocation exits normally.
            with (self.root / 'runtime/computer-driver.log').open('ab') as output:
                self.computer_process = await asyncio.create_subprocess_exec(
                    str(driver), 'serve', env=env, stdin=asyncio.subprocess.DEVNULL,
                    stdout=output, stderr=output, creationflags=0x08000000 if os.name == 'nt' else 0,
                )
        self.process = await asyncio.create_subprocess_exec(
            str(python), "-u", "-m", "backend.native_gateway", cwd=str(hermes), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, creationflags=0x08000000 if os.name == "nt" else 0,
            limit=8 * 1024 * 1024,
        )
        self.tasks = [asyncio.create_task(self.read_stdout()), asyncio.create_task(self.read_stderr())]
        await asyncio.wait_for(self.ready.wait(), 90)
        state = self.state_path
        previous = json.loads(state.read_text()) if state.exists() else {}
        if previous.get("stored_session_id"):
            try:
                self.session = await self.call("session.resume", {"session_id": previous["stored_session_id"], "cwd": str(self.root), "lazy": True})
            except RuntimeError as exc:
                if "session not found" not in str(exc):
                    raise
        if not self.session and self.config.get("model") and self.config.get("provider"):
            self.session = await self.call("session.create", {
                "title": "Vision", "cwd": str(self.root), "model": self.config["model"],
                "provider": self.config["provider"], "source": "web", "cols": 120,
            })
        stored = (self.session or {}).get("stored_session_id") or previous.get("stored_session_id")
        if stored:
            state.write_text(json.dumps({"stored_session_id": stored}), encoding="utf-8")
        self.conversations.record()
        await self.publish("bridge.ready", {"model": self.config.get("model"), "session_id": (self.session or {}).get("session_id")})

    async def read_stdout(self):
        try:
            while raw := await self.process.stdout.readline():
                try:
                    frame = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if "id" in frame and frame["id"] in self.pending:
                    future = self.pending.pop(frame["id"])
                    if not future.done():
                        if frame.get("error"):
                            future.set_exception(RuntimeError(frame["error"].get("message", "Vision engine request failed")))
                        else:
                            future.set_result(frame.get("result", {}))
                    continue
                if frame.get("method") != "event":
                    continue
                event = frame.get("params", {})
                kind, payload = event.get("type", "hermes.event"), event.get("payload") or {}
                if kind == "gateway.ready":
                    self.ready.set()
                # Subagent events remain in logs, but cannot overwrite the main chat.
                sid = event.get("session_id")
                main = not sid or not self.session or sid == self.session.get("session_id")
                if kind == "session.info" and main and self.session:
                    stored = payload.get("stored_session_id")
                    if stored:
                        self.session["stored_session_id"] = stored
                        self.conversations.record()
                    selected_provider = str(payload.get("provider") or "")
                    selected_model = str(payload.get("model") or "")
                    if selected_model and not selected_model.startswith("vision-qwen") and "ollama" not in selected_provider.lower():
                        self.config["model"] = payload["model"]
                        if payload.get("provider"):
                            self.config["provider"] = payload["provider"]
                        (self.root / "runtime/config.json").write_text(json.dumps(self.config, indent=2), encoding="utf-8")
                if kind == "message.delta" and main:
                    self.stream += payload.get("text", "")
                if kind == "message.complete" and main:
                    self.busy = False
                    self.stream = ""
                if kind.endswith(".request") and main:
                    self.requests.append({"type": kind, "payload": payload})
                if not main and kind.startswith("message."):
                    kind = "subagent." + kind
                await self.publish(kind, payload)
        finally:
            self.ready.clear()
            self.busy = False
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError("Vision engine disconnected"))
            self.pending.clear()
            await self.publish("bridge.error", {"text": "Vision engine exited. Restart Vision to reconnect."})

    async def read_stderr(self):
        while raw := await self.process.stderr.readline():
            line = raw.decode("utf-8", "replace").strip()
            if line:
                await self.publish("gateway.log", {"text": line})

    async def call(self, method, params=None, timeout=180):
        if not self.process or self.process.returncode is not None:
            raise RuntimeError("Vision engine is not running")
        self.counter += 1
        rid = f"vision-{self.counter}"
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}) + "\n").encode())
        await self.process.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(rid, None)

    async def submit(self, text, display=None, queued=False, attachments=None):
        async with self.lock:
            if self.busy and not queued:
                raise RuntimeError("Vision is working. Stop the current task before sending another.")
            if not self.session:
                raise RuntimeError("Vision is still starting")
            self.busy = True
            self.stream = ""
            attached_images = []
            original_text = text
            try:
                context = self.workspace_context.prepare(self.session) if hasattr(self, "workspace_context") else {"text": "", "attachments": []}
                text += context["text"]
                attachments = list(attachments or []) + [file for file in context["attachments"] if file["path"] not in {f["path"] for f in attachments or []}]
                refs = []
                for file in attachments or []:
                    method = 'image.attach' if Path(file['path']).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'} else 'file.attach'
                    try:
                        result = await self.call(method, {'session_id': self.session['session_id'], 'path': '"' + file['path'] + '"' if method == 'image.attach' else file['path']})
                    except RuntimeError:
                        if not file.get('workspace'):
                            raise
                        context['keys'] = [key for key in context['keys'] if not key.startswith(file['id'] + ':')]
                        await self.publish('workspace.notice', {'text': file['name'] + ' is available by file path, but the current model could not attach it as an image.'})
                        continue
                    if method == 'image.attach':
                        attached_images.append(result['path'])
                    if result.get('ref_text'):
                        refs.append(result['ref_text'])
                visible = display if display is not None else original_text
                public_files = [{k: v for k, v in f.items() if k != 'path'} for f in attachments or []]
                await self.publish("user.message", {"text": visible, "attachments": public_files})
                if refs:
                    text += '\n\n' + '\n'.join(refs)
                result = await self.call("prompt.submit", {"session_id": self.session["session_id"], "text": text, "queued": queued})
                if context["text"]:
                    self.workspace_context.acknowledge(context)
                if public_files or context["text"]:
                    self.attachment_turns.append({'session': self.session.get('stored_session_id') or self.session['session_id'], 'text': text, 'display': visible, 'attachments': public_files})
                    self.attachment_turns = self.attachment_turns[-500:]
                    self.turns_path.write_text(json.dumps(self.attachment_turns), encoding='utf-8')
                return result
            except Exception:
                self.busy = False
                for path in attached_images:
                    try:
                        await self.call('image.detach', {'session_id': self.session['session_id'], 'path': path})
                    except RuntimeError:
                        pass
                raise

    async def close(self):
        if self.computer_process and self.computer_process.returncode is None:
            self.computer_process.terminate()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.ready.clear()
        self.session = None
        self.busy = False
        self.requests.clear()
        self.logs.clear()
