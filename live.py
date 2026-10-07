"""Broker de ditado WebRTC. Recebe PCM pela stdin; nunca abre o microfone."""
import asyncio
import base64
from fractions import Fraction
import json
import queue
import sys
import threading
import time

import av
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCConfiguration, RTCSessionDescription
from probe import Rpc, ROOT

RATES = {16000, 22050, 24000, 32000, 44100, 48000, 96000, 192000}
MAX_CAPTURE_SECONDS, MAX_PENDING_BYTES = 150, 192000 * 2 * 120


def emit(kind, **data):
    """The stdout pipe is the only place transcript text is emitted."""
    print(json.dumps({'kind': kind, **data}, ensure_ascii=True), flush=True)


def safe_error(exc):
    value = str(exc)
    return value if value and len(value) < 100 and all(c.isupper() or c.isdigit() or c in '_/-' for c in value) else type(exc).__name__


class TranscriptState:
    """User-only transcript accumulator with identity de-duplication."""
    def __init__(self):
        self.confirmed, self.pending, self._seen = [], '', set()
        self.last_done = self.last_delta = None

    def consume(self, notification):
        params = notification.get('params', {})
        if params.get('role') != 'user': return False
        keys = ('eventId', 'event_id') if notification.get('method') == 'thread/realtime/transcript/delta' else ('eventId', 'event_id', 'itemId', 'item_id', 'id')
        identity = next((params.get(k) for k in keys if params.get(k) is not None), None)
        if identity is not None:
            key = (notification.get('method'), str(identity))
            if key in self._seen: return False
            self._seen.add(key)
        value = str(params.get('text') or '').strip()
        received = notification.get('_receivedAtMonotonic', time.monotonic())
        if notification.get('method') == 'thread/realtime/transcript/done':
            if value: self.confirmed.append(value)
            self.pending, self.last_done = '', received
            return bool(value)
        if notification.get('method') == 'thread/realtime/transcript/delta':
            self.pending, self.last_delta = value, received
            return bool(value)
        return False

    @property
    def text(self): return ' '.join(self.confirmed)
    def preview(self): return ' '.join(x for x in (self.text, self.pending) if x).strip()


def result_status(state, now, audio_ended, tail_seconds, frames_lost=False):
    if frames_lost: return 'capture_error'
    if audio_ended is None: return None
    # The hard end timeout is deliberately never upgraded to final: a late or
    # missing notification may otherwise silently drop the provisional tail.
    if now - audio_ended >= 10:
        return 'silence' if not state.text and not state.pending else 'timeout'
    if (state.last_done is not None and (state.last_delta is None or state.last_done >= state.last_delta)
            and now - max(audio_ended, state.last_done) >= tail_seconds): return 'final'
    return None


