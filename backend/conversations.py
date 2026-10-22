"""Profile-local pointers to real native sessions; Main is never a side-chat alias."""
import json
import secrets
import time
from fastapi import HTTPException, Request


class Conversations:
    def __init__(self, gateway):
        self.gateway = gateway
        self.active = 'main'

    @property
    def path(self):
        return self.gateway.root / ('runtime/conversations-' + self.gateway.config.get('profile', 'default') + '.json')

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'main': {'id': 'main', 'title': 'Main', 'stored_session_id': ''}, 'sides': []}

    def save(self, state):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def record(self, session=None, identity=None, title=None):
        session = session or self.gateway.session or {}
        identity = identity or self.active
        state = self.load()
        if identity == 'main':
            item = state['main']
        else:
            item = next((i for i in state['sides'] if i['id'] == identity), None)
            if item is None:
                item = {'id': identity, 'title': title or 'Side conversation'}
                state['sides'].append(item)
        stored = session.get('stored_session_id')
        if stored:
            item['stored_session_id'] = stored
        # Unsaved new native sessions can be revisited in this running process.
        if session.get('session_id'):
            item['live_session_id'] = session['session_id']
        if title:
            item['title'] = title
        item['updated'] = time.time()
        self.save(state)
        if identity == 'main' and stored:
            self.gateway.state_path.write_text(json.dumps({'stored_session_id': stored}), encoding='utf-8')

    def public(self):
        state = self.load()
        return {'active': self.active, 'main': state['main'], 'sides': sorted(state['sides'], key=lambda i: i.get('updated', 0), reverse=True), 'busy': self.gateway.busy, 'connected': bool(self.gateway.session and self.gateway.ready.is_set()), 'profile': self.gateway.config.get('profile', 'default')}


def install_conversations(app, gateway, connected, apply_prompt):
    conversations = gateway.conversations
    live = {}

    async def native(method, params):
        try:
            return await gateway.call(method, params)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/api/conversations')
    async def list_conversations():
        return conversations.public()

    @app.get('/api/conversations/recent')
    async def recent():
        connected()
        result = await native('session.list', {'limit': 50})
        main = conversations.load()['main'].get('stored_session_id')
        return {'sessions': [i for i in result.get('sessions', []) if i.get('id') != main]}

    @app.post('/api/conversations')
    async def change(request: Request):
        data = await request.json()
        async with gateway.lock:
            connected()
            if gateway.busy:
                raise HTTPException(409, 'Wait for the current reply or stop it before switching conversations.')
            action = data.get('action', 'switch')
            if action not in {'switch', 'create', 'recent'}:
                raise HTTPException(400, 'Choose a conversation action.')
            old_id, old_session = conversations.active, gateway.session
            await native('vision.conversation.persist', {'session_id': old_session['session_id']})
            conversations.record()
            owner = gateway.config.get('profile', 'default')
            epoch = gateway.process.pid
            live[(owner, epoch, old_id)] = old_session
            state = conversations.load()
            title = str(data.get('title') or 'Side conversation').strip()[:100]
            identity = str(data.get('id', 'main'))
            if action == 'create':
                identity = 'side-' + secrets.token_hex(10)
                result = await native('session.create', {'title': title, 'cwd': str(gateway.root), 'model': gateway.config['model'], 'provider': gateway.config['provider'], 'source': 'web'})
                await native('vision.conversation.persist', {'session_id': result['session_id']})
            else:
                if action == 'recent':
                    stored = str(data.get('session_id', ''))
                    if not stored or stored == state['main'].get('stored_session_id'):
                        raise HTTPException(400, 'Use the Main tab for the main conversation.')
                    known = next((i for i in state['sides'] if i.get('stored_session_id') == stored), None)
                    identity = known['id'] if known else 'side-' + secrets.token_hex(10)
                    item = known or {'stored_session_id': stored}
                    if known:
                        title = known.get('title') or title
                else:
                    item = state['main'] if identity == 'main' else next((i for i in state['sides'] if i['id'] == identity), None)
                    if item is None:
                        raise HTTPException(404, 'This side conversation is no longer available.')
                    title = item.get('title', 'Side conversation')
                result = live.get((owner, epoch, identity))
                if result:
                    try:
                        await gateway.call('session.history', {'session_id': result['session_id']})
                    except RuntimeError:
                        result = None
                if not result:
                    stored = item.get('stored_session_id')
                    if not stored:
                        raise HTTPException(409, 'This empty conversation has no saved messages yet. Start a new side conversation.')
                    result = await native('session.resume', {'session_id': stored, 'cwd': str(gateway.root)})
            gateway.session = result
            conversations.active = identity
            conversations.record(result, identity, title if identity != 'main' else 'Main')
            live[(owner, epoch, identity)] = result
            gateway.requests.clear()
            gateway.stream = ''
            try:
                await apply_prompt()
            except Exception:
                # The session itself still contains the installed Vision prompt.
                pass
            await gateway.publish('conversation.changed', conversations.public())
            await gateway.publish('chat.reloaded', {'conversation_only': True})
            return conversations.public()
