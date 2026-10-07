"""Ícones desenhados localmente, sem fontes de símbolos ou downloads."""
from PIL import Image, ImageDraw
import customtkinter as ctk

def icon(name, color='#e5e5e7', size=20):
    scale=4; image=Image.new('RGBA',(24*scale,24*scale)); draw=ImageDraw.Draw(image)
    def line(points,width=1.7): draw.line([(int(x*scale),int(y*scale)) for x,y in points],fill=color,width=round(width*scale),joint='curve')
    def rect(box,r=0):
        bounds=tuple(round(v*scale) for v in box)
        if r: draw.rounded_rectangle(bounds,radius=round(r*scale),outline=color,width=round(1.7*scale))
        else: draw.rectangle(bounds,outline=color,width=round(1.7*scale))
    if name=='mic':
        rect((9,3,15,14),3); draw.arc((6*scale,8*scale,18*scale,18*scale),0,180,fill=color,width=7); line([(12,18),(12,22)]); line([(8,22),(16,22)])
    elif name=='copy': rect((8,7,20,21),2); line([(15,7),(15,3),(4,3),(4,17),(8,17)])
    elif name=='stop': draw.rounded_rectangle((6*scale,6*scale,18*scale,18*scale),radius=2*scale,fill=color)
    elif name=='cancel': line([(6,6),(18,18)]); line([(18,6),(6,18)])
    elif name=='settings':
        for y in (6,12,18): line([(3,y),(21,y)])
        for x,y in ((8,6),(16,12),(10,18)):
            draw.ellipse(((x-2)*scale,(y-2)*scale,(x+2)*scale,(y+2)*scale),fill='#202124',outline=color,width=5)
    elif name=='more':
        for x in (5,12,19): draw.ellipse(((x-1)*scale,11*scale,(x+1)*scale,13*scale),fill=color)
    elif name=='recover':
        draw.arc((4*scale,4*scale,20*scale,20*scale),-70,210,fill=color,width=7); line([(3,8),(3,14),(9,14)])
    elif name=='expand':
        line([(3,9),(3,3),(9,3)]); line([(15,3),(21,3),(21,9)])
        line([(3,15),(3,21),(9,21)]); line([(15,21),(21,21),(21,15)])
    return ctk.CTkImage(light_image=image,dark_image=image,size=(size,size))

class Tooltip:
    def __init__(self, widget, text):
        self.widget=widget; self.text=text; self.popup=None; self.timer=None
        widget.bind('<Enter>',self.enter,add=True); widget.bind('<Leave>',self.leave,add=True); widget.bind('<ButtonPress>',self.leave,add=True)
    def enter(self,_=None): self.timer=self.widget.after(450,self.show)
    def show(self):
        import tkinter as tk
        self.popup=tk.Toplevel(self.widget); self.popup.withdraw(); self.popup.overrideredirect(True)
        self.popup.geometry(f'+{self.widget.winfo_rootx()}+{self.widget.winfo_rooty()+self.widget.winfo_height()+5}')
        text=self.text.get() if hasattr(self.text,'get') else self.text
        tk.Label(self.popup,text=text,bg='#363940',fg='#f5f6f7',font=('Segoe UI',10),padx=8,pady=5,wraplength=280).pack()
        self.popup.update_idletasks()
        from win_integration import make_nonactivating, IS_WINDOWS
        if IS_WINDOWS:
            try: make_nonactivating(self.popup)
            except Exception: self.popup.destroy(); self.popup=None; return
        self.popup.deiconify()
    def leave(self,_=None):
        if self.timer: self.widget.after_cancel(self.timer); self.timer=None
        if self.popup: self.popup.destroy(); self.popup=None
