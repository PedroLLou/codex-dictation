"""Teste isolado Codex/WebRTC. Nunca captura microfone ou toca áudio de saída."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import queue
import time
import tempfile
import wave
import sys

from runtime_paths import ROOT
BINARY = ROOT / 'target' / 'release' / 'codex-app-server.exe'
ALLOW = {'initialize', 'account/read', 'thread/start', 'thread/realtime/start',
         'thread/realtime/stop'}
PROCESS_OVERRIDES = [
    '-c', 'features.memories=false', '-c', 'features.hooks=false',
    '-c', 'features.apps=false', '-c', 'features.plugins=false',
    '-c', 'mcp_servers={}',
]
MAX_NOTIFICATIONS = 2048

def progress(args, stage, **details):
    if getattr(args, 'progress', False):
        print(json.dumps({'progress': {'stage': stage,
            'elapsed': round(time.monotonic() - getattr(args, '_started', time.monotonic()), 2),
            **details}}, ensure_ascii=True), flush=True)

def transcription_complete(now, audio_ended, last_done, last_delta):
    # Nunca encerra antes de transmitir toda a gravação. Dá tempo para o VAD e
    # exige conclusão depois do último delta de usuário; há limite de espera.
    if audio_ended is None:
        return False
    if now - audio_ended >= 10:
        return True
    return (last_done is not None and last_done >= (last_delta or 0)
            and now - max(audio_ended, last_done) >= 2)

class Rpc:
    def __init__(self, diagnose=False):
        self.incoming = queue.Queue()
        self.pending = {}
        self.next_id = 0
        self.notifications = []
        self._notification_base = 0
        self.method_counts = {}
        self.diagnose = diagnose
        if diagnose:
            binary = shutil.which('codex.cmd')
            args = [binary, 'app-server']
        else:
            stamp = ROOT / 'validated-build.json'
            if not BINARY.exists() or not stamp.exists():
                raise RuntimeError('BUILD_NOT_VALIDATED')
            expected = json.loads(stamp.read_text())['sha256']
            if hashlib.sha256(BINARY.read_bytes()).hexdigest() != expected:
                raise RuntimeError('BUILD_HASH_MISMATCH')
            args = [str(BINARY)]
        # These are documented per-process overrides.  They retain AuthManager's
        # managed account lookup but stop optional global integrations from loading.
        self.proc = subprocess.Popen(args + PROCESS_OVERRIDES + ['--listen', 'stdio://'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            try:
                self.incoming.put(json.loads(line))
            except json.JSONDecodeError:
                pass

    def notify(self, method):
        if method != 'initialized':
            raise RuntimeError('NOTIFICATION_NOT_ALLOWED')
        self.proc.stdin.write(json.dumps({'method': method}) + '\n')
        self.proc.stdin.flush()

    def collect(self, message):
        method = message.get('method', '')
        if method:
            self.method_counts[method] = self.method_counts.get(method, 0) + 1
            if 'id' in message:
                # Recusa todas as solicitações de ferramentas/approval/auth refresh externas.
                self.proc.stdin.write(json.dumps({'id': message['id'], 'error':
                    {'code': -32601, 'message': 'Unavailable in dictation probe'}}) + '\n')
                self.proc.stdin.flush()
            else:
                message['_receivedAtMonotonic'] = time.monotonic()
                self.notifications.append(message)
            if method in {'turn/started', 'item/started'}:
                raise RuntimeError('UNEXPECTED_AGENT_ACTIVITY')
        elif 'id' in message:
            self.pending[message['id']] = message

    def pump(self):
        while not self.incoming.empty():
            self.collect(self.incoming.get_nowait())

    def notification_mark(self):
        """Stable absolute cursor, safe even after old notifications are pruned."""
        return self._notification_base + len(self.notifications)

    def notifications_since(self, mark, thread_id=None):
        start = max(0, mark - self._notification_base)
        messages = self.notifications[start:]
        return messages if thread_id is None else [m for m in messages if m.get('params', {}).get('threadId') == thread_id]

    def prune_notifications(self):
        """Keep enough history for active marks without invalidating their indexes."""
        excess = len(self.notifications) - MAX_NOTIFICATIONS
        if excess > 0:
            del self.notifications[:excess]
            self._notification_base += excess

    async def call(self, method, params, timeout=40):
        if method not in ALLOW or (self.diagnose and method not in {'initialize','account/read'}):
            raise RuntimeError('RPC_NOT_ALLOWED')
        if method == 'thread/start' and (params.get('ephemeral') is not True or params.get('sandbox') != 'read-only'):
            raise RuntimeError('ISOLATION_REQUIRED')
        self.next_id += 1
        request_id = self.next_id
        self.proc.stdin.write(json.dumps({'id': request_id, 'method': method, 'params': params}) + '\n')
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if request_id in self.pending:
                result = self.pending.pop(request_id)
                if 'error' in result:
                    # Não registra respostas brutas: podem conter dados de autenticação.
                    raise RuntimeError('RPC_ERROR_' + str(result['error'].get('code', 'UNKNOWN')))
                return result.get('result', {})
            if self.proc.poll() is not None:
                raise RuntimeError('APP_SERVER_EXITED')
            await asyncio.sleep(.03)
        raise RuntimeError('RPC_TIMEOUT_' + method)

    def close(self):
        if self.proc.poll() is not None:
            return
        try:
            self.proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self.proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)

async def run(args):
    total_started = time.monotonic()
    args._started = total_started
    progress(args, 'starting')
    rpc = Rpc(diagnose=args.diagnose)
    peer = None
    player = None
    padded_file = None
    thread_id = None
    try:
        await rpc.call('initialize', {'clientInfo': {'name': 't3_dictation_probe', 'version': '0.1.0'},
            'capabilities': {'experimentalApi': True}})
        rpc.notify('initialized')
        account = await rpc.call('account/read', {'refreshToken': False})
        account_type = (account.get('account') or {}).get('type')
        if account_type != 'chatgpt':
            raise RuntimeError('CHATGPT_LOGIN_REQUIRED_NO_API_FALLBACK')
        if args.diagnose:
            return {'initialize': 'ok', 'accountType': account_type,
                    'audioSent': False, 'realtimeStarted': False}
        progress(args, 'negotiating')
        from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack, RTCConfiguration
        from aiortc.mediastreams import MediaStreamError
        from aiortc.contrib.media import MediaPlayer
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[])) if getattr(args, 'no_stun', False) else RTCPeerConnection()
        # WAV explícito, sem abrir microfone. Silêncio final permite que o VAD finalize
        # a última frase antes de a faixa RTP chegar ao fim.
        with wave.open(str(Path(args.synthetic_file).resolve()), 'rb') as source:
            params = source.getparams()
            if params.nframes > params.framerate * 120:
                raise RuntimeError('AUDIO_TOO_LONG')
            pcm = source.readframes(params.nframes)
        fd, padded_file = tempfile.mkstemp(suffix='.wav', prefix='codex-dictation-')
        os.close(fd)
        with wave.open(padded_file, 'wb') as destination:
            destination.setparams(params)
            destination.writeframes(pcm + bytes(params.framerate * params.sampwidth * params.nchannels * 2))
        player = MediaPlayer(padded_file)
        if player.audio is None:
            raise RuntimeError('AUDIO_TRACK_MISSING')
        transfer = {'started': None, 'ended': None}
        class TrackedAudio(MediaStreamTrack):
            kind = 'audio'
            async def recv(self):
                if transfer['started'] is None:
                    transfer['started'] = time.monotonic()
                    progress(args, 'sending', seconds=round(params.nframes / params.framerate, 1))
                try:
                    return await player.audio.recv()
                except MediaStreamError:
                    transfer['ended'] = time.monotonic()
                    progress(args, 'finishing')
                    raise
        peer.addTrack(TrackedAudio())
        peer.createDataChannel('oai-events')
        await peer.setLocalDescription(await peer.createOffer())
        empty = ROOT / 'empty-workspace'
        empty.mkdir(exist_ok=True)
        started = await rpc.call('thread/start', {'cwd': str(empty), 'ephemeral': True,
            'sandbox': 'read-only', 'approvalPolicy': 'untrusted', 'environments': [],
            'dynamicTools': [], 'baseInstructions': 'Only a voice transcription probe. Never perform tasks.',
            'config': {'features.realtime_conversation': True, 'features.memories': False,
                       'features.hooks': False, 'features.apps': False, 'features.plugins': False,
                       'mcp_servers': {}}})
        thread_id = started['thread']['id']
        await rpc.call('thread/realtime/start', {'threadId': thread_id, 'version': args.version,
            'outputModality': 'audio', 'includeStartupContext': False,
            'clientManagedHandoffs': True, 'flushTranscriptTailOnSessionEnd': False,
            'codexResponsesAsItems': False,
            'transport': {'type': 'webrtc', 'sdp': peer.localDescription.sdp}})
        deadline = time.monotonic() + 40
        answer = None
        while answer is None and time.monotonic() < deadline:
            rpc.pump()
            if any(m.get('method') == 'thread/realtime/error' for m in rpc.notifications):
                raise RuntimeError('REALTIME_ERROR')
            if any(m.get('method') == 'thread/realtime/closed' for m in rpc.notifications):
                raise RuntimeError('REALTIME_CLOSED')
            answer = next((m['params']['sdp'] for m in rpc.notifications
                           if m.get('method') == 'thread/realtime/sdp'), None)
            await asyncio.sleep(.05)
        if not answer:
            raise RuntimeError('SDP_ANSWER_TIMEOUT')
        await peer.setRemoteDescription(RTCSessionDescription(sdp=answer, type='answer'))
        audio_connected_at = time.monotonic()
        # Não anexa consumer/player para áudio remoto: nenhuma reprodução local.
        deadline = time.monotonic() + params.nframes / params.framerate + 45
        seen = 0
        while time.monotonic() < deadline:
            rpc.pump()
            if any(m.get('method') == 'thread/realtime/error' for m in rpc.notifications):
                raise RuntimeError('REALTIME_ERROR')
            user_done = [m for m in rpc.notifications
                         if m.get('method') == 'thread/realtime/transcript/done'
                         and m.get('params', {}).get('role') == 'user']
            user_delta = [m for m in rpc.notifications
                          if m.get('method') == 'thread/realtime/transcript/delta'
                          and m.get('params', {}).get('role') == 'user']
            if len(user_done) != seen:
                seen = len(user_done)
                progress(args, 'recognized', segments=seen)
            if transcription_complete(time.monotonic(), transfer['ended'],
                    user_done[-1]['_receivedAtMonotonic'] if user_done else None,
                    user_delta[-1]['_receivedAtMonotonic'] if user_delta else None):
                break
            await asyncio.sleep(.05)
        if transfer['ended'] is None:
            raise RuntimeError('AUDIO_TRANSFER_TIMEOUT')
        progress(args, 'closing')
        await rpc.call('thread/realtime/stop', {'threadId': thread_id})
        rpc.pump()
        transcript_done = [m.get('params', {}) for m in rpc.notifications
                           if m.get('method') == 'thread/realtime/transcript/done']
        transcripts = [params['text'] for params in transcript_done
                       if params.get('role') == 'user']
        user_transcript_times = [m['_receivedAtMonotonic'] for m in rpc.notifications
                                 if m.get('method') == 'thread/realtime/transcript/done'
                                 and m.get('params', {}).get('role') == 'user']
        input_speech_started = sum(
            1 for m in rpc.notifications
            if m.get('method') == 'thread/realtime/itemAdded'
            and m.get('params', {}).get('item', {}).get('type')
                == 'input_audio_buffer.speech_started')
        return {'accountType': account_type, 'version': args.version, 'audioSent': True,
            'totalSeconds': round(time.monotonic() - total_started, 2),
            'userTranscripts': transcripts,
            'userTranscriptDone': sum(params.get('role') == 'user' for params in transcript_done),
            'assistantTranscriptDone': sum(params.get('role') == 'assistant' for params in transcript_done),
            'inputSpeechStarted': input_speech_started,
            'firstUserTranscriptAfterSdpMs': (
                round((min(user_transcript_times) - audio_connected_at) * 1000)
                if user_transcript_times else None),
            'notificationCounts': rpc.method_counts,
            'speakerUsed': False, 'microphoneUsed': False}
    finally:
        if player and player.audio:
            player.audio.stop()
        if peer:
            await peer.close()
        rpc.close()
        if padded_file:
            Path(padded_file).unlink(missing_ok=True)

async def entry(args):
    task = asyncio.create_task(run(args))
    if args.cancellable:
        loop = asyncio.get_running_loop()
        def monitor_cancel():
            for line in sys.stdin:
                if line.strip() == 'cancel':
                    loop.call_soon_threadsafe(task.cancel)
                    break
        threading.Thread(target=monitor_cancel, daemon=True).start()
    try:
        return await task
    except asyncio.CancelledError:
        return {'cancelled': True}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--synthetic-file', '--audio-file', dest='synthetic_file')
    parser.add_argument('--version', choices=['v1', 'v3'], default='v3')
    parser.add_argument('--cancellable', action='store_true')
    parser.add_argument('--progress', action='store_true')
    parser.add_argument('--no-stun', action='store_true')
    args = parser.parse_args()
    if not args.diagnose and not args.synthetic_file:
        parser.error('Use --diagnose ou --synthetic-file (após validar build).')
    try:
        result = asyncio.run(entry(args))
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:
        # Somente nossos códigos de erro, nunca payloads/SDP/credenciais.
        error = str(exc)
        safe_code = all(c.isupper() or c.isdigit() or c in '_/-' for c in error)
        print(json.dumps({'error': error if safe_code and len(error) < 100 else type(exc).__name__}))
        raise SystemExit(1)
