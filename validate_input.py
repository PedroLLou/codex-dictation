"""Real Unicode insertion into this validator's own native Edit control only."""
import ctypes
import json
import os
import time
from ctypes import wintypes as w
from win_integration import _user32 as u, capture_target, paste_text

def main():
    u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,ctypes.c_void_p]
    u.CreateWindowExW.restype=w.HWND
    u.SetFocus.argtypes=[w.HWND]; u.SetFocus.restype=w.HWND
    u.DestroyWindow.argtypes=[w.HWND]
    u.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
    previous=u.GetForegroundWindow()
    parent=u.CreateWindowExW(0,'STATIC','Codex Dictation - isolated input validation',0x10cf0000,30,30,440,160,None,None,None,None)
    first=u.CreateWindowExW(0,'EDIT','',0x50010080,10,15,400,30,parent,None,None,None)
    second=u.CreateWindowExW(0,'EDIT','',0x50010080,10,55,400,30,parent,None,None,None)
    assert parent and first and second
    try:
        u.SetForegroundWindow(parent); u.SetFocus(first)
        target=capture_target()
        assert target.pid==os.getpid() and target.child_hwnd==first and target.known,'OWN_FIELD_FOCUS_REQUIRED'
        text='Olá, English and Unicode: café 🎤'
        ok,_=paste_text(target,text); assert ok
        deadline=time.monotonic()+.15
        while time.monotonic()<deadline:
            msg=w.MSG()
            while u.PeekMessageW(ctypes.byref(msg),None,0,0,1):
                u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))
            time.sleep(.005)
        buf=ctypes.create_unicode_buffer(256); u.GetWindowTextW(first,buf,len(buf))
        assert buf.value==text
        u.SetFocus(second)
        ok,_=paste_text(target,'SHOULD NOT BE INSERTED'); assert not ok
        u.GetWindowTextW(second,buf,len(buf)); assert buf.value==''
        print(json.dumps({'validation':'OWN_NATIVE_INPUT_OK','unicode':True,'focusChangeBlocked':True,'otherAppInput':False}))
    finally:
        u.DestroyWindow(parent)
        if previous: u.SetForegroundWindow(previous)

if __name__=='__main__': main()
