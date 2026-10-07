"""Interface compacta; componentes visuais separados do motor de ditado."""
import tkinter as tk
from i18n import tr
import customtkinter as ctk

BG = '#202124'
SURFACE = '#292b30'
LINE = '#3b3e45'
TEXT = '#f5f6f7'
MUTED = '#a7adb7'
ACCENT = '#beb9ff'

class DeviceBox(ctk.CTkComboBox):
    def current(self, index=None):
        values = self.cget('values')
        if index is not None: self.set(values[index]); return index
        try: return values.index(self.get())
        except ValueError: return -1
    def __setitem__(self, key, value): self.configure(**{key:value})

class Meter(ctk.CTkProgressBar):
    def __setitem__(self, key, value):
        if key == 'value': self.set(value / 100)
        else: self.configure(**{key:value})

def button(parent, text, command, primary=False, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command, height=36,
        corner_radius=10, font=('Segoe UI',13),
        fg_color=ACCENT if primary else SURFACE,
        hover_color='#d0ccff' if primary else '#363940',
        text_color='#252239' if primary else TEXT,
        border_width=0, **kwargs)

def label(parent, text='', **kwargs):
    kwargs.setdefault('text_color',MUTED); kwargs.setdefault('font',('Segoe UI',12)); kwargs.setdefault('anchor','w')
    return ctk.CTkLabel(parent, text=text, **kwargs)

def build(app, root, start_services):
    from minimal_ui import build as minimal_build
    minimal_build(app, root, start_services)

def update_empty(app):
    if app.text.edit_modified():
        if app.text.get('1.0','end-1c'): app.empty_label.place_forget()
        else: app.empty_label.place(relx=.5,rely=.43,anchor='center')
        app.text.edit_modified(False)

def update(app):
    app.record_button.configure(text='',image=app.icons['stop' if app.recording else 'mic'],fg_color='#eea8ad' if app.recording else ACCENT)
    app.hint.set(app.prefs['hotkey'].replace('Space',tr('Espaço', app.prefs['language'])))
    if app.recording or app.busy: app.cancel_button.place(relx=.5,x=40,rely=.5,anchor='w')
    else: app.cancel_button.place_forget()
    if app.recording: app.elapsed_label.pack(pady=(3,0))
    else: app.elapsed_label.pack_forget()
    if app.retained or app.partial: app.recovery_row.pack(fill='x',pady=(6,0),after=app.editor_panel)
    else: app.recovery_row.pack_forget()
    app.status_dot.configure(text_color='#eea8ad' if app.recording else ACCENT if app.ready else MUTED)
    show_preview = bool(app.preview.get('1.0','end-1c'))
    if show_preview and not app.preview_panel.winfo_manager(): app.preview_panel.pack(fill='x',pady=(0,12),before=app.editor_panel)
    elif not show_preview: app.preview_panel.pack_forget()
    if app.retained and not app.recording: app.recover_button.pack(side='left',padx=(6,0))
    else: app.recover_button.pack_forget()
    if app.partial: app.partial_button.pack(side='left',padx=(6,0))
    else: app.partial_button.pack_forget()

def history(app):
    dialog = ctk.CTkToplevel(app.root); dialog.title(tr('Histórico', app.prefs['language'])); dialog.geometry('520x440'); dialog.configure(fg_color=BG); dialog.transient(app.root)
    from app_identity import apply_window_icon
    apply_window_icon(dialog)
    panel = ctk.CTkScrollableFrame(dialog,fg_color=BG); panel.pack(fill='both',expand=True,padx=16,pady=16)
    ctk.CTkLabel(panel,text=tr('Histórico desta sessão', app.prefs['language']),text_color=TEXT,font=('Segoe UI Semibold',20)).pack(anchor='w',pady=(0,8))
    label(panel,tr('Os ditados desaparecem quando você encerra o app.', app.prefs['language'])).pack(anchor='w',pady=(0,16))
    if not app.history: label(panel,tr('Seus próximos ditados aparecerão aqui.', app.prefs['language'])).pack(anchor='w')
    for value, _ in reversed(app.history):
        row = ctk.CTkFrame(panel,fg_color=SURFACE,corner_radius=10); row.pack(fill='x',pady=(0,8))
        label(row,value[:300],wraplength=430,justify='left',text_color=TEXT).pack(fill='x',padx=12,pady=10)
        button(row,tr('Trazer para o editor', app.prefs['language']),lambda text=value: app.text.insert('end','\n\n'+text),width=155).pack(anchor='e',padx=10,pady=(0,10))
