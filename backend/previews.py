"""Register actual tool artifacts and computer captures; never accept arbitrary URLs/paths from the UI."""
import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote

TEXT = {'.txt', '.md', '.csv', '.json', '.log', '.py', '.js', '.ts', '.tsx', '.jsx', '.css', '.xml', '.yaml', '.yml'}
PREVIEW = TEXT | {'.html', '.htm', '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.mp3', '.wav', '.ogg', '.mp4', '.webm', '.docx', '.xlsx', '.pptx', '.zip'}
SKIP = {'.venv', '.git', 'node_modules', '__pycache__', 'vendor', 'runtime', 'backend', 'desktop', 'dist', 'docs', '.hermes', '.playwright-mcp'}


class Previews:
    def __init__(self, root, gateway):
        self.root, self.gateway = root, gateway
        self.files, self.signatures = {}, {}
        self.queue = asyncio.Queue(maxsize=100)
        self.task = None
        self.capture_dir = root / 'runtime/artifacts'
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = root / 'runtime/artifacts.json'
        if self.manifest.exists():
            try:
                for entry in json.loads(self.manifest.read_text()):
                    if Path(entry['path']).is_file():
                        self.files[entry['id']] = entry
            except (ValueError, KeyError, OSError):
                pass

    def scan(self):
        found = {}
        for folder, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('.')]
            for name in files:
                path = Path(folder) / name
                if path.suffix.lower() not in PREVIEW or name.startswith('.'):
                    continue
                try:
                    stat = path.stat()
                    found[str(path)] = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    pass
        return found

    async def start(self):
        self.signatures = await asyncio.to_thread(self.scan)
        self.gateway.observers.append(self.enqueue)
        self.task = asyncio.create_task(self.run())

    def enqueue(self, event):
        if event['type'] in {'tool.complete', 'message.complete'} and not self.queue.full():
            self.queue.put_nowait(event)

    def public(self, entry):
        if Path(entry['name']).suffix.lower() in {'.html', '.htm'}:
            entry.setdefault('preview_token', secrets.token_urlsafe(24))
        data = {key: value for key, value in entry.items() if key not in {'path', 'preview_token'}}
        if entry.get('preview_token'):
            data['preview_url'] = '/preview/' + entry['preview_token'] + '/' + quote(entry['name'])
        return data

    async def register(self, path, kind='artifact', manual=False):
        try:
            path = Path(path).expanduser().resolve()
            if not path.is_file() or (not manual and path.suffix.lower() not in PREVIEW):
                return
            # Never surface credentials, private app databases or hidden configuration.
            if not manual and (any(p.startswith('.') for p in path.parts) or path.name.lower() in {'config.yaml', 'auth.json', 'credentials.json', 'package-lock.json'}):
                return
            if not manual and any(p in {'.venv', 'node_modules', '.git', 'browser'} for p in path.parts):
                return
            stat = path.stat()
            identity = hashlib.sha256(str(path).encode()).hexdigest()[:24]
            previous = self.files.get(identity)
            if previous and previous.get('modified') == stat.st_mtime_ns:
                if manual and previous.get('kind') != kind:
                    previous['kind'] = kind
                    self.manifest.write_text(json.dumps(list(self.files.values())), encoding='utf-8')
                return self.public(previous)
            entry = {'id': identity, 'name': path.name, 'path': str(path), 'kind': kind,
                     'media_type': mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
                     'text': path.suffix.lower() in TEXT, 'size': stat.st_size, 'modified': stat.st_mtime_ns}
            if path.suffix.lower() in {'.html', '.htm'}:
                entry['preview_token'] = (previous or {}).get('preview_token') or secrets.token_urlsafe(24)
            self.files[identity] = entry
            # A bounded local registry survives application restarts.
            manual_files = {key: value for key, value in self.files.items() if value.get('kind') == 'workspace'}
            automatic_files = [(key, value) for key, value in self.files.items() if value.get('kind') != 'workspace'][-150:]
            self.files = {**manual_files, **dict(automatic_files)}
            self.manifest.write_text(json.dumps(list(self.files.values())), encoding='utf-8')
            await self.gateway.publish('artifact.available', self.public(entry))
            return self.public(entry)
        except (OSError, ValueError):
            pass

    async def inspect(self, value, kind, depth=0):
        if depth > 12:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {'api_key', 'token', 'password', 'secret', 'system_prompt'}:
                    continue
                await self.inspect(item, kind, depth + 1)
        elif isinstance(value, list):
            for item in value[:100]:
                await self.inspect(item, kind, depth + 1)
        elif isinstance(value, str):
            if kind == 'computer' and value.startswith('data:image/') and ';base64,' in value:
                header, data = value.split(',', 1)
                if len(data) > 24 * 1024 * 1024:
                    return
                try:
                    raw = base64.b64decode(data, validate=True)
                    extension = '.jpg' if 'jpeg' in header else '.png'
                    target = self.capture_dir / ('computer-' + hashlib.sha256(raw).hexdigest()[:16] + extension)
                    target.write_bytes(raw)
                    await self.register(target, kind)
                except (ValueError, OSError):
                    pass
                return
            if len(value) > 100000:
                return
            if value.startswith(('{', '[')):
                try:
                    await self.inspect(json.loads(value), kind, depth + 1)
                    return
                except ValueError:
                    pass
            candidates = [value.strip().strip('`"')]
            candidates += re.findall(r'\]\(([^)]+)\)', value)
            candidates += re.findall(r'`([^`\n]+\.[a-zA-Z0-9]{1,6})`', value)
            candidates += re.findall(r'[A-Za-z]:[\\/][^\r\n"<>|]+?\.(?:html?|pdf|png|jpe?g|svg|webp|docx|xlsx|pptx|txt|csv|md)(?=[\s"\)\]]|$)', value)
            for candidate in candidates[:30]:
                if '\n' in candidate or len(candidate) > 1024 or '://' in candidate:
                    continue
                path = Path(candidate)
                if not path.is_absolute():
                    path = self.root / path
                await self.register(path, kind)

    async def run(self):
        while True:
            event = await self.queue.get()
            try:
                payload = event['payload']
                kind = 'computer' if 'computer' in str(payload.get('name', '')).lower() else 'artifact'
                await self.inspect(payload, kind)
                current = await asyncio.to_thread(self.scan)
                for path, signature in current.items():
                    if self.signatures.get(path) != signature:
                        await self.register(path)
                self.signatures = current
            except Exception as exc:
                await self.gateway.publish('preview.error', {'text': str(exc)})

    async def close(self):
        if self.task:
            self.task.cancel()
