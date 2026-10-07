import tkinter as tk
from i18n import tr
import customtkinter as ctk
from ui_theme import BG,SURFACE,LINE,TEXT,MUTED,ACCENT,DeviceBox,Meter,button,label,update_empty,history
from ui_icons import icon,Tooltip

def build(app,root,start_services):
    ctk.set_appearance_mode('dark')
    root.geometry('460x540'); root.minsize(400,440); root.configure(bg=BG)
    app.icons={name:icon(name) for name in ('mic','stop','cancel','settings','copy','more','recover','expand')}
    app.icons['mic']=icon('mic','#252239',22); app.icons['stop']=icon('stop','#252239',22)
    panel=ctk.CTkFrame(root,fg_color=BG,corner_radius=0); panel.pack(fill='both',expand=True,padx=20,pady=18)
    def action(parent,name,command,hint,primary=False,size=34):
        widget=button(parent,'',command,primary=primary,width=size,image=app.icons[name]); widget.configure(height=size)
        Tooltip(widget,hint); return widget
    header=ctk.CTkFrame(panel,fg_color='transparent'); header.pack(fill='x',pady=(0,12))
    ctk.CTkLabel(header,text='Codex Dictation' if app.prefs['language']=='en' else 'Ditado Codex',text_color=TEXT,font=('Segoe UI Semibold',18),anchor='w').pack(side='left')
    action(header,'settings',app.preferences,tr('Preferências', app.prefs['language'])).pack(side='right')
    button(header,tr('Modo mini', app.prefs['language']),app.enter_mini,width=86).pack(side='right',padx=(0,6))
    app.status=tk.StringVar(value=tr('Preparando…', app.prefs['language']) if start_services else tr('Pronto', app.prefs['language']))
    state=ctk.CTkFrame(panel,fg_color='transparent'); state.pack(fill='x',pady=(0,10))
    app.status_dot=ctk.CTkLabel(state,text='●',text_color=ACCENT,width=14,font=('Segoe UI',10)); app.status_dot.pack(side='left',padx=(0,4))
    label(state,textvariable=app.status,wraplength=365,justify='left').pack(side='left',fill='x',expand=True)
    app.preview_panel=ctk.CTkFrame(panel,fg_color='transparent')
    preview=ctk.CTkTextbox(app.preview_panel,height=58,fg_color=BG,text_color=MUTED,font=('Segoe UI',13),wrap='word')
    preview.pack(fill='x'); app.preview=preview._textbox; app.preview.configure(state='disabled')
    app.editor_panel=ctk.CTkFrame(panel,fg_color=SURFACE,corner_radius=14,border_width=1,border_color=LINE)
    app.editor_panel.pack(fill='both',expand=True)
    tools=ctk.CTkFrame(app.editor_panel,fg_color='transparent'); tools.pack(fill='x',padx=8,pady=(7,0))
    action(tools,'copy',app.copy,tr('Copiar texto', app.prefs['language'])).pack(side='right')
    app.more_menu=tk.Menu(root,tearoff=False,bg=SURFACE,fg=TEXT,activebackground=LINE,activeforeground=TEXT,font=('Segoe UI',11))
    for title,command in [(tr('Histórico', app.prefs['language']),lambda:history(app)),(tr('Salvar texto', app.prefs['language']),app.export),(tr('Desfazer correção', app.prefs['language']),app.undo_correction),(tr('Limpar', app.prefs['language']),app.clear_text),(tr('Reconectar', app.prefs['language']),app.reconnect),(tr('Atualizar microfones', app.prefs['language']),app.refresh_devices),(tr('Ocultar na bandeja', app.prefs['language']),app.hide),(tr('Encerrar', app.prefs['language']),lambda:app.close(force=True))]: app.more_menu.add_command(label=title,command=command)
    more=action(tools,'more',lambda:app.more_menu.tk_popup(more.winfo_rootx(),more.winfo_rooty()+more.winfo_height()),tr('Mais opções', app.prefs['language'])); more.pack(side='right',padx=(0,2))
    app.more_menu.add_command(label=tr('Ajuda',app.prefs['language']),command=app.open_help)
    editor=ctk.CTkTextbox(app.editor_panel,height=130,fg_color=SURFACE,text_color=TEXT,font=('Segoe UI',15),wrap='word',undo=True,scrollbar_button_color=LINE,scrollbar_button_hover_color=MUTED)
    editor.pack(fill='both',expand=True,padx=8,pady=(0,10)); app.text=editor._textbox
    app.empty_label=ctk.CTkLabel(editor,text=tr('Seu texto aparece aqui.', app.prefs['language']),text_color=MUTED,font=('Segoe UI',14))
    app.empty_label.place(relx=.5,rely=.43,anchor='center'); app.empty_label.bind('<Button-1>',lambda _:app.text.focus_set())
    app.text.bind('<<Modified>>',lambda _:update_empty(app))
    app.recovery_row=ctk.CTkFrame(panel,fg_color='transparent')
    app.recover_button=button(app.recovery_row,tr('Recuperar', app.prefs['language']),app.recover,width=110,image=app.icons['recover'])
    app.partial_button=button(app.recovery_row,tr('Usar parcial', app.prefs['language']),app.accept_partial,width=110)
    app.meter=Meter(panel,height=2,corner_radius=0,fg_color=BG,progress_color=ACCENT); app.meter.set(0); app.meter.pack(fill='x',pady=(12,6))
    controls=ctk.CTkFrame(panel,fg_color='transparent'); controls.pack(fill='x')
    app.record_button=action(controls,'mic',app.toggle,tr('Iniciar ou parar ditado', app.prefs['language']),primary=True,size=52); app.record_button.pack(anchor='center')
    app.cancel_button=action(controls,'cancel',app.cancel,tr('Cancelar', app.prefs['language']),size=32)
    app.hint=tk.StringVar(); label(panel,textvariable=app.hint,font=('Segoe UI',10),anchor='center').pack(pady=(7,0))
    app.elapsed=tk.StringVar(value=''); app.elapsed_label=label(panel,textvariable=app.elapsed,font=('Segoe UI',10),anchor='center')
    quick=ctk.CTkFrame(panel,fg_color='transparent'); quick.pack(fill='x',pady=(14,0))
    app.quick_prefs={}; app.quick_switches={}
    for key,title,hint in [('topmost',tr('Sempre visível', app.prefs['language']),tr('Manter a janela acima dos outros aplicativos', app.prefs['language'])),('auto_paste',tr('Inserir no campo', app.prefs['language']),tr('Inserir no campo original ao usar o atalho, sem enviar Enter', app.prefs['language']))]:
        variable=tk.BooleanVar(value=app.prefs[key]); app.quick_prefs[key]=variable
        switch=ctk.CTkSwitch(quick,text=title,variable=variable,command=lambda name=key: app.save_quick_preference(name),font=('Segoe UI',11),text_color=MUTED,fg_color=LINE,progress_color=ACCENT,button_color='#e5e5e7',button_hover_color=TEXT,switch_width=30,switch_height=16,width=140,height=24)
        switch.pack(side='left' if key=='topmost' else 'right'); app.quick_switches[key]=switch; Tooltip(switch,hint)
    # O seletor continua disponível para o controlador e aparece nas preferências.
    hidden=ctk.CTkFrame(root)
    app.device_box=DeviceBox(hidden,values=[],state='readonly',command=lambda _:app.save_device())
    app.reconnect_button=button(hidden,tr('Reconectar', app.prefs['language']),app.reconnect)
    app.history_box=tk.Listbox(root)
