"""Interface de ditado. Captura apenas por ação explícita; texto e áudio em RAM."""
import hashlib
import json
import queue
import threading
import time
import os
import webbrowser
from desktop_integration import create_shortcut, startup_enabled, set_startup
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sounddevice as sd
from audio_capture import AudioCapture
from backend_client import BackendClient
from settings import SettingsStore, apply_dictionary, parse_dictionary, format_dictionary
from i18n import tr
import ui_theme
import customtkinter as ctk
from app_identity import prepare_identity, apply_window_icon
from win_integration import InstanceGuard, Hotkeys, Tray, capture_target, paste_text, make_nonactivating, foreground_is_t3

from runtime_paths import ROOT
TITLE = 'Ditado Codex — v2'

def load_model():
    expected = json.loads((ROOT / 'validated-build.json').read_text())['sha256']
    digest = hashlib.sha256()
    with (ROOT / 'target/release/codex-app-server.exe').open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''): digest.update(chunk)
    if digest.hexdigest() != expected: raise RuntimeError('A cópia do Codex não corresponde ao binário validado.')
    return True

class App:
    def __init__(self, root, start_services=True, settings_store=None):
        self.root, self.store = root, settings_store or SettingsStore()
        self.prefs = self.store.load()
        self.events = queue.Queue()
        self.client = self.hotkeys = self.tray = None
        self.epoch = self.generation = self.sequence = 0
        self.ready = self.recording = self.busy = self.closing = False
        self.retained = self.target = None
        self.partial = ''
        self.history = []
        self.replay_cancel = threading.Event()
        self.capture = AudioCapture(self.audio_chunk)
        self.last_correction = None
        self.cancel_deadline = None
        self.reconnecting = False
        self.failed_generations = set()
        self.terminal_generations = set()
        self.mini = None
        self.mini_visible = False
        self.mini_visibility_check = 0
        self.mini_tooltips = []
        self.capture_auto_paste = False
        root.title(TITLE)
        prepare_identity(); apply_window_icon(root)
        root.attributes('-topmost', self.prefs['topmost'])
        ui_theme.build(self, root, start_services)
        self.refresh_devices(); self.update_controls()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(40, self.poll)
        if start_services:
            self.install_windows()
            threading.Thread(target=self.verify, daemon=True).start()

    def set_status(self, value):
        self.status.set(tr(value, self.prefs.get('language', 'pt-BR')))

    def text_widget(self, parent, height, **kwargs):
        widget = tk.Text(parent, height=height, bg='#222936', fg='#edf4ff', insertbackground='#edf4ff', relief='flat', padx=10, pady=8, wrap='word', font=('Segoe UI', 11), **kwargs)
        widget.pack(fill='both', expand=True, pady=(4, 0)); return widget

    def refresh_devices(self):
        if self.recording or self.busy: return
        try:
            devices = sd.query_devices()
            self.devices = [(i, d, f"{d['name']}|{sd.query_hostapis(d['hostapi'])['name']}") for i, d in enumerate(devices) if d['max_input_channels']]
            self.device_box['values'] = [key.replace('|', ' · ') for _, _, key in self.devices]
            selected = next((n for n, (_, _, key) in enumerate(self.devices) if key == self.prefs['microphone']), None)
            if selected is None and not self.prefs['microphone']:
                default = int(sd.default.device[0])
                selected = next((n for n, (i, _, _) in enumerate(self.devices) if i == default), 0 if self.devices else None)
            self.device_box.set('')
            if selected is not None: self.device_box.current(selected)
            elif self.prefs['microphone']: self.set_status('O microfone salvo não está disponível. Selecione outro.')
        except Exception: self.devices = []; self.set_status('Não foi possível listar os microfones.')

    def save_device(self, _=None):
        index = self.device_box.current()
        if index >= 0:
            self.prefs['microphone'] = self.devices[index][2]
            try: self.store.save(self.prefs)
            except OSError: self.set_status('Microfone selecionado; não foi possível salvar a preferência.')

    def save_quick_preference(self, key):
        previous = self.prefs[key]
        try:
            data = dict(self.prefs); data[key] = self.quick_prefs[key].get()
            self.prefs = self.store.save(data)
            if key == 'topmost': self.root.attributes('-topmost', self.prefs[key])
        except OSError:
            self.quick_prefs[key].set(previous)
            self.set_status('Não foi possível salvar a opção. Tente novamente.')

    def install_windows(self):
        if self.hotkeys: self.hotkeys.close()
        try:
            self.hotkeys = Hotkeys(lambda action: self.events.put(('action', (action, capture_target() if (self.prefs['auto_paste'] or self.mini) and not self.recording and not self.busy and action in ('toggle', 'start') else None))), self.prefs['hotkey'], self.prefs['hotkey_mode'])
            self.hotkeys.start()
        except Exception as exc: self.hotkeys = None; self.set_status(f'Atalho indisponível: {exc}. Use o botão Gravar.')
        if not self.tray:
            self.tray = Tray(lambda action: self.events.put(('action', (action, None))), language=self.prefs['language'])
            if not self.tray.start(): self.tray = None
        self.update_controls()

    def verify(self):
        try: load_model(); self.events.put(('verified', None))
        except Exception as exc: self.events.put(('failure', str(exc)))

    def desktop_shortcut(self):
        try:
            create_shortcut(); self.set_status('Atalho criado na área de trabalho.')
        except Exception: self.set_status('Não foi possível criar o atalho. Abra o executável diretamente.')

    def open_help(self):
        webbrowser.open('https://github.com/PedroLLou/codex-dictation#readme')

    def connect(self):
        self.epoch += 1; epoch = self.epoch
        self.client = BackendClient(lambda message: self.events.put(('backend', (epoch, message))))
        self.client.start(); self.ready = False; self.set_status('Conectando ao serviço…'); self.update_controls()

    def configure_backend(self):
        self.client.send({'command': 'configure', **{k: self.prefs[k] for k in ('warmup', 'idle_seconds', 'tail_seconds')}})
        if self.prefs['warmup']: self.client.send({'command': 'warmup'})

    def audio_chunk(self, samples, rate):
        self.client.send_audio(samples, rate, self.generation, self.sequence); self.sequence += 1

    def toggle(self, target=None):
        if self.recording: self.stop()
        elif not self.busy: self.start(target)

    def enter_mini(self):
        if self.mini or self.recording or self.busy: return
        self.full_geometry = self.root.geometry()
        window = ctk.CTkToplevel(self.root)
        window.withdraw(); window.title('Ditado Codex — mini'); window.overrideredirect(True)
        apply_window_icon(window)
        window.configure(fg_color='#010102'); window.attributes('-transparentcolor','#010102')
        x = min(self.root.winfo_x(), self.root.winfo_screenwidth()-190)
        y = min(self.root.winfo_y(), self.root.winfo_screenheight()-74)
        window.geometry(f'178x66+{max(0,x)}+{max(0,y)}')
        panel = ctk.CTkFrame(window,fg_color=ui_theme.BG,corner_radius=19,border_width=1,border_color=ui_theme.LINE); panel.pack(fill='both',expand=True)
        self.mini_record = ui_theme.button(panel,'',self.mini_toggle,primary=True,width=46,image=self.icons['mic'])
        self.mini_record.configure(height=46,corner_radius=12); self.mini_record.pack(side='left',padx=(10,8),pady=10)
        from mini_meter import MiniMeter
        self.mini_meter = MiniMeter(panel); self.mini_meter.pack(side='left',padx=(0,10))
        back = ui_theme.button(panel,'',self.exit_mini,width=40,image=self.icons['expand'])
        back.configure(height=40,fg_color=ui_theme.BG,corner_radius=10); back.pack(side='left',padx=(0,10),pady=10)
        from ui_icons import Tooltip
        self.mini_tooltips = [Tooltip(self.mini_record,self.status), Tooltip(back,tr('Sair do modo mini', self.prefs['language']))]
        # Arraste o fundo; os dois botões continuam livres para clicar.
        def drag_start(event): self.mini_drag = (event.x_root-window.winfo_x(),event.y_root-window.winfo_y())
        def drag_move(event):
            dx,dy=self.mini_drag; window.geometry(f'+{max(0,event.x_root-dx)}+{max(0,event.y_root-dy)}')
        panel.bind('<ButtonPress-1>',drag_start); panel.bind('<B1-Motion>',drag_move)
        self.mini_meter.bind('<ButtonPress-1>',drag_start); self.mini_meter.bind('<B1-Motion>',drag_move)
        window.update_idletasks()
        try: make_nonactivating(window, taskbar=True)
        except Exception:
            window.destroy(); self.set_status('Não foi possível abrir o modo mini nesta sessão.'); return
        self.mini = window; self.root.withdraw()
        self.mini_visible = False; self.mini_visibility_check = 0
        self.sync_mini_visibility(); self.update_controls()

    def sync_mini_visibility(self):
        if not self.mini: return
        try: visible = foreground_is_t3()
        except Exception: visible = False
        if visible == self.mini_visible: return
        if visible:
            self.mini.deiconify()
        else:
            for tooltip in self.mini_tooltips: tooltip.leave()
            self.mini.withdraw()
        self.mini_visible = visible

    def mini_toggle(self):
        if self.recording: self.stop(); return
        if self.busy: return
        try: target = capture_target()
        except Exception: target = None
        if not target or not target.known or target.pid == os.getpid():
            self.set_status('Clique no campo onde deseja escrever e tente novamente.')
            self.mini_record.configure(fg_color='#eea8ad'); return
        self.start(target)

    def exit_mini(self):
        if not self.mini: return
        window,self.mini = self.mini,None
        for tooltip in self.mini_tooltips: tooltip.leave()
        self.mini_tooltips = []; self.mini_visible = False
        window.destroy(); self.root.deiconify(); self.root.geometry(self.full_geometry); self.root.lift()
        self.update_controls()

    def start(self, target=None):
        if not self.ready or self.busy or self.recording: return
        if self.retained and not messagebox.askyesno('Descartar gravação?', 'Há uma gravação pendente. Descartar e iniciar outra?', parent=self.root): return
        index = self.device_box.current()
        if index < 0: self.set_status('Selecione um microfone.'); return
        device, _, key = self.devices[index]
        try:
            info = sd.query_devices(device)
            if f"{info['name']}|{sd.query_hostapis(info['hostapi'])['name']}" != key: raise RuntimeError('Atualize a lista de microfones.')
            self.retained = None; self.partial = ''; self.set_preview('')
            self.generation += 1; self.sequence = 0; self.target = target
            self.capture_auto_paste = bool(self.prefs['auto_paste'] or self.mini)
            self.failed_generations.clear()
            self.client.send({'command': 'prepare', 'generation': self.generation})
            self.capture.start(device, int(info['default_samplerate']), self.prefs['max_record_seconds'])
            self.recording = True; self.started = time.monotonic(); self.set_status('Gravando · fale normalmente')
        except Exception as exc:
            self.capture.stop()
            self.client.interrupt({'command': 'cancel', 'generation': self.generation})
            self.set_status(f'Não foi possível iniciar: {exc}')
        self.update_controls()

    def stop(self):
        if not self.recording: return
        self.capture.stop(); self.recording = False
        self.retained = self.capture.snapshot()
        if not self.capture.has_speech(): self.cancel(); self.set_status('Não detectei áudio suficiente. Tente outra vez.'); return
        self.busy = True
        try: self.client.send({'command': 'stop', 'generation': self.generation, 'seq': self.sequence}); self.set_status('Finalizando a transcrição…')
        except Exception: self.fail('O envio falhou. Você pode recuperar a gravação.')
        self.update_controls()

    def cancel(self):
        if not (self.recording or self.busy or self.retained or self.partial): return
        self.replay_cancel.set(); self.capture.stop(); self.capture.clear()
        self.retained = None; self.partial = ''; self.target = None; self.set_preview('')
        self.recording = False; self.generation += 1
        self.busy = bool(self.client and not self.client.done.is_set())
        if self.busy:
            self.client.interrupt({'command': 'cancel', 'generation': self.generation})
            self.cancel_deadline = time.monotonic() + 6
        self.set_status('Cancelado · nenhuma transcrição inserida'); self.update_controls()

    def fail(self, reason):
        self.failed_generations.add(self.generation)
        if self.recording:
            self.capture.stop(); self.retained = self.capture.snapshot()
        self.recording = self.busy = False; self.target = None
        if self.ready and self.client and not self.client.done.is_set():
            self.busy = True
            self.client.interrupt({'command': 'cancel', 'generation': self.generation})
            self.cancel_deadline = time.monotonic() + 6
        self.set_status(reason); self.update_controls()
        if self.mini: self.exit_mini()

    def recover(self):
        if not self.ready or self.busy or not self.retained or not self.retained['integrity']: return
        self.generation += 1; generation = self.generation; self.target = None; self.sequence = 0
        self.failed_generations.clear()
        self.replay_cancel = threading.Event(); cancel = self.replay_cancel
        self.busy = True; self.partial = ''; self.set_preview(''); self.set_status('Recuperando o áudio guardado…')
        snapshot = self.retained; client = self.client
        def replay():
            try:
                client.send({'command': 'prepare', 'generation': generation})
                seq = 0
                for chunk in snapshot['chunks']:
                    if cancel.is_set(): return
                    client.send_audio(chunk, snapshot['rate'], generation, seq); seq += 1
                    if cancel.wait(len(chunk) / snapshot['rate']): return
                client.send({'command': 'stop', 'generation': generation, 'seq': seq})
            except Exception: self.events.put(('replay_failed', generation))
        threading.Thread(target=replay, daemon=True).start(); self.update_controls()

    def set_preview(self, value):
        self.preview.configure(state='normal'); self.preview.delete('1.0', 'end'); self.preview.insert('1.0', value); self.preview.configure(state='disabled')
        ui_theme.update(self)

    def handle_backend(self, message):
        kind = message.get('kind')
        if kind == 'ready':
            self.ready = True; self.configure_backend(); self.set_status('Pronto · o microfone está desligado'); self.update_controls(); return
        if kind == 'fatal':
            self.ready = False
            self.fail('Entre no Codex com sua conta ChatGPT e clique em Reconectar.' if message.get('error') == 'CHATGPT_LOGIN_REQUIRED_NO_API_FALLBACK' else 'O serviço desconectou. Reconecte para continuar.')
            return
        if message.get('generation') not in (None, self.generation): return
        if kind in ('preview', 'progress') and self.generation in self.terminal_generations: return
        if kind == 'preview': self.set_preview(message.get('text', ''))
        elif kind == 'result':
            if self.generation in self.terminal_generations: return
            self.terminal_generations = {g for g in self.terminal_generations if g >= self.generation - 32}
            self.terminal_generations.add(self.generation)
            was_recording = self.recording
            self.capture.stop()
            if was_recording: self.retained = self.capture.snapshot()
            self.recording = self.busy = False
            status = message.get('status', 'partial')
            if self.generation in self.failed_generations or (was_recording and self.capture.fault) or (self.retained and not self.retained['integrity']): status = 'capture_error'
            if status == 'final' and message.get('text', '').strip():
                self.append_text(message['text'], allow_paste=True)
                self.retained = None; self.capture.clear(); self.partial = ''; self.set_preview('')
                if not self.status.get().startswith(tr('Texto', self.prefs['language'])): self.set_status(f"Concluído · {message.get('afterStopSeconds', 0)} s após parar")
            else:
                self.partial = '\n'.join(filter(None, [message.get('text', '').strip(), message.get('partialText', '').strip()]))
                self.set_preview(self.partial)
                self.set_status('A transcrição não foi confirmada. Recupere a gravação ou revise e use o parcial.' if status != 'silence' else 'Não houve texto confirmado. Você pode tentar recuperar o áudio.')
                if self.mini: self.exit_mini()
            if self.cancel_deadline is not None: self.busy = True
            self.target = None; self.update_controls()
        elif kind == 'progress' and self.busy: self.set_status('Finalizando a transcrição…')
        elif kind == 'cancelled': self.busy = False; self.cancel_deadline = None; self.update_controls()
        elif kind == 'error' and self.recording: self.fail('A conexão falhou. A gravação disponível ficou em memória.')

    def append_text(self, raw, allow_paste=False):
        value = apply_dictionary(raw.strip(), self.prefs['dictionary'], self.prefs['dictionary_enabled'])
        if self.text.get('1.0', 'end-1c'): self.text.insert('end', '\n\n')
        begin = self.text.index('end-1c'); self.text.insert('end', value); end = self.text.index('end-1c')
        self.last_correction = (begin, end, value, raw.strip()) if value != raw.strip() else None
        self.text.see('end'); self.history.append((value, raw.strip())); self.history = self.history[-20:]
        self.history_box.delete(0, 'end')
        for text, _ in self.history: self.history_box.insert('end', text.replace('\n', ' ')[:100])
        if allow_paste and (self.capture_auto_paste or self.prefs['auto_paste']) and self.target:
            ok, reason = paste_text(self.target, value)
            self.set_status('Texto inserido no campo original.' if ok else 'Texto mantido no editor: o campo original não pôde receber a inserção segura.')
            if not ok and self.mini: self.exit_mini()

    def accept_partial(self):
        if self.partial and not self.busy:
            self.append_text(self.partial); self.partial = ''; self.retained = None; self.capture.clear(); self.set_preview(''); self.set_status('Parcial aceito para revisão.'); self.update_controls()

    def undo_correction(self):
        if self.last_correction:
            start, end, value, raw = self.last_correction
            if self.text.get(start, end) == value: self.text.delete(start, end); self.text.insert(start, raw)
            else: self.set_status('O texto foi editado. A correção não será desfeita automaticamente.')
            self.last_correction = None

    def restore_history(self):
        selection = self.history_box.curselection()
        if selection: self.text.insert('end', '\n\n' + self.history[selection[0]][0])
    def copy(self):
        value = self.text.get('1.0', 'end-1c')
        if value: self.root.clipboard_clear(); self.root.clipboard_append(value); self.set_status('Texto copiado.')
    def clear_text(self): self.text.delete('1.0', 'end'); self.last_correction = None
    def export(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.txt', filetypes=[(tr('Texto',self.prefs['language']), '*.txt')])
        if path:
            try: Path(path).write_text(self.text.get('1.0', 'end-1c'), encoding='utf-8'); self.set_status('Texto salvo no arquivo escolhido.')
            except OSError: messagebox.showerror('Salvar', 'Não foi possível salvar o texto.', parent=self.root)

    def update_controls(self):
        self.record_button.configure(text=tr('Parar' if self.recording else 'Gravar', self.prefs['language']), state='normal' if self.recording or (self.ready and not self.busy) else 'disabled')
        self.cancel_button.configure(state='normal' if self.recording or self.busy or self.retained or self.partial else 'disabled')
        self.recover_button.configure(state='normal' if self.ready and not self.busy and not self.recording and self.retained and self.retained['integrity'] else 'disabled')
        self.partial_button.configure(state='normal' if self.partial and not self.busy and not self.recording else 'disabled')
        self.device_box.configure(state='disabled' if self.busy or self.recording else 'readonly')
        self.reconnect_button.configure(state='disabled' if self.reconnecting or self.busy or self.recording else 'normal')
        self.quick_switches['auto_paste'].configure(state='disabled' if self.busy or self.recording else 'normal')
        self.hint.set(f"{self.prefs['hotkey']} · {tr('segure para falar' if self.prefs['hotkey_mode'] == 'hold' else 'iniciar / parar', self.prefs['language'])} · {tr('Esc cancela', self.prefs['language'])}")
        if self.hotkeys: self.hotkeys.set_active(self.recording or self.busy)
        if self.tray: self.tray.update(self.recording, self.busy)
        ui_theme.update(self)
        if self.mini:
            self.mini_record.configure(image=self.icons['stop' if self.recording else 'mic'],fg_color='#eea8ad' if self.recording else ui_theme.ACCENT,state='normal' if self.recording or (self.ready and not self.busy) else 'disabled')

    def poll(self):
        if self.closing: return
        for _ in range(200):
            try: kind, value = self.events.get_nowait()
            except queue.Empty: break
            if kind == 'verified': self.connect()
            elif kind == 'failure': self.fail(value)
            elif kind == 'backend':
                epoch, message = value
                if epoch == self.epoch: self.handle_backend(message)
            elif kind == 'replay_failed' and value == self.generation: self.fail('Falha na recuperação. A gravação continua guardada.')
            elif kind == 'action':
                action, target = value
                if action == 'toggle': self.toggle(target)
                elif action == 'start': self.start(target)
                elif action == 'stop': self.stop()
                elif action == 'cancel': self.cancel()
                elif action == 'show':
                    if self.mini: self.exit_mini()
                    else: self.root.deiconify(); self.root.lift()
                elif action == 'exit': self.close(force=True); return
        if self.recording:
            self.elapsed.set(f"{tr('Gravando · ', self.prefs['language'])}{self.capture.frames / self.capture.rate:.1f} s / {self.prefs['max_record_seconds']} s")
            self.meter['value'] = min(100, self.capture.level * 500)
            if self.capture.fault:
                self.fail(self.capture.fault)
            elif self.capture.limit: self.stop()
        else:
            self.meter['value'] = 0
            self.elapsed.set(tr('Microfone desligado · áudio guardado para recuperação' if self.retained else 'Microfone desligado', self.prefs['language']))
        if self.cancel_deadline and time.monotonic() > self.cancel_deadline:
            self.cancel_deadline = None; self.busy = False; self.reconnect()
        if self.mini:
            self.mini_meter.update_level(self.capture.level,self.recording,self.busy,self.ready)
            if time.monotonic() >= self.mini_visibility_check:
                self.mini_visibility_check = time.monotonic() + .15
                self.sync_mini_visibility()
        self.root.after(40, self.poll)

    def reconnect(self):
        if self.recording or self.busy or self.reconnecting: return
        self.reconnecting = True; self.epoch += 1
        self.ready = False; self.update_controls()
        client = self.client
        if client: client.close()
        def wait():
            if client and not client.done.is_set(): self.root.after(100, wait)
            elif not self.closing:
                self.reconnecting = False
                if client and client.cleanup_error: self.set_status('O processo anterior não encerrou. Feche o painel antes de continuar.'); self.update_controls()
                else: self.connect()
        wait()

    def hide(self):
        if self.tray: self.root.withdraw()
        else: self.set_status('Bandeja indisponível nesta sessão. A janela continuará aberta.')

    def preferences(self):
        if self.recording or self.busy: self.set_status('Pare ou cancele o ditado antes de mudar as preferências.'); return
        dialog = ctk.CTkToplevel(self.root); dialog.title(tr('Preferências',self.prefs['language'])); apply_window_icon(dialog); dialog.transient(self.root); dialog.grab_set(); dialog.geometry('540x700'); dialog.configure(fg_color=ui_theme.BG)
        panel = ctk.CTkScrollableFrame(dialog, fg_color=ui_theme.BG); panel.pack(fill='both', expand=True, padx=16, pady=16)
        ui_theme.label(panel,tr('Microfone', self.prefs['language'])).pack(anchor='w',pady=(0,4))
        microphone = ctk.CTkComboBox(panel, values=self.device_box.cget('values'), state='readonly', height=34)
        microphone.set(self.device_box.get()); microphone.pack(fill='x',pady=(0,12))
        ui_theme.label(panel, tr('Idioma', self.prefs['language'])).pack(anchor='w')
        language_var = tk.StringVar(value='English' if self.prefs['language']=='en' else 'Português')
        ctk.CTkComboBox(panel, values=['Português', 'English'], state='readonly', height=34, variable=language_var).pack(fill='x', pady=(0, 10))
        variables = {}
        startup_var = tk.BooleanVar(value=startup_enabled())
        ctk.CTkCheckBox(panel,text=tr('Iniciar com o Windows',self.prefs['language']),variable=startup_var,fg_color=ui_theme.ACCENT,text_color=ui_theme.TEXT).pack(anchor='w',pady=(0,10))
        ui_theme.button(panel,tr('Criar atalho na área de trabalho',self.prefs['language']),self.desktop_shortcut).pack(fill='x',pady=(0,12))
        for key, label in [('hotkey', 'Atalho global'), ('hotkey_mode', 'Modo: toggle ou hold'), ('idle_seconds', 'Conexão preparada por (10–120 s)'), ('tail_seconds', 'Espera final (0,5–2 s; use ponto)'), ('max_record_seconds', 'Limite de gravação (15–120 s)')]:
            ui_theme.label(panel, text=tr(label, self.prefs['language'])).pack(anchor='w'); variables[key] = tk.StringVar(value=str(self.prefs[key])); ctk.CTkEntry(panel, textvariable=variables[key],fg_color=ui_theme.SURFACE,border_color=ui_theme.LINE,text_color=ui_theme.TEXT).pack(fill='x', pady=(0, 6))
        for key, label in [('warmup', 'Preparar conexão ao abrir (microfone desligado)'), ('minimize_to_tray', 'Ao fechar a janela, ocultar na bandeja'), ('dictionary_enabled', 'Aplicar dicionário ao texto confirmado')]:
            variables[key] = tk.BooleanVar(value=self.prefs[key]); ctk.CTkCheckBox(panel, text=tr(label, self.prefs['language']), variable=variables[key],fg_color=ui_theme.ACCENT,hover_color='#d0ccff',text_color=ui_theme.TEXT,checkmark_color='#252239',border_color=ui_theme.LINE).pack(anchor='w', pady=6)
        ui_theme.label(panel, text=tr('Dicionário · uma regra por linha: original = substituição', self.prefs['language'])).pack(anchor='w', pady=(10, 0))
        dictionary = ctk.CTkTextbox(panel, height=120, fg_color=ui_theme.SURFACE, text_color=ui_theme.TEXT); dictionary.pack(fill='x'); dictionary.insert('1.0', format_dictionary(self.prefs['dictionary']))
        def save():
            try:
                from win_integration import parse_binding
                data = dict(self.prefs); data.update({k: v.get() for k, v in variables.items()})
                data['language'] = 'en' if language_var.get() == 'English' else 'pt-BR'
                parse_binding(data['hotkey'])
                if data['hotkey_mode'] not in ('toggle', 'hold'): raise ValueError('Modo deve ser toggle ou hold.')
                for key in ('idle_seconds', 'max_record_seconds'): data[key] = int(data[key])
                data['tail_seconds'] = float(data['tail_seconds'])
                if not 10 <= data['idle_seconds'] <= 120 or not 15 <= data['max_record_seconds'] <= 120 or not .5 <= data['tail_seconds'] <= 2: raise ValueError('Confira os limites indicados.')
                data['dictionary'] = parse_dictionary(dictionary.get('1.0', 'end-1c'))
                selected = next((key for _, _, key in self.devices if key.replace('|',' · ') == microphone.get()), None)
                if selected: data['microphone'] = selected; self.device_box.set(microphone.get())
                old_language = self.prefs['language']
                self.prefs = self.store.save(data)
                if startup_var.get() != startup_enabled(): set_startup(startup_var.get())
                self.root.attributes('-topmost', self.prefs['topmost'])
                if self.tray: self.tray.close(); self.tray = None
                self.install_windows()
                if self.ready: self.configure_backend()
                if old_language != self.prefs['language']:
                    messagebox.showinfo(tr('Preferências', self.prefs['language']), tr('Idioma salvo. Feche e abra o app para aplicar a nova língua à interface.', self.prefs['language']), parent=dialog)
                dialog.destroy()
            except (ValueError, OSError, RuntimeError) as exc: messagebox.showerror(tr('Preferências', self.prefs['language']), tr(str(exc), self.prefs['language']), parent=dialog)
        ui_theme.button(panel, tr('Salvar preferências',self.prefs['language']), save, primary=True).pack(anchor='e', pady=(10, 0))

    def close(self, force=False):
        if self.closing: return
        if not force and self.prefs['minimize_to_tray'] and self.tray: self.hide(); return
        self.closing = True; self.replay_cancel.set(); self.capture.stop(); self.capture.clear(); self.retained = None
        if self.hotkeys: self.hotkeys.close()
        if self.mini: self.mini.destroy(); self.mini = None
        if self.tray: self.tray.close()
        if self.client: self.client.close()
        def finish():
            if self.client and not self.client.done.is_set(): self.root.after(100, finish)
            else:
                for timer in self.root.tk.call('after','info'):
                    try: self.root.tk.call('after','cancel',timer)
                    except tk.TclError: pass
                self.root.destroy()
        finish()

def main():
    prepare_identity()
    guard = InstanceGuard(TITLE)
    if not guard.acquire(): return
    try:
        root = tk.Tk(); App(root); root.mainloop()
    finally: guard.release()

if __name__ == '__main__': main()
