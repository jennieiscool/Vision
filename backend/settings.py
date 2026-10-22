"""Local GUI settings backed by the installed engine, never sample settings."""
import hashlib
import json
import re
from pathlib import Path
import yaml
from fastapi import HTTPException, Request

MASK = '[unchanged secret]'


def redact(value, key=''):
    if isinstance(value, dict):
        if key in {'env', 'headers'}:
            return {k: MASK if v else v for k, v in value.items()}
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str) and value and re.search(r'api.?key|password|secret|token|authorization|credential', key, re.I):
        return MASK
    return value


def restore_secrets(value, old):
    if value == MASK:
        return old
    if isinstance(value, dict):
        return {k: restore_secrets(v, old.get(k) if isinstance(old, dict) else None) for k, v in value.items()}
    if isinstance(value, list):
        return [restore_secrets(v, old[i] if isinstance(old, list) and i < len(old) else None) for i, v in enumerate(value)]
    return value


def install_settings(app, gateway, config, root, connected, execute_slash, apply_configuration, install_prompt):
    def home():
        return Path(config.get('hermes_home') or Path(config['hermes_path']).parent)

    def native_config():
        path = home() / 'config.yaml'
        raw = path.read_text(encoding='utf-8')
        return path, yaml.safe_load(raw) or {}, hashlib.sha256(raw.encode()).hexdigest()

    def idle():
        if gateway.busy:
            raise HTTPException(409, 'Finish or stop the current task before changing settings.')

    @app.get('/api/settings/prompt')
    async def get_prompt():
        _, data, _ = native_config()
        text = str((data.get('agent') or {}).get('system_prompt') or '')
        text = re.sub(r'\[Vision desktop instructions\].*?\[/Vision desktop instructions\]', '', text, flags=re.S).strip()
        return {'prompt': text}

    @app.post('/api/settings/prompt')
    async def save_prompt(request: Request):
        idle()
        text = (await request.json()).get('prompt')
        if not isinstance(text, str) or len(text) > 100000:
            raise HTTPException(400, 'Prompt must be text up to 100,000 characters')
        path, data, _ = native_config()
        data.setdefault('agent', {})['system_prompt'] = text
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8')
        install_prompt()
        await gateway.call('vision.prompt.reload', {'session_id': connected()})
        await gateway.publish('settings.saved', {'text': 'Instructions saved and applied.'})
        return {'saved': True, 'message': 'Instructions saved and applied to the active conversation.'}

    @app.get('/api/settings/config')
    async def get_config():
        _, data, revision = native_config()
        # Environment maps often use nonstandard secret names. Keep names, mask values.
        def mask_env(value):
            if isinstance(value, dict):
                return {k: ({name: MASK if item else item for name, item in v.items()} if k in {'env', 'headers'} and isinstance(v, dict) else mask_env(v)) for k, v in value.items()}
            if isinstance(value, list):
                return [mask_env(v) for v in value]
            return value
        return {'config': mask_env(redact(data)), 'revision': revision, 'home': str(home()), 'engine': str(Path(config['hermes_path']))}

    @app.post('/api/settings/config')
    async def save_config(request: Request):
        idle()
        body = await request.json()
        path, existing, revision = native_config()
        if body.get('revision') != revision:
            raise HTTPException(409, 'Settings changed elsewhere. Reload before saving.')
        if not isinstance(body.get('config'), dict):
            raise HTTPException(400, 'Settings must be a JSON object')
        updated = restore_secrets(body['config'], existing)
        for key in {'agent', 'terminal', 'display', 'providers', 'memory', 'browser', 'mcp_servers', 'compression', 'skills'}:
            if key in updated and not isinstance(updated[key], dict):
                raise HTTPException(400, f'{key} must be an object')
        if 'model' in updated and not isinstance(updated['model'], (str, dict)):
            raise HTTPException(400, 'model must be an object or string')
        original = path.read_text(encoding='utf-8')
        try:
            temporary = path.with_suffix('.yaml.tmp')
            temporary.write_text(yaml.safe_dump(updated, sort_keys=False, allow_unicode=True), encoding='utf-8')
            temporary.replace(path)
            install_prompt()
        except Exception as exc:
            path.write_text(original, encoding='utf-8')
            raise HTTPException(400, 'Settings were not saved: ' + str(exc)) from exc
        try:
            result = await apply_configuration()
            await gateway.call('vision.prompt.reload', {'session_id': connected()})
        except Exception as exc:
            await gateway.publish('settings.saved', {'text': 'Settings saved. Restart Vision to apply them.'})
            return {'saved': True, 'restart_required': True, 'message': 'Saved. Reload requires a restart: ' + str(exc)}
        await gateway.publish('settings.saved', {'text': 'Settings saved.'})
        return {'saved': True, 'restart_required': True, 'message': 'Saved. Model and agent settings reloaded; startup/service settings apply after restarting Vision.', 'applied': result.get('configured', False)}

    @app.post('/api/settings/rpc')
    async def rpc(request: Request):
        body = await request.json()
        method = body.get('method')
        allowed = {'config.get', 'config.show', 'config.set', 'tools.list', 'tools.show', 'tools.configure',
                   'toolsets.list', 'skills.manage', 'skills.reload', 'session.list', 'session.status',
                   'session.title', 'session.usage', 'session.context_breakdown'}
        if method not in allowed:
            raise HTTPException(400, 'Unsupported settings action')
        params = body.get('params') or {}
        if not isinstance(params, dict):
            raise HTTPException(400, 'Invalid settings arguments')
        if method in {'config.set', 'tools.configure', 'skills.reload', 'session.title'} or (method == 'skills.manage' and params.get('action', 'list') not in {'list', 'inspect', 'browse', 'search'}):
            idle()
        try:
            result = await gateway.call(method, {**params, 'session_id': connected()})
            if method == 'config.set' and params.get('key') in {'prompt', 'personality'}:
                install_prompt()
                await apply_configuration()
                await gateway.call('vision.prompt.reload', {'session_id': connected()})
            if method in {'config.set', 'tools.configure', 'skills.reload'} or (method == 'session.title' and 'title' in params):
                label = 'Conversation title' if method == 'session.title' else 'Toolset' if method == 'tools.configure' else 'Skills' if method == 'skills.reload' else 'Setting'
                await gateway.publish('settings.saved', {'text': label + ' updated.'})
            return redact(result)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/settings/command')
    async def command(request: Request):
        text = str((await request.json()).get('command', ''))
        if not text.startswith('/') or len(text) > 20000:
            raise HTTPException(400, 'Enter a valid slash command')
        try:
            return await execute_slash(text)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc

    def memory_files():
        found = {}
        locations = [home() / 'memories', home() / 'memory']
        for folder in locations:
            if folder.is_dir():
                for path in folder.rglob('*'):
                    if path.is_file() and path.suffix.lower() in {'.md', '.txt'} and path.resolve().is_relative_to(home().resolve()):
                        found[str(path.relative_to(home()))] = path
        for name in ['MEMORY.md', 'USER.md']:
            path = home() / name
            if path.is_file():
                found[name] = path
        return found

    @app.get('/api/settings/memory')
    async def memory():
        return {'files': [{'name': name, 'content': path.read_text(encoding='utf-8', errors='replace')} for name, path in memory_files().items()]}

    @app.post('/api/settings/memory')
    async def save_memory(request: Request):
        idle()
        body = await request.json()
        path = memory_files().get(body.get('name'))
        if path is None or not isinstance(body.get('content'), str) or len(body['content']) > 250000:
            raise HTTPException(400, 'Choose a valid memory file, up to 250,000 characters')
        path.write_text(body['content'], encoding='utf-8')
        try:
            await gateway.call('vision.memory.reload', {'session_id': connected()})
            message = 'Memory saved and reloaded for this conversation.'
        except (RuntimeError, HTTPException):
            message = 'Memory saved. Open a new conversation to reload it.'
        await gateway.publish('settings.saved', {'text': message})
        return {'saved': True, 'message': message}

    def skills_files():
        files = {}
        for folder in [home() / 'skills', Path(config['hermes_path']) / 'skills']:
            if folder.is_dir():
                for path in folder.rglob('SKILL.md'):
                    resolved = path.resolve()
                    if not (resolved.is_relative_to(home().resolve()) or resolved.is_relative_to(Path(config['hermes_path']).resolve())):
                        continue
                    identity = hashlib.sha256(str(resolved).encode()).hexdigest()[:24]
                    files[identity] = path
        return files

    @app.get('/api/settings/skills')
    async def skills():
        available = await gateway.call('skills.manage', {'action': 'list', 'session_id': connected()})
        items = []
        for identity, path in skills_files().items():
            text = path.read_text(encoding='utf-8', errors='replace')
            metadata = {}
            if text.startswith('---'):
                try:
                    metadata = yaml.safe_load(text.split('---', 2)[1]) or {}
                except yaml.YAMLError:
                    pass
            if not isinstance(metadata, dict):
                metadata = {}
            items.append({'id': identity, 'name': str(metadata.get('name') or path.parent.name), 'description': str(metadata.get('description') or ''), 'path': str(path)})
        return {'available': available.get('skills', {}), 'installed': sorted(items, key=lambda row: row['name'].lower())}

    @app.get('/api/settings/skills/{identity}')
    async def skill_content(identity: str):
        path = skills_files().get(identity)
        if path is None:
            raise HTTPException(404, 'Skill not found')
        return {'name': path.parent.name, 'content': path.read_text(encoding='utf-8', errors='replace')}
