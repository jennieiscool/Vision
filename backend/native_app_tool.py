"""Native engine adapter: live accessibility observations and real window input."""
import dataclasses
import json
import os
import threading
import time
import sys

_lock = threading.RLock()
_backend = None
_observations = {}


def driver():
    global _backend
    if _backend is None:
        from tools.computer_use.cua_backend import CuaDriverBackend
        instance = CuaDriverBackend()
        instance.start()
        _backend = instance
    return _backend


def execute(target, args, human=False):
    """Keep the capture's exact window and element tokens together under one lock."""
    with _lock:
        backend = driver()
        identity = target['id']
        action = args.get('action', 'observe')
        recent = _observations.get(identity)
        if action == 'observe' or (human and (not recent or time.monotonic() - recent[0] > 30 or recent[3] != target.get('viewport_revision'))):
            capture = backend.capture(mode='vision' if human else 'som', pid=int(target['window_pid']), window_id=int(target['hwnd'], 0) if isinstance(target['hwnd'], str) else int(target['hwnd']))
            if not capture.png_b64 and not capture.elements:
                raise RuntimeError('The driver could not observe this application: ' + str(capture.window_title))
            _observations.clear()  # driver has a single sticky capture context
            _observations[identity] = (time.monotonic(), capture.width, capture.height, target.get('viewport_revision'), 'human' if human else 'ai')
            if action == 'observe':
                return dataclasses.asdict(capture)
        previous = _observations.get(identity)
        if not previous or time.monotonic() - previous[0] > 30 or previous[3] != target.get('viewport_revision'):
            raise RuntimeError('Observe this application again before acting; its controls may have changed.')
        if not human and previous[4] != 'ai':
            raise RuntimeError('The user interacted with this application. Observe it again before acting.')
        delivery = {'delivery_mode': 'background', 'bring_to_front': False}
        element = args.get('element')
        coordinates = {}
        if element is not None:
            coordinates['element'] = int(element)
        elif args.get('x') is not None and args.get('y') is not None:
            x, y = float(args['x']), float(args['y'])
            if human:
                x, y = max(0, min(1, x)) * previous[1], max(0, min(1, y)) * previous[2]
            coordinates.update(x=int(x), y=int(y))
        if action in {'click', 'double_click', 'right_click'}:
            result = backend.click(**coordinates, button='right' if action == 'right_click' else 'left', click_count=2 if action == 'double_click' else 1, **delivery)
        elif action == 'scroll':
            result = backend.scroll(direction=args.get('direction', 'down'), amount=max(1, min(30, int(args.get('amount', 3)))), **coordinates, **delivery)
        elif action == 'type':
            result = backend.type_text(str(args.get('text', ''))[:100000], **delivery)
        elif action == 'key':
            result = backend.key(str(args.get('keys', '')), **delivery)
        elif action == 'set_value':
            result = backend.set_value(str(args.get('text', '')), element=int(element) if element is not None else None)
        elif action == 'drag':
            start_x, start_y = float(args['from_x']), float(args['from_y'])
            if human:
                start_x, start_y = max(0, min(1, start_x)) * previous[1], max(0, min(1, start_y)) * previous[2]
            result = backend.drag(from_xy=(int(start_x), int(start_y)), to_xy=(coordinates['x'], coordinates['y']), **delivery)
        else:
            raise ValueError('Unknown application action.')
        if not human:
            _observations.clear()  # AI must observe again after every mutation
        else:
            _observations[identity] = (*previous[:4], 'human')
        data = dataclasses.asdict(result)
        if not result.ok:
            data['error'] = result.message
        return data


def handle(args, **kwargs):
    try:
        import httpx
        with httpx.Client(timeout=15, trust_env=False) as client:
            response = client.post('http://127.0.0.1:8787/api/app-control/agent/authorize',
                                   headers={'Origin': 'http://127.0.0.1:8787', 'x-vision-agent': os.environ.get('VISION_APP_BRIDGE_TOKEN', '')}, json=args)
        data = response.json()
        if response.is_error:
            return json.dumps({'error': data.get('detail', 'Application control is unavailable.')})
        if args.get('action') == 'list':
            return json.dumps(data)
        result = execute(data, args)
        image = result.pop('png_b64', None)
        text = json.dumps(result, ensure_ascii=False)
        if image:
            mime = result.get('image_mime_type') or 'image/png'
            return {'_multimodal': True, 'content': [{'type': 'text', 'text': text}, {'type': 'image_url', 'image_url': {'url': 'data:' + mime + ';base64,' + image}}], 'text_summary': text}
        return text
    except Exception as exc:
        return json.dumps({'error': str(exc)})


SCHEMA = {'name': 'vision_app', 'description': 'Observe and control the actual application in Vision preview. List managed sessions, observe accessibility controls and live image, then act on that exact window. Observe after every action. Never infer success from input delivery; inspect the result. Human takeover and application-control settings are enforced. Coordinates are screenshot pixels. Normal actions use background delivery; elevated or unsupported applications can refuse input.',
          'parameters': {'type': 'object', 'properties': {
              'action': {'type': 'string', 'enum': ['list', 'observe', 'click', 'double_click', 'right_click', 'scroll', 'type', 'key', 'set_value', 'drag']},
              'session': {'type': 'string'}, 'element': {'type': 'integer'},
              'x': {'type': 'number'}, 'y': {'type': 'number'}, 'from_x': {'type': 'number'}, 'from_y': {'type': 'number'},
              'direction': {'type': 'string', 'enum': ['up', 'down', 'left', 'right']}, 'amount': {'type': 'integer'},
              'text': {'type': 'string'}, 'keys': {'type': 'string'}}, 'required': ['action']}}


def install(server):
    from tools.registry import registry
    registry.register(name='vision_app', toolset='vision_app', schema=SCHEMA, handler=handle,
                      check_fn=lambda: os.name == 'nt' or sys.platform.startswith('linux'), description='Control managed Vision application previews')
    original_toolsets = server._load_enabled_toolsets

    def application_toolsets():
        enabled = original_toolsets()
        return None if enabled is None else sorted({*enabled, 'vision_app'})

    server._load_enabled_toolsets = application_toolsets

    @server.method('vision.app.control')
    def control(rid, params):
        try:
            return server._ok(rid, execute(params['target'], params.get('args', {}), human=True))
        except Exception as exc:
            return server._err(rid, 4002, str(exc))
