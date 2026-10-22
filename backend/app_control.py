"""Profile-scoped real application windows and explicit shared-control policy."""
import asyncio
import json
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request
if os.name == 'nt':
    from . import app_windows as win
else:
    from . import app_windows_linux as win


def install_app_control(app, root, context):
    sessions = {}
    profile = lambda: context.config.get('profile', 'default')

    def policy_path():
        return root / ('runtime/application-control-' + profile() + '.json')

    def policy():
        defaults = {'enabled': False, 'automatic': False, 'quiet_seconds': 3}
        try:
            defaults.update(json.loads(policy_path().read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass
        return defaults

    def desktop(request):
        expected = os.environ.get('VISION_DESKTOP_SECRET', '')
        if not expected or not secrets.compare_digest(expected, request.headers.get('x-vision-desktop', '')):
            raise HTTPException(403, 'Use the Vision desktop application.')

    def get(identity):
        item = sessions.get(identity)
        if not item or item['profile'] != profile():
            raise HTTPException(404, 'This application session is not available in this profile.')
        if item.get('hwnd') and (not win.U.IsWindow(int(item['hwnd'])) or win.pid(int(item['hwnd'])) != item['window_pid'] or not win.same_path(win.executable(item['window_pid']), item.get('window_executable', item['executable']))):
            raise HTTPException(410, 'The application window closed. Open it again from Applications.')
        return item

    def public(item):
        return {key: item.get(key) for key in ('id', 'name', 'hwnd', 'window_pid', 'mode', 'reason', 'paused', 'candidates', 'workspace_id', 'viewport_revision')}

    async def discover(item):
        # Launcher processes and single-instance applications can use another PID;
        # executable identity must still match. Ambiguous windows require selection.
        family = await asyncio.to_thread(win.process_tree, item['launch_pid'])
        matches = [window for window in await asyncio.to_thread(win.windows)
                   if window['executable'] and (win.same_path(window['executable'], item['executable']) or window['pid'] in family or (item.get('app_id') and item['app_id'] in window.get('app_ids', [])))
                   and window.get('owner', '0') == '0']
        owned = [window for window in matches if window['pid'] == item.get('launch_pid')]
        fresh = [window for window in matches if window['hwnd'] not in item['before']]
        choices = owned or fresh or matches
        item['candidates'] = choices
        if len(choices) == 1:
            item.update(hwnd=choices[0]['hwnd'], window_pid=choices[0]['pid'], window_executable=choices[0]['executable'], mode='ready', reason='Application window found.')
        else:
            item.update(mode='pending' if not choices else 'choose', reason='Waiting for the application window.' if not choices else 'Choose the application window to host.')

    async def register(name, executable, launch_pid, before, workspace_id=None, app_id=None):
        item = {'id': secrets.token_hex(12), 'name': name, 'executable': str(executable),
                'launch_pid': launch_pid, 'before': before, 'profile': profile(), 'mode': 'pending',
                'paused': False, 'grant': False, 'workspace_id': workspace_id, 'app_id': app_id}
        sessions[item['id']] = item
        await discover(item)
        if not item.get('hwnd') and not item.get('candidates'):
            for existing in list(sessions.values()):
                if existing is not item and existing['profile'] == profile() and win.same_path(existing['executable'], executable) and existing.get('hwnd'):
                    try:
                        get(existing['id'])
                    except HTTPException:
                        continue
                    sessions.pop(item['id'], None)
                    return public(existing)
        return public(item)

    app.state.application_register = register

    @app.get('/api/app-control/settings')
    async def settings():
        return policy()

    @app.post('/api/app-control/settings')
    async def save_settings(request: Request):
        data = await request.json()
        values = policy()
        for key in ('enabled', 'automatic'):
            if key in data:
                if not isinstance(data[key], bool):
                    raise HTTPException(400, 'Choose enabled or disabled.')
                values[key] = data[key]
        if 'quiet_seconds' in data:
            values['quiet_seconds'] = max(1, min(15, int(data['quiet_seconds'])))
        target = policy_path()
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(values), encoding='utf-8')
        temporary.replace(target)
        await context.gateway.publish('settings.saved', {'text': 'Application control settings saved.'})
        return values

    @app.get('/api/app-control/sessions')
    async def listing():
        return {'items': [public(item) for item in sessions.values() if item['profile'] == profile()]}

    @app.get('/api/app-control/sessions/{identity}')
    async def status(identity: str):
        item = get(identity)
        if not item.get('hwnd'):
            await discover(item)
        return public(item)

    @app.post('/api/app-control/sessions/{identity}/control')
    async def control(identity: str, request: Request):
        item = get(identity)
        data = await request.json()
        action = data.get('action')
        if action == 'takeover':
            item['paused'] = True
        elif action == 'resume':
            item['paused'] = False
        elif action == 'allow-next':
            item['grant'] = True
        elif action == 'choose':
            await discover(item)
            choices = item.get('candidates', [])
            window = next((w for w in choices if w['hwnd'] == str(data.get('hwnd'))), None)
            if not window:
                raise HTTPException(409, 'Choose a window from this application.')
            item.update(hwnd=window['hwnd'], window_pid=window['pid'], window_executable=window['executable'], mode='ready')
        elif action == 'detach':
            await asyncio.to_thread(win.detach, item)
            item.update(mode='ready', visible=False)
        else:
            raise HTTPException(400, 'Unknown application control.')
        return public(item)

    @app.post('/api/app-control/desktop/{identity}')
    async def viewport(identity: str, request: Request):
        desktop(request)
        item = get(identity)
        data = await request.json()
        hwnd = int(item.get('hwnd') or 0)
        if not hwnd:
            return public(item)
        owner = int(data.get('owner') or 0)
        if not win.U.IsWindow(owner) or win.pid(owner) != int(os.environ.get('VISION_DESKTOP_PID', 0)):
            raise HTTPException(403, 'Invalid Vision window owner.')
        visible = bool(data.get('visible')) and not getattr(app.state, 'vision_locked', False)
        item['visible'] = visible
        if not visible:
            return public(item)
        rect = data.get('rect', [])
        if len(rect) != 4 or any(not isinstance(v, (int, float)) or abs(v) > 100000 for v in rect):
            raise HTTPException(400, 'Invalid preview bounds.')
        if item.get('rect') != rect:
            item['rect'] = rect
            item['viewport_revision'] = item.get('viewport_revision', 0) + 1
        item.update(await asyncio.to_thread(win.present_capture, item))
        return public(item)

    @app.post('/api/app-control/manual/{identity}')
    async def manual(identity: str, request: Request):
        item = get(identity)
        item['paused'] = True
        if not item.get('visible'):
            raise HTTPException(409, 'Open this application preview before controlling it.')
        data = await request.json()
        return await context.gateway.call('vision.app.control', {'target': public(item), 'args': data}, timeout=45)

    @app.post('/api/app-control/agent/authorize')
    async def authorize(request: Request):
        data = await request.json()
        if data.get('action') == 'list':
            return {'items': [public(item) for item in sessions.values() if item['profile'] == profile()]}
        item = get(data.get('session'))
        values = policy()
        if not values['enabled']:
            raise HTTPException(403, 'Application control is disabled. Enable it in Settings > Application control.')
        if not item.get('hwnd'):
            raise HTTPException(409, 'Choose an application window in the preview first.')
        if data.get('action') != 'observe':
            if item['paused'] or not item.get('visible'):
                raise HTTPException(409, 'Human control is active or the application preview is hidden. The user can resume AI control in its toolbar.')
            if win.input_idle() < values['quiet_seconds'] * 1000:
                raise HTTPException(409, 'The user is interacting. Wait for their input to become idle, then observe again.')
            if not values['automatic'] and not item.pop('grant', False):
                raise HTTPException(403, 'Automatic coordination is off. The user can Allow next action in the application toolbar or enable automatic coordination in Settings.')
        return public(item)

    @app.post('/api/app-control/editor/{identity}')
    async def editor(identity: str, request: Request):
        desktop(request)
        manifest = root / ('runtime/workspaces-' + profile() + '.json')
        records = json.loads(manifest.read_text(encoding='utf-8')).get('items', []) if manifest.exists() else []
        record = next((item for item in records if item['id'] == identity), None)
        if not record or not Path(record['path']).is_dir():
            raise HTTPException(404, 'Open a saved workspace first.')
        candidates = ([Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Microsoft VS Code/Code.exe',
                       Path(os.environ.get('ProgramFiles', '')) / 'Microsoft VS Code/Code.exe'] if os.name == 'nt' else
                      [Path(path) for path in (os.environ.get('VISION_CODE_BIN', ''), '/usr/bin/code', '/usr/bin/code-insiders') if path])
        code = next((p for p in candidates if p.is_file()), None)
        if not code:
            raise HTTPException(404, 'Install VS Code to use its complete workbench.')
        return {'executable': str(code), 'args': ['--new-window', '--user-data-dir', str(root / 'runtime/editor-profile'), record['path']],
                'directory': record['path'], 'name': 'VS Code · ' + record['name'], 'workspace_id': identity,
                'before': [w['hwnd'] for w in await asyncio.to_thread(win.windows)]}

    @app.post('/api/app-control/desktop-register')
    async def register_launch(request: Request):
        desktop(request)
        data = await request.json()
        return await register(data['name'], data['executable'], int(data['pid']), data.get('before', []), data.get('workspace_id'), data.get('app_id'))

    def detach_all():
        for item in sessions.values():
            win.detach(item)

    app.state.detach_applications = detach_all

    @app.post('/api/app-control/desktop-detach-all')
    async def detach_everything(request: Request):
        desktop(request)
        await asyncio.to_thread(detach_all)
        return {'detached': True}
