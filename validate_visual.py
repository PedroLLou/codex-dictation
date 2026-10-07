"""Validação de layout e modais; sem captura, rede ou teclas globais."""
import tkinter as tk
from gui_v2 import App
import ui_theme

root=tk.Tk(); app=App(root,start_services=False)
try:
    root.update()
    assert app.record_button.cget('text') == ''
    assert not app.cancel_button.winfo_manager()
    assert not app.device_box.winfo_ismapped()
    app.set_preview('Prévia de uma frase em português.'); root.update()
    assert app.preview_panel.winfo_manager() == 'pack'
    app.set_preview(''); root.update()
    assert not app.preview_panel.winfo_manager()
    app.preferences(); root.update()
    dialogs=[child for child in root.winfo_children() if isinstance(child,tk.Toplevel)]
    assert len(dialogs)==1
    dialogs[0].destroy()
    ui_theme.history(app); root.update()
    dialogs=[child for child in root.winfo_children() if isinstance(child,tk.Toplevel)]
    assert len(dialogs)==1
    dialogs[0].destroy()
    for width,height in ((460,540),(400,440)):
        root.geometry(f'{width}x{height}'); root.update()
        assert app.text.winfo_width()>250 and app.text.winfo_height()>70
        assert app.record_button.winfo_y()>=0
    print('VISUAL_LAYOUT_OK: idle, preview, preferences, history, minimum window; no microphone or network')
finally: app.close(force=True)
