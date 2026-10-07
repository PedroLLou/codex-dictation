"""Identidade visual e agrupamento do aplicativo, apenas neste processo."""
import ctypes
import os
from pathlib import Path
from PIL import Image, ImageDraw
from runtime_paths import ROOT

ASSETS=ROOT/'assets'
ICON=ASSETS/'ditado-codex.ico'
_native_icons = []

def app_image(size=256):
    scale=4; image=Image.new('RGBA',(100*scale,100*scale))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((4*scale,4*scale,96*scale,96*scale),radius=24*scale,fill='#beb9ff')
    ink='#252239'
    draw.rounded_rectangle((40*scale,20*scale,60*scale,58*scale),radius=10*scale,fill=ink)
    draw.arc((30*scale,36*scale,70*scale,74*scale),0,180,fill=ink,width=6*scale)
    draw.line((50*scale,73*scale,50*scale,83*scale),fill=ink,width=5*scale)
    draw.line((40*scale,83*scale,60*scale,83*scale),fill=ink,width=5*scale)
    return image.resize((size,size),Image.Resampling.LANCZOS)

def prepare_identity():
    if os.name=='nt':
        shell=ctypes.WinDLL('shell32')
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes=[ctypes.c_wchar_p]
        shell.SetCurrentProcessExplicitAppUserModelID.restype=ctypes.c_long
        shell.SetCurrentProcessExplicitAppUserModelID('Pedro.DitadoCodex')

def apply_window_icon(window):
    if os.name=='nt':
        window.iconbitmap(str(ICON))
        # Explicit high resolution handles avoid Tk's small default icon being
        # stretched by the taskbar on monitors with display scaling.
        def install():
            if not window.winfo_exists(): return
            user=ctypes.WinDLL('user32',use_last_error=True)
            user.LoadImageW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
            user.LoadImageW.restype=ctypes.c_void_p
            user.GetParent.argtypes=[ctypes.c_void_p]; user.GetParent.restype=ctypes.c_void_p
            user.SendMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
            user.SendMessageW.restype=ctypes.c_ssize_t
            hwnd=user.GetParent(window.winfo_id()) or window.winfo_id()
            if not _native_icons:
                _native_icons.extend(user.LoadImageW(None,str(ICON),1,s,s,0x10) for s in (32,64))
            for kind,handle in enumerate(_native_icons):
                if handle: user.SendMessageW(hwnd,0x80,kind,handle)
        window.after(250,install)

if __name__=='__main__':
    ASSETS.mkdir(exist_ok=True)
    image=app_image()
    image.save(ICON,format='ICO',sizes=[(s,s) for s in (16,20,24,32,40,48,64,128,256)])
    image.save(ASSETS/'ditado-codex.png')
