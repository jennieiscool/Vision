"""Persistent app identity and real Defender scan results; explicit desktop launch only."""
import asyncio
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile
from .application_shortcuts import resolve_shortcut


def install_application_library(app, root, context):
    if os.name != 'nt':
        from .linux_application_library import install_linux_application_library
        return install_linux_application_library(app, root, context)
    tasks, locks = set(), {}
    scan_slots = asyncio.Semaphore(1)

    def manifest(profile):
        return root / ('runtime/app-library-' + profile + '.json')

    def load(profile):
        try:
            return json.loads(manifest(profile).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'items': []}

    def save(profile, state):
        target = manifest(profile)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temporary.replace(target)

    def public(item):
        return {k: v for k, v in item.items() if k != 'path'}

    def profile():
        return context.config.get('profile', 'default')

    def lookup(owner, identity):
        item = next((i for i in load(owner)['items'] if i['id'] == identity), None)
        if not item:
            raise HTTPException(404, 'This app is no longer in the library.')
        return item

    def update(owner, item):
        state = load(owner)
        state['items'] = [old for old in state['items'] if old['id'] != item['id']] + [item]
        save(owner, state)

    def digest(path):
        result = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                result.update(chunk)
        return result.hexdigest()

    async def scan(owner, identity):
        async with locks.setdefault((owner, identity), asyncio.Lock()), scan_slots:
            try:
                item = lookup(owner, identity)
            except HTTPException:
                return
            path = Path(item['path'])
            item.update(state='scanning', detail='Checking file identity and scanning with Microsoft Defender…')
            update(owner, item)
            process = None
            try:
                before = await asyncio.to_thread(digest, path)
                process = await asyncio.create_subprocess_exec('powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(root / 'desktop/scan-application.ps1'), env={**os.environ, 'VISION_SCAN_PATH': str(path)}, creationflags=0x08000000, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                output, error = await asyncio.wait_for(process.communicate(), 600)
                if process.returncode:
                    raise RuntimeError(error.decode('utf-8', errors='replace')[-1500:] or 'Defender could not complete this scan.')
                result = json.loads(output.decode('utf-8-sig'))
                after = await asyncio.to_thread(digest, path)
                if before != after:
                    raise RuntimeError('The file changed during its scan. Scan it again before opening.')
                item.update(result, sha256=after, size=path.stat().st_size, scan_time=time.time())
                if item.get('state') == 'clear' and item.get('signature') in {'HashMismatch', 'NotTrusted'}:
                    item.update(state='blocked', detail='Windows could not validate this application signature. Opening is blocked.')
                if item.get('state') == 'clear':
                    item['detail'] = 'Defender completed this scan without detecting a threat. This is not a guarantee of safety.'
            except asyncio.CancelledError:
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            except Exception as exc:
                if process and process.returncode is None:
                    process.kill()
                    await process.wait()
                item.update(state='unavailable', detail=str(exc) or 'The scan did not complete.')
            # Removing a library item while a scan runs must not resurrect it.
            if any(old['id'] == identity for old in load(owner)['items']):
                update(owner, item)

    def schedule(owner, identity):
        key = (owner, identity)
        if any(getattr(task, 'app_key', None) == key and not task.done() for task in tasks):
            return
        task = asyncio.create_task(scan(owner, identity))
        task.app_key = key
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def register(path):
        if path.suffix.lower() not in {'.exe', '.msi', '.lnk'}:
            raise HTTPException(415, 'Choose an .exe application, .msi installer or Windows .lnk application shortcut.')
        if not path.is_absolute() or not path.is_file():
            raise HTTPException(400, 'Choose an application file.')
        path = path.resolve()
        owner = profile()
        identity = hashlib.sha256(str(path).encode()).hexdigest()[:24]
        shortcut = await resolve_shortcut(root, path) if path.suffix.lower() == '.lnk' else {}
        item = {'id': identity, 'name': path.name, 'kind': 'application', 'path': str(path), 'size': path.stat().st_size, 'state': 'scanning', 'detail': 'Waiting for Microsoft Defender…', **shortcut}
        if shortcut:
            item['shortcut'] = True
        update(owner, item)
        schedule(owner, identity)
        await context.add({'id': item['id'], 'name': item['name'], 'path': item['path'], 'kind': 'application'})
        return public(item)

    @app.get('/api/app-library')
    async def library():
        owner = profile()
        state = load(owner)
        for item in state['items']:
            if item['state'] == 'scanning':
                schedule(owner, item['id'])
        return {'items': [public(item) for item in state['items']]}

    @app.post('/api/app-library/open')
    async def add_local(request: Request):
        return await register(Path(str((await request.json()).get('path', ''))))

    @app.post('/api/app-library/upload')
    async def upload_app(file: UploadFile):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(file.filename or 'application.exe').name).strip(' .')[:180]
        if Path(name).suffix.lower() not in {'.exe', '.msi', '.lnk'}:
            raise HTTPException(415, 'Choose an .exe, .msi or .lnk file.')
        destination = root / 'runtime/app-library-files' / secrets.token_hex(12)
        destination.mkdir(parents=True)
        path = destination / name
        try:
            size = 0
            with path.open('wb') as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 2 * 1024 * 1024 * 1024:
                        raise HTTPException(413, 'Use the desktop app for applications larger than 2 GB.')
                    stream.write(chunk)
            return await register(path)
        except Exception:
            path.unlink(missing_ok=True)
            destination.rmdir()
            raise

    @app.post('/api/app-library/{identity}/scan')
    async def rescan(identity: str):
        owner = profile()
        item = lookup(owner, identity)
        item.update(state='scanning', detail='Waiting for Microsoft Defender…')
        update(owner, item)
        schedule(owner, identity)
        return public(item)

    @app.post('/api/app-library/{identity}/remove')
    async def remove(identity: str):
        owner = profile()
        state = load(owner)
        state['items'] = [item for item in state['items'] if item['id'] != identity]
        save(owner, state)
        await context.remove(identity)
        return {'removed': True}

    @app.post('/api/app-library/{identity}/launch')
    async def launch(identity: str, request: Request):
        expected = os.environ.get('VISION_DESKTOP_SECRET', '')
        if not expected or not secrets.compare_digest(expected, request.headers.get('x-vision-desktop', '')):
            raise HTTPException(403, 'Open applications using the Vision desktop app.')
        owner = profile()
        async with locks.setdefault((owner, identity), asyncio.Lock()):
            item = lookup(owner, identity)
            path = Path(item['path'])
            if item['state'] != 'clear' or time.time() - item.get('scan_time', 0) > 86400:
                schedule(owner, identity)
                raise HTTPException(409, 'A completed current scan is required. Wait for the scan, then click Open again.')
            try:
                current = await asyncio.to_thread(digest, path)
            except OSError:
                raise HTTPException(404, 'This application file has moved or was removed. Add it again.')
            if current != item.get('sha256'):
                item.update(state='scanning', detail='The application changed. A new scan is required.')
                update(owner, item)
                schedule(owner, identity)
                raise HTTPException(409, 'The application changed. Scan it again before opening.')
            if path.suffix.lower() == '.msi':
                raise HTTPException(409, 'Installer execution is deferred until application isolation is implemented. It will not be installed into Windows.')
            # No shell interpolation, extra command arguments or silent elevation.
            args = ([str(path)] if path.suffix.lower() == '.exe' else [str(Path(os.environ['SystemRoot']) / 'System32/msiexec.exe'), '/i', str(path)]) + item.get('arguments', [])
            item['last_opened'] = datetime.now(timezone.utc).isoformat()
            update(owner, item)
            await context.gateway.publish('settings.saved', {'text': 'Application launch authorized: ' + item['name']})
            from .app_windows import windows
            app_id = None
            # Windows Calculator's signed system stub activates a packaged app
            # through Windows, outside the launcher's process family.
            if path.resolve() == (Path(os.environ['SystemRoot']) / 'System32/calc.exe').resolve():
                app_id = 'Microsoft.WindowsCalculator_8wekyb3d8bbwe!App'
            return {'executable': args[0], 'args': args[1:], 'directory': item.get('directory') or str(path.parent), 'name': item['name'], 'app_id': app_id, 'before': [w['hwnd'] for w in await asyncio.to_thread(windows)]}