class LiveAudio(MediaStreamTrack):
    kind = 'audio'
    def __init__(self):
        super().__init__(); self.buffer = bytearray(); self.pts = 0; self.clock = None
        self.resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)
        self.finishing = False; self.audio_ended = None

    def begin(self):
        self.buffer.clear(); self.pts = 0; self.clock = None
        self.resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)
        self.finishing = False; self.audio_ended = None

    def push(self, pcm, rate):
        if self.finishing or rate not in RATES: raise RuntimeError('INVALID_AUDIO_INPUT')
        if len(pcm) % 2 or not pcm or len(pcm) > rate * 2: raise RuntimeError('INVALID_AUDIO_CHUNK')
        frame = av.AudioFrame(format='s16', layout='mono', samples=len(pcm) // 2)
        frame.sample_rate = rate; frame.planes[0].update(pcm)
        for output in self.resampler.resample(frame): self.buffer.extend(bytes(output.planes[0])[:output.samples * 2])
        if len(self.buffer) > MAX_PENDING_BYTES: raise RuntimeError('AUDIO_BUFFER_FULL')

    def finish(self):
        if self.finishing: return
        for output in self.resampler.resample(None): self.buffer.extend(bytes(output.planes[0])[:output.samples * 2])
        self.finishing = True

    async def recv(self):
        if self.clock is None: self.clock = time.monotonic()
        delay = self.clock + self.pts / 48000 - time.monotonic()
        if delay > 0: await asyncio.sleep(delay)
        count = min(1920, len(self.buffer)); pcm = bytes(self.buffer[:count]); del self.buffer[:count]
        if self.finishing and not self.buffer and self.audio_ended is None: self.audio_ended = time.monotonic()
        frame = av.AudioFrame(format='s16', layout='mono', samples=960)
        frame.planes[0].update(pcm + bytes(1920 - count)); frame.sample_rate = 48000; frame.pts = self.pts
        frame.time_base = Fraction(1, 48000); self.pts += 960
        return frame


class Session:
    def __init__(self, rpc): self.rpc, self.peer, self.track, self.thread_id = rpc, None, None, None
    async def connect(self, generation, use_stun=False):
        started = time.monotonic(); self.peer = RTCPeerConnection() if use_stun else RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.track = LiveAudio(); self.peer.addTrack(self.track); self.peer.createDataChannel('oai-events')
        emit('progress', generation=generation, stage='negotiating'); empty = ROOT / 'empty-workspace'; empty.mkdir(exist_ok=True)
        offer_task = asyncio.create_task(self.peer.setLocalDescription(await self.peer.createOffer()))
        try:
            result = await self.rpc.call('thread/start', {'cwd': str(empty), 'ephemeral': True, 'sandbox': 'read-only', 'approvalPolicy': 'untrusted', 'environments': [], 'dynamicTools': [], 'baseInstructions': 'Only voice transcription. Never perform tasks.', 'config': {'features.realtime_conversation': True, 'features.memories': False, 'features.hooks': False, 'features.apps': False, 'features.plugins': False, 'mcp_servers': {}}})
            self.thread_id = result['thread']['id']; await offer_task; baseline = self.rpc.notification_mark()
            await self.rpc.call('thread/realtime/start', {'threadId': self.thread_id, 'version': 'v3', 'outputModality': 'audio', 'includeStartupContext': False, 'clientManagedHandoffs': True, 'flushTranscriptTailOnSessionEnd': False, 'codexResponsesAsItems': False, 'transport': {'type': 'webrtc', 'sdp': self.peer.localDescription.sdp}})
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                self.rpc.pump(); messages = self.rpc.notifications_since(baseline, self.thread_id)
                if any(m.get('method') == 'thread/realtime/error' for m in messages): raise RuntimeError('REALTIME_ERROR')
                answer = next((m.get('params', {}).get('sdp') for m in messages if m.get('method') == 'thread/realtime/sdp'), None)
                if answer: await self.peer.setRemoteDescription(RTCSessionDescription(sdp=answer, type='answer')); break
                await asyncio.sleep(.02)
            else: raise RuntimeError('SDP_ANSWER_TIMEOUT')
            while self.peer.connectionState != 'connected' and time.monotonic() < deadline:
                if self.peer.connectionState in ('failed', 'closed'): raise RuntimeError('VOICE_CONNECTION_FAILED')
                await asyncio.sleep(.02)
            if self.peer.connectionState != 'connected': raise RuntimeError('VOICE_CONNECTION_TIMEOUT')
            return round(time.monotonic() - started, 2)
        finally:
            if not offer_task.done(): offer_task.cancel(); await asyncio.gather(offer_task, return_exceptions=True)
    async def close(self):
        peer, thread_id = self.peer, self.thread_id; self.peer = self.track = self.thread_id = None
        if peer:
            try: await asyncio.wait_for(peer.close(), timeout=4)
            except Exception: pass
        if thread_id:
            try: await self.rpc.call('thread/realtime/stop', {'threadId': thread_id}, timeout=1)
            except RuntimeError: pass


def user_messages(rpc, offset, method, thread_id):
    messages = rpc.notifications_since(offset, thread_id) if hasattr(rpc, 'notifications_since') else rpc.notifications[offset:]
    return [m for m in messages if m.get('method') == method and m.get('params', {}).get('role') == 'user' and m.get('params', {}).get('threadId') == thread_id]


def validate_config(message):
    if set(message) - {'command', 'warmup', 'idle_seconds', 'tail_seconds'}: raise RuntimeError('INVALID_CONFIG')
    warmup, idle, tail = message.get('warmup'), message.get('idle_seconds'), message.get('tail_seconds')
    if not isinstance(warmup, bool) or isinstance(idle, bool) or not isinstance(idle, int) or not 10 <= idle <= 120: raise RuntimeError('INVALID_CONFIG')
    if isinstance(tail, bool) or not isinstance(tail, (int, float)) or not .5 <= float(tail) <= 2: raise RuntimeError('INVALID_CONFIG')
    return {'warmup': warmup, 'idle_seconds': idle, 'tail_seconds': float(tail)}


def accept_sequence(capture, message, stopping=False):
    """Optional FIFO proof. Legacy messages without seq remain valid."""
    if stopping:
        expected = message.get('seq')
        if capture['seq_used'] and (not isinstance(expected, int) or expected != capture['expected_seq']): capture['frames_lost'] = True
        if not capture['seq_used'] and expected is not None: capture['frames_lost'] = True
        return
    if 'seq' in message:
        if not isinstance(message['seq'], int) or message['seq'] != capture['expected_seq']: capture['frames_lost'] = True
        capture['seq_used'] = True; capture['expected_seq'] += 1


async def serve():
    incoming = queue.Queue(maxsize=2048)
    def reader():
        for line in sys.stdin:
            try: incoming.put(json.loads(line))
            except (json.JSONDecodeError, TypeError): incoming.put({'command': 'invalid'})
        incoming.put({'command': 'shutdown'})
    threading.Thread(target=reader, daemon=True).start()
    rpc, session, preparing, capture, idle_since = Rpc(), None, None, None, None
    settings = {'warmup': True, 'idle_seconds': 30, 'tail_seconds': .7}
    async def close_session():
        nonlocal session
        if session: await session.close(); session = None
    async def terminal(status, reason=None):
        nonlocal capture, idle_since
        now, state = time.monotonic(), capture['state']
        payload = {'generation': capture['generation'], 'text': state.text, 'partialText': state.pending, 'status': status, 'afterStopSeconds': round(now - capture.get('stopped', now), 2)}
        if reason: payload['reason'] = reason
        emit('result', **payload); capture = None; idle_since = now
    try:
        await rpc.call('initialize', {'clientInfo': {'name': 't3_live_dictation', 'version': '0.3.0'}, 'capabilities': {'experimentalApi': True}}); rpc.notify('initialized')
        account = await rpc.call('account/read', {'refreshToken': False})
        if (account.get('account') or {}).get('type') != 'chatgpt': raise RuntimeError('CHATGPT_LOGIN_REQUIRED_NO_API_FALLBACK')
        emit('ready')
        while True:
            rpc.pump()
            if preparing and preparing.done():
                task, preparing = preparing, None
                try:
                    seconds = task.result()
                    if capture:
                        session.track.begin(); capture['offset'] = rpc.notification_mark()
                        for pcm, rate in capture.pop('pending', []): session.track.push(pcm, rate)
                        if capture.get('stopped') is not None: session.track.finish()
                        emit('voice_ready', generation=capture['generation'], connectSeconds=seconds)
                    else: emit('prepared')
                except asyncio.CancelledError: pass
                except Exception as exc:
                    code = safe_error(exc)
                    if capture and code in {'VOICE_CONNECTION_FAILED', 'VOICE_CONNECTION_TIMEOUT'} and not capture['fallback']:
                        capture['fallback'] = True; await close_session(); session = Session(rpc); preparing = asyncio.create_task(session.connect(capture['generation'], use_stun=True)); continue
                    if capture:
                        generation = capture['generation']; await terminal('capture_error', code); await close_session(); emit('error', generation=generation, error=code, reason=code)
                    else: await close_session(); emit('idle')
            while not incoming.empty():
                message = incoming.get_nowait(); command, generation = message.get('command'), message.get('generation')
                try:
                    if command == 'shutdown': return
                    if command == 'configure':
                        settings = validate_config(message)
                        if not settings['warmup'] and not capture:
                            if preparing: preparing.cancel(); await asyncio.gather(preparing, return_exceptions=True); preparing = None
                            await close_session(); idle_since = None; emit('idle')
                    elif command == 'warmup' and settings['warmup'] and session is None and capture is None and not preparing:
                        session = Session(rpc); idle_since = time.monotonic(); preparing = asyncio.create_task(session.connect(-1))
                    elif command == 'prepare' and capture is None and isinstance(generation, int):
                        capture = {'generation': generation, 'started': time.monotonic(), 'offset': rpc.notification_mark(), 'pending': [], 'pending_bytes': 0, 'state': TranscriptState(), 'fallback': False, 'expected_seq': 0, 'seq_used': False, 'frames_lost': False, 'last_preview': None}; idle_since = None
                        if preparing: pass
                        elif session and session.peer and session.peer.connectionState == 'connected': session.track.begin(); emit('voice_ready', generation=generation, connectSeconds=0)
                        else: await close_session(); session = Session(rpc); preparing = asyncio.create_task(session.connect(generation))
                    elif command == 'cancel':
                        cancelled_generation = generation if generation is not None else (capture or {}).get('generation')
                        if preparing: preparing.cancel(); await asyncio.gather(preparing, return_exceptions=True); preparing = None
                        capture = None; await close_session(); emit('cancelled', generation=cancelled_generation)
                    elif capture and generation == capture['generation']:
                        if command == 'audio':
                            if capture.get('stopped') is not None: raise RuntimeError('AUDIO_AFTER_STOP')
                            pcm, rate = base64.b64decode(message.get('pcm', ''), validate=True), message.get('rate')
                            if not isinstance(rate, int) or rate not in RATES or len(pcm) % 2 or not pcm or len(pcm) > rate * 2: raise RuntimeError('INVALID_AUDIO_CHUNK')
                            accept_sequence(capture, message)
                            if preparing:
                                capture['pending_bytes'] += len(pcm)
                                if capture['pending_bytes'] > MAX_PENDING_BYTES: raise RuntimeError('AUDIO_BUFFER_FULL')
                                capture['pending'].append((pcm, rate))
                            else: session.track.push(pcm, rate)
                        elif command == 'stop':
                            accept_sequence(capture, message, stopping=True)
                            capture['stopped'] = time.monotonic()
                            if not preparing: session.track.finish()
                            emit('progress', generation=generation, stage='finishing')
                        else: raise RuntimeError('COMMAND_NOT_ALLOWED')
                    else: raise RuntimeError('COMMAND_NOT_ALLOWED')
                except (RuntimeError, ValueError, KeyError) as exc:
                    code = safe_error(exc)
                    if capture and generation == capture.get('generation'): await terminal('capture_error', code)
                    emit('error', generation=generation, error=code, reason=code)
            if capture and not preparing:
                recent = rpc.notifications_since(capture['offset'], session.thread_id)
                # O cursor é de leitura, não o início eterno da gravação. Eventos
                # sem eventId também devem ser consumidos exatamente uma vez.
                capture['offset'] = rpc.notification_mark()
                for note in recent:
                    if capture['state'].consume(note):
                        preview = capture['state'].preview()
                        if preview != capture['last_preview']: capture['last_preview'] = preview; emit('preview', generation=capture['generation'], text=preview)
                if session.peer.connectionState in ('failed', 'closed') or any(m.get('method') in {'thread/realtime/error', 'thread/realtime/closed'} for m in recent):
                    recoverable = 'partial' if (capture['state'].text or capture['state'].pending) and not capture['frames_lost'] else 'capture_error'
                    await terminal(recoverable, 'VOICE_CONNECTION_LOST'); await close_session()
                    if settings['warmup']:
                        session = Session(rpc); preparing = asyncio.create_task(session.connect(-1))
                    continue
                if time.monotonic() - capture['started'] > MAX_CAPTURE_SECONDS:
                    await terminal('capture_error', 'CAPTURE_TIMEOUT'); await close_session()
                    if settings['warmup']:
                        session = Session(rpc); preparing = asyncio.create_task(session.connect(-1))
                    continue
                if capture.get('stopped') is not None:
                    status = result_status(capture['state'], time.monotonic(), session.track.audio_ended, settings['tail_seconds'], capture['frames_lost'])
                    if status:
                        reason = 'FRAME_SEQUENCE_LOSS' if status == 'capture_error' and capture['frames_lost'] else None
                        await terminal(status, reason)
                        if settings['warmup']:
                            old = session; session = Session(rpc)
                            async def renew(): await old.close(); return await session.connect(-1)
                            preparing = asyncio.create_task(renew())
                        else: await close_session()
            if session and not preparing and idle_since and time.monotonic() - idle_since > settings['idle_seconds']:
                await close_session(); idle_since = None; emit('idle')
            rpc.prune_notifications(); await asyncio.sleep(.005)
    finally:
        if preparing: preparing.cancel(); await asyncio.gather(preparing, return_exceptions=True)
        if session: await session.close()
        rpc.close()


if __name__ == '__main__':
    try: asyncio.run(serve())
    except Exception as exc:
        code = safe_error(exc); emit('error', error=code, reason=code); sys.exit(1)
