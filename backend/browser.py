"""Dedicated local browser shared with Hermes via its supported CDP override."""
import asyncio
import base64
import os
import time
import contextlib
from pathlib import Path
from urllib.parse import urlsplit


class Browser:
    def __init__(self, root, gateway):
        self.root, self.gateway = root, gateway
        self.playwright = self.context = self.task = None
        self.latest = None
        self.preview_page = None
        self.control_lock = asyncio.Lock()
        self.stream_clients = set()
        self.stream = None
        self.stream_page = None
        self.latest_frame = None
        self.last_frame_at = 0
        self.frame_tasks = set()
        self.pending_frame = None
        self.frame_timer = None

    async def start(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        cache = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
        bundled = self.root / "runtime/chromium/chrome-win64/chrome.exe"
        available = [bundled] if bundled.is_file() else sorted(cache.glob("chromium-*/chrome-win64/chrome.exe"))
        if not available:
            raise RuntimeError("Chromium is missing. Run setup.ps1 to install it.")
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.root / "runtime/browser"), executable_path=str(available[-1]),
            headless=True, viewport={"width": 1280, "height": 800},
            # Playwright adds --mute-audio to headless Chromium by default.
            # This browser runs on the user's computer, so use its real audio output.
            ignore_default_args=['--mute-audio'],
            args=["--remote-debugging-port=9227", "--remote-debugging-address=127.0.0.1",
                  '--autoplay-policy=no-user-gesture-required'],
        )
        self.task = asyncio.create_task(self.frames())

    async def frames(self):
        while True:
            try:
                page = self.select_page()
                if page and page.url != 'about:blank':
                    viewport = page.viewport_size or {'width': 1280, 'height': 800}
                    metadata = {'url': page.url, **viewport}
                    if metadata != self.latest:
                        self.latest = metadata
                        await self.gateway.publish('browser.state', metadata)
                    if self.stream_clients and (self.stream_page is not page or self.stream is None):
                        await self.start_stream(page)
                if not self.stream_clients and self.stream:
                    await self.stop_stream()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                await self.stop_stream()
                await self.gateway.publish('browser.error', {'text': 'Browser stream reconnecting: ' + str(exc)})
                await asyncio.sleep(2)
            await asyncio.sleep(.25)

    async def stop_stream(self):
        if self.frame_timer:
            self.frame_timer.cancel()
            self.frame_timer = None
        self.pending_frame = None
        stream, self.stream = self.stream, None
        self.stream_page = None
        self.latest_frame = None
        if stream:
            with contextlib.suppress(Exception):
                await stream.send('Page.stopScreencast')
                await stream.detach()

    async def start_stream(self, page):
        await self.stop_stream()
        stream = await self.context.new_cdp_session(page)
        self.stream, self.stream_page = stream, page
        self.last_frame_at = 0

        def receive(event):
            task = asyncio.create_task(self.receive_frame(stream, page, event))
            self.frame_tasks.add(task)
            task.add_done_callback(self.frame_tasks.discard)

        stream.on('Page.screencastFrame', receive)
        # Frames arrive from Chromium's compositor instead of a slow screenshot loop.
        await stream.send('Page.startScreencast', {'format': 'jpeg', 'quality': 72,
                          'maxWidth': 1280, 'maxHeight': 800, 'everyNthFrame': 1})

    async def receive_frame(self, stream, page, event):
        try:
            await stream.send('Page.screencastFrameAck', {'sessionId': event['sessionId']})
            if self.stream is not stream:
                return
            self.pending_frame = (page, event)
            if self.frame_timer is None:
                delay = max(0, 1 / 30 - (time.monotonic() - self.last_frame_at))
                self.frame_timer = asyncio.get_running_loop().call_later(delay, self.flush_frame)
        except Exception:
            # Page closure/detachment is picked up by the stream supervisor.
            if self.stream is stream:
                self.stream_page = None

    def flush_frame(self):
        self.frame_timer = None
        pending, self.pending_frame = self.pending_frame, None
        if pending is None:
            return
        page, event = pending
        viewport = page.viewport_size or {'width': 1280, 'height': 800}
        metadata = event.get('metadata') or {}
        self.latest_frame = {'image': base64.b64decode(event['data']), 'url': page.url,
                             'width': metadata.get('deviceWidth', viewport['width']),
                             'height': metadata.get('deviceHeight', viewport['height'])}
        self.last_frame_at = time.monotonic()
        self.preview_page = page
        for queue in tuple(self.stream_clients):
            # Replace stale video frames without dropping the final frame of a change.
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(self.latest_frame)

    def select_page(self):
        pages = [p for p in self.context.pages if not p.is_closed()]
        visible = [p for p in pages if p.url != 'about:blank']
        return visible[-1] if visible else pages[-1] if pages else None

    async def control(self, body):
        if not self.context:
            raise RuntimeError('The browser is still starting')
        async with self.control_lock:
            page = self.preview_page if self.preview_page and not self.preview_page.is_closed() else self.select_page()
            if page is None:
                page = await self.context.new_page()
            action = body.get('action')
            if action == 'navigate':
                url = str(body.get('url', '')).strip()
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                parsed = urlsplit(url)
                if parsed.scheme not in {'http', 'https'} or not parsed.hostname or len(url) > 8000:
                    raise ValueError('Enter a valid web address')
                await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            elif action in {'back', 'forward', 'reload'}:
                await {'back': page.go_back, 'forward': page.go_forward, 'reload': page.reload}[action](wait_until='domcontentloaded', timeout=20000)
            elif action in {'move', 'down', 'up'}:
                viewport = page.viewport_size or {'width': 1280, 'height': 800}
                x = max(0, min(viewport['width'] - 1, float(body.get('x', 0))))
                y = max(0, min(viewport['height'] - 1, float(body.get('y', 0))))
                await page.mouse.move(x, y)
                if action != 'move':
                    button = body.get('button', 'left')
                    if button not in {'left', 'right', 'middle'}:
                        raise ValueError('Unsupported mouse button')
                    await getattr(page.mouse, action)(button=button, click_count=max(1, min(2, int(body.get('click_count', 1)))))
            elif action == 'scroll':
                await page.mouse.wheel(max(-3000, min(3000, float(body.get('dx', 0)))), max(-3000, min(3000, float(body.get('dy', 0)))))
            elif action == 'key':
                key = str(body.get('key', ''))
                if not key or len(key) > 80:
                    raise ValueError('Invalid key')
                await page.keyboard.press(key)
            elif action == 'text':
                text = str(body.get('text', ''))
                if len(text) > 20000:
                    raise ValueError('Paste up to 20,000 characters at a time')
                await page.keyboard.insert_text(text)
            elif action == 'unmute':
                for frame in page.frames:
                    with contextlib.suppress(Exception):
                        await frame.evaluate('''() => {
                            for (const media of document.querySelectorAll('audio,video')) {
                                media.muted = false;
                                if (media.volume === 0) media.volume = 1;
                            }
                        }''')
            elif action == 'selection':
                return {'text': await page.evaluate('''() => {
                    const element = document.activeElement;
                    if (element && typeof element.selectionStart === 'number' && typeof element.value === 'string')
                        return element.value.slice(element.selectionStart, element.selectionEnd);
                    return window.getSelection()?.toString() || '';
                }''')}
            else:
                raise ValueError('Unsupported browser action')
            return {'ok': True}

    async def close(self):
        if self.task:
            self.task.cancel()
        await self.stop_stream()
        for task in tuple(self.frame_tasks):
            task.cancel()
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
