"""Local desktop profiles, real system inventory and application security."""
import asyncio
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

import yaml
from fastapi import HTTPException, Request


def install_desktop_settings(app, gateway, config, root, connected, apply_configuration, install_prompt):
    runtime = root / 'runtime'
    preferences_path = runtime / 'desktop-preferences.json'
    preferences = json.loads(preferences_path.read_text()) if preferences_path.exists() else {}
    preferences.setdefault('name', os.environ.get('USERNAME', 'My profile'))
    app.state.vision_locked = bool(preferences.get('password_hash') and preferences.get('lock_on_start'))
    inventory = {}
    failed_attempts = 0
    retry_at = 0
    switching = asyncio.Lock()

    def save():
        preferences_path.write_text(json.dumps(preferences, indent=2), encoding='utf-8')

    def idle():
        if gateway.busy or switching.locked():
            raise HTTPException(409, 'Finish the current task before changing this setting.')

    async def scan():
        for area in ['overview', 'devices', 'drives', 'settings', 'apps']:
            process = await asyncio.create_subprocess_exec(
                'powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', str(root / 'backend/windows-system.ps1'), '-Area', area,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=0x08000000)
            try:
                output, _ = await asyncio.wait_for(process.communicate(), 50)
                value = json.loads(output.decode('utf-8-sig', errors='replace'))
                inventory[area] = value.get('Data', {'unavailable': value.get('Error', 'Unavailable')})
            except (asyncio.TimeoutError, ValueError):
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                inventory[area] = {'unavailable': 'Windows did not return this information.'}
        inventory['updated'] = time.time()
        (runtime / 'system-inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')

    async def desktop_background():
        await scan()
        while True:
            await asyncio.sleep(30)
            if preferences.get('scheduler') and gateway.ready.is_set() and not app.state.vision_locked:
                try:
                    await gateway.call('vision.schedule.tick', {}, timeout=20)
                except Exception as exc:
                    await gateway.publish('schedule.error', {'text': str(exc)})

    app.state.desktop_start = desktop_background

    @app.get('/api/desktop/system')
    async def system():
        return {'inventory': inventory, 'collecting': 'updated' not in inventory}

    @app.post('/api/desktop/system/refresh')
    async def system_refresh():
        await scan()
        return {'inventory': inventory}

    @app.get('/api/desktop/profiles')
    async def profiles():
        result = await gateway.call('vision.profiles', {})
        return {**result, 'active': config.get('profile', 'default'), 'display_name': preferences['name']}

    @app.post('/api/desktop/profiles')
    async def profile_action(request: Request):
        idle()
        body = await request.json()
        action = body.get('action')
        if action == 'rename':
            name = str(body.get('display_name', '')).strip()
            if not name or len(name) > 60:
                raise HTTPException(400, 'Enter a name of up to 60 characters.')
            preferences['name'] = name
            save()
            await gateway.publish('settings.saved', {'text': 'Profile name saved.'})
            return {'saved': True}
        name = str(body.get('name', ''))
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', name):
            raise HTTPException(400, 'Use letters, numbers, hyphens or underscores for the profile name.')
        if action == 'create':
            try:
                result = await gateway.call('vision.profiles', {'action': 'create', 'name': name,
                    'description': str(body.get('description', ''))[:500], 'inherit': body.get('inherit', True)})
                await gateway.publish('settings.saved', {'text': 'Profile created.'})
                return result
            except RuntimeError as exc:
                raise HTTPException(400, str(exc)) from exc
        if action != 'switch':
            raise HTTPException(400, 'Unknown profile action.')
        if app.state.has_open_terminals():
            raise HTTPException(409, 'Close open terminal tabs before switching profiles.')
        base = runtime / 'hermes'
        home = base if name == 'default' else base / 'profiles' / name
        if not (home / 'config.yaml').is_file():
            raise HTTPException(404, 'That profile is not available.')
        async with switching:
            await gateway.close()
            config.update(profile=name, hermes_home=str(home))
            native = yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8')) or {}
            model = native.get('model') or {}
            config.update(provider=model.get('provider', '') if isinstance(model, dict) else '',
                          model=model.get('default', '') if isinstance(model, dict) else str(model))
            (runtime / 'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
            install_prompt()
            await gateway.start()
            await apply_configuration()
            await gateway.publish('chat.reloaded', {})
        return {'active': name}

    @app.get('/api/desktop/schedules')
    async def schedules():
        result = await gateway.call('vision.schedules', {'action': 'list'})
        return {**result, 'running': bool(preferences.get('scheduler'))}

    @app.post('/api/desktop/schedules')
    async def schedule_action(request: Request):
        idle()
        body = await request.json()
        if body.get('action') == 'scheduler':
            preferences['scheduler'] = bool(body.get('enabled'))
            save()
            return {'running': preferences['scheduler']}
        try:
            return await gateway.call('vision.schedules', body)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get('/api/desktop/schedules/{identity}/results')
    async def schedule_results(identity: str):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', identity):
            raise HTTPException(400, 'Invalid task')
        home = Path(config.get('hermes_home') or Path(config['hermes_path']).parent)
        output = home / 'cron/output' / identity
        files = sorted(output.glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True)[:8] if output.is_dir() else []
        return {'results': [{'time': file.stat().st_mtime,
                            'content': file.read_text(encoding='utf-8', errors='replace')[:100000]}
                           for file in files if file.resolve().is_relative_to(home.resolve())]}

    @app.get('/api/desktop/journey')
    async def journey():
        return await gateway.call('vision.learning', {})

    @app.get('/api/desktop/security')
    async def security():
        return {'locked': app.state.vision_locked, 'password_enabled': bool(preferences.get('password_hash')),
                'lock_on_start': bool(preferences.get('lock_on_start')), 'name': preferences['name']}

    @app.post('/api/desktop/security')
    async def security_action(request: Request):
        nonlocal failed_attempts, retry_at
        body = await request.json()
        action = body.get('action')
        if action == 'unlock':
            if time.monotonic() < retry_at:
                raise HTTPException(429, 'Please wait a moment before trying again.')
            native_secret = os.environ.get('VISION_DESKTOP_SECRET', '')
            verified_hello = bool(native_secret and body.get('hello') and secrets.compare_digest(
                request.headers.get('x-vision-desktop', ''), native_secret))
            password = str(body.get('password', ''))
            digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(preferences.get('salt', '00')), n=16384, r=8, p=1).hex()
            if not verified_hello and not (preferences.get('password_hash') and secrets.compare_digest(digest, preferences['password_hash'])):
                failed_attempts += 1
                retry_at = time.monotonic() + min(30, failed_attempts * 2)
                raise HTTPException(403, 'The password did not match.')
            app.state.vision_locked = False
            failed_attempts = 0
            return {'unlocked': True}
        if app.state.vision_locked:
            raise HTTPException(423, 'Unlock Vision to change security settings.')
        if action == 'password':
            password = str(body.get('password', ''))
            if len(password) < 8 or len(password) > 1000:
                raise HTTPException(400, 'Use a password with at least eight characters.')
            salt = secrets.token_bytes(16)
            preferences['salt'] = salt.hex()
            preferences['password_hash'] = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
            preferences['lock_on_start'] = bool(body.get('lock_on_start', True))
            save()
            await gateway.publish('settings.saved', {'text': 'App lock password saved.'})
            return {'saved': True}
        if action == 'preferences':
            preferences['lock_on_start'] = bool(body.get('lock_on_start'))
            save()
            await gateway.publish('settings.saved', {'text': 'Startup lock preference saved.'})
            return {'saved': True}
        if action == 'lock':
            idle()
            if app.state.has_open_terminals():
                raise HTTPException(409, 'Close open terminal tabs before locking Vision.')
            if not preferences.get('password_hash'):
                raise HTTPException(400, 'Set an app password before locking Vision.')
            app.state.vision_locked = True
            for socket in tuple(app.state.open_sockets):
                try:
                    await socket.close(code=4423)
                except RuntimeError:
                    pass
            app.state.open_sockets.clear()
            return {'locked': True}
        raise HTTPException(400, 'Unknown security action.')
