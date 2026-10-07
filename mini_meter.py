"""Barrinha de nível do microfone e indicação discreta de processamento."""
import math
import time
import tkinter as tk
from ui_theme import BG, LINE, ACCENT

class MiniMeter(tk.Canvas):
    def __init__(self,parent):
        super().__init__(parent,width=44,height=34,bg=BG,highlightthickness=0)
        self.bars=[self.create_line(x,15,x,19,fill=LINE,width=3,capstyle='round') for x in (7,14,21,28,35)]
    def update_level(self,level,recording=False,busy=False,ready=True):
        amplitude=min(1,max(0,float(level))*12)
        for index,bar in enumerate(self.bars):
            if recording: height=4+amplitude*(10,21,28,19,11)[index]
            elif busy: height=4+5*(1+math.sin(time.monotonic()*5-index))
            else: height=4
            x=(7,14,21,28,35)[index]
            self.coords(bar,x,17-height/2,x,17+height/2)
            self.itemconfigure(bar,fill=ACCENT if recording or busy else '#eea8ad' if not ready else '#636773')
