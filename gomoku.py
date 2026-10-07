# -*- coding: utf-8 -*-
"""
五子棋对局助手（纯本地） — 程序=你，在15x15棋盘窗口和对面下棋
选颜色后：
  对面落子 -> 你在窗口点一下对面那颗(程序自动按黑先白后判断颜色) -> 引擎算棋 -> 程序自动把你那子落在窗口
  你照着窗口你落的位置，在外面真实软件下这一步；对面再落子继续。
按键: F1=开始新对局(选颜色), Esc=关闭
"""
import sys, os, ctypes, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---- DPI 感知: 解决 125%/150% 缩放下点击坐标与像素不一致 ----
# 必须在使用 tkinter 窗口创建之前调用
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import messagebox, colorchooser
import gomoku_engine as E
import time as _time

MAIN = {"my_side": None, "turn": 1, "board": None, "running": False, "game_over": False, "busy": False}

# ---- 对局日志: 每局一个文件(文档\五子棋对局助手日志\), 记录每手棋+引擎理由+终局盘面, 便于事后诊断 ----
LOG_DIR = os.path.join(os.path.expanduser("~"), "Documents", "五子棋对局助手日志")
_LOGF = None

def _log(msg):
    """追加一条日志; 任何日志失败都不影响对局。"""
    global _LOGF
    try:
        if _LOGF is None:
            os.makedirs(LOG_DIR, exist_ok=True)
            _LOGF = open(os.path.join(LOG_DIR, "对局_%s.log" % _time.strftime("%Y%m%d_%H%M%S")),
                         "a", encoding="utf-8")
        _LOGF.write("[%s] %s\n" % (_time.strftime("%H:%M:%S"), msg))
        _LOGF.flush()
    except Exception:
        pass

def _reset_log():
    """每新开一局: 删除上一局的日志文件, 只保留本局。"""
    global _LOGF
    try:
        if _LOGF:
            _LOGF.close()
    except Exception:
        pass
    _LOGF = None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        for fn in os.listdir(LOG_DIR):
            if fn.startswith("对局_") and fn.endswith(".log"):
                try: os.remove(os.path.join(LOG_DIR, fn))
                except Exception: pass
    except Exception:
        pass

def _board_str(b):
    """终局盘面: 15行x15列, 1=黑 2=白 0=空。"""
    return "\n".join(" ".join(str(v) for v in row) for row in b)

def new_board():
    return [[0]*15 for _ in range(15)]

class Board:
    def __init__(self, root):
        self.root=root
        self.img=None
        cw=640
        self.c=tk.Canvas(root,width=cw,height=cw,bg="#e8c98f",highlightthickness=0)
        self.c.pack(padx=10,pady=10)
        self.c.bind("<Button-1>", self.on_click)
        self.c.bind("<Motion>", self.on_hover)
        # 用画布实际像素宽算格子(兼容DPI缩放), 并用触摸坐标的像素值
        self.recalc()
        # 每帧/尺寸变化后重算, 确保网格铺满并点取准确
        self.c.bind("<Configure>", lambda e: self.recalc())
        self.draw()

    def recalc(self):
        # 画布真实可用尺寸(物理像素, 由环境给出)
        self.c.update_idletasks()
        w=self.c.winfo_width()
        if w and w>50:
            self.cw=w
        else:
            self.cw=640
        self.cell=self.cw/14.0
        self.draw()

    def xy(self,r,c): return self.cell*c, self.cell*r

    def set_status(self,text):
        lbl=MAIN.get("status_label")
        if lbl is not None:
            try: lbl.config(text=text)
            except Exception: pass

    def on_hover(self,ev):
        # 悬停高亮最近交叉点(纯视觉, 不影响落子逻辑)
        px=self.c.canvasx(ev.x); py=self.c.canvasy(ev.y)
        c=int(round(px/self.cell)); r=int(round(py/self.cell))
        self.c.delete("hover")
        if MAIN["running"] and 0<=r<15 and 0<=c<15 and MAIN["board"][r][c]==0:
            x,y=self.xy(r,c)
            self.c.create_oval(x-9,y-9,x+9,y+9,outline="#b5651d",width=2,tags="hover")

    def draw(self):
        self.c.delete("all")
        b=MAIN["board"] or new_board()
        pad=self.cell*0.35
        # 木纹底色矩形
        self.c.create_rectangle(-pad,-pad,self.cw+pad,self.cw+pad,fill="#e8c98f",outline="",tags="bg")
        for i in range(15):
            self.c.create_line(*self.xy(0,i), *self.xy(14,i), fill="#7a5a2e", width=1)
            self.c.create_line(*self.xy(i,0), *self.xy(i,14), fill="#7a5a2e", width=1)
        # 外框加粗
        self.c.create_rectangle(*self.xy(0,0), *self.xy(14,14), outline="#5a3e1c", width=2)
        for (r,c) in [(7,7),(3,3),(3,11),(11,3),(11,11)]:
            x,y=self.xy(r,c); self.c.create_oval(x-4,y-4,x+4,y+4,fill="#5a3e1c",outline="")
        for r in range(15):
            for c in range(15):
                if r<len(b) and c<len(b[r]) and b[r][c]:
                    x,y=self.xy(r,c)
                    col="#000" if b[r][c]==1 else "#fff"
                    self.c.create_oval(x-13,y-13,x+13,y+13,fill=col,outline="#333",width=1)

    def on_click(self,ev):
        # 防抖: 上一次点击还在处理(引擎思考中)则忽略, 避免连点导致多落子
        if MAIN.get("busy"): return
        MAIN["busy"]=True
        # _do_click 内部若进入异步计算(your_move), 会保持 busy 直到算完;
        # 否则 (点了已占格/对手赢/非运行) 由 _do_click 自释放。
        self._do_click(ev)

    def _do_click(self,ev):
        if MAIN["game_over"]:
            MAIN["busy"]=False
            # 明确确认再开新局, 避免误点重置残局
            if messagebox.askyesno("再来一局？","本局已结束。是否开始下一局（沿用同色）？"):
                self.start(MAIN["my_side"])
            return
        if not MAIN["running"]: 
            MAIN["busy"]=False
            self.set_status("请先点上方『执黑先手』或『执白后手』开始对局")
            return
        # 用画布实际坐标(像素)就近取交叉点, 避免偏左上
        px=self.c.canvasx(ev.x); py=self.c.canvasy(ev.y)
        c=int(round(px/self.cell)); r=int(round(py/self.cell))
        if r<0 or r>14 or c<0 or c>14:
            MAIN["busy"]=False
            return
        b=MAIN["board"]
        if b[r][c]!=0:
            MAIN["busy"]=False
            messagebox.showinfo("提示","这里已经有棋子了"); return
        # 这是"对面"落子(程序是你)
        opp=3-MAIN["my_side"]
        b[r][c]=opp
        MAIN["turn"]+=1
        _log("对方(%s)落子 (%d,%d)" % ("黑" if opp==1 else "白", r, c))
        self.draw()
        # 判断对面是否赢了
        if self.check_win(opp, r, c):
            _log("对方连五, 对方胜。终局盘面:\n%s" % _board_str(b))
            self.set_status("对面(敌方)赢了！点击棋盘可开始下一局。")
            self.finish(); MAIN["busy"]=False; return
        # 对面落完, 该你(程序)下 -> 引擎算棋(异步, busy保持到算完) -> 自动落+提示
        self.your_move()

    def start(self, side):
        """选颜色开局(side=1黑先手/2白后手)。"""
        if MAIN.get("busy"):
            return
        MAIN["busy"]=True
        E.new_game()   # 开新局清空置换表(局内复用)
        MAIN["my_side"]=side
        MAIN["board"]=new_board()
        MAIN["turn"]=1
        MAIN["running"]=True
        MAIN["game_over"]=False
        global _LOGF
        _reset_log()   # 每新开一局: 删上一局日志, 本局新开文件
        _log("==== 新对局: 我方执%s ====" % ("黑(先手)" if side==1 else "白(后手)"))
        self.draw()
        if side==1:
            # 程序执黑先手 -> 后台线程算首步, 避免冻结界面
            self.set_status("已开局(你执黑先手)，程序正在思考第一步…")
            def _think():
                move,reason=E.best_move(MAIN["board"],1)
                self.root.after(0, lambda: self._apply_black_open(move, reason))
            threading.Thread(target=_think, daemon=True).start()
        else:
            MAIN["busy"]=False
            self.set_status("已开局(你执白后手)。请等对面先落子，然后点击下方说明：对面落子后点击棋盘上对面那颗。")

    def _apply_black_open(self, move, reason):
        """在主线程应用'执黑先手'的第一步落子。"""
        MAIN["busy"]=False
        if move is None:
            self.set_status("开局无位: %s" % reason); return
        MAIN["board"][move[0]][move[1]]=1
        MAIN["turn"]=2
        _log("我方应手 (%d,%d) 理由: %s" % (move[0], move[1], reason))
        self.draw()
        x,y=self.xy(move[0],move[1])
        self.c.create_oval(x-16,y-16,x+16,y+16,outline="#e53935",width=3,tags="last")
        self.set_status("已开局(你执黑先手)，程序先落在(%d,%d)。等对面落子后，点击棋盘上对面那颗。"%(move[0],move[1]))

    def your_move(self):
        b=MAIN["board"]
        my=MAIN["my_side"]
        self.set_status("对面已落子，程序正在思考应手…")
        def _think():
            try:
                move,reason=E.best_move(b,my)
            except Exception as e:
                move,reason=None,"引擎出错: %s"%e
                _log("引擎异常: %r" % e)
            self.root.after(0, lambda: self._apply_your_move(move, reason))
        threading.Thread(target=_think, daemon=True).start()

    def _apply_your_move(self, move, reason):
        """在主线程应用程序应手。"""
        MAIN["busy"]=False
        my=MAIN["my_side"]
        if move is None:
            _log("无着可下(满盘/异常), 平局。终局盘面:\n%s" % _board_str(b))
            self.set_status("棋盘已满/异常，平局。点击棋盘可开始下一局。"); self.finish(); return
        b=MAIN["board"]
        b[move[0]][move[1]]=my
        MAIN["turn"]+=1
        _log("我方应手 (%d,%d) 理由: %s" % (move[0], move[1], reason))
        self.draw()
        # 高亮建议/己方落子(红环标记)
        x,y=self.xy(move[0],move[1])
        self.c.create_oval(x-16,y-16,x+16,y+16,outline="#e53935",width=3,tags="last")
        if self.check_win(my, move[0], move[1]):
            _log("我方连五, 我方胜。终局盘面:\n%s" % _board_str(b))
            self.set_status("你(助手)赢了！点击棋盘可开始下一局。")
            self.finish(); return
        # 不弹对话框: 用窗口上的状态文字提示
        self.set_status("程序已替你落子在 (%d,%d)。请在外面软件下这步，等对面落子后点击棋盘上对面那颗。  (提示: %s)" % (move[0], move[1], reason))

    def check_win(self,p,r,c):
        for dr,dc in E.DIRS:
            cnt=1
            for s in range(1,5):
                nr,nc=r+dr*s,c+dc*s
                if 0<=nr<15 and 0<=nc<15 and MAIN["board"][nr][nc]==p: cnt+=1
                else: break
            for s in range(1,5):
                nr,nc=r-dr*s,c-dc*s
                if 0<=nr<15 and 0<=nc<15 and MAIN["board"][nr][nc]==p: cnt+=1
                else: break
            if cnt>=5: return True
        return False

    def finish(self):
        MAIN["running"]=False
        MAIN["game_over"]=True

def _run_selftest():
    """无头自测(--selftest): 验证打包产物内 引擎/开局库/PVS/VCF/日志 协同工作, 结果写入日志目录。"""
    lines = []
    def w(s):
        lines.append(s)
        try: print(s)
        except Exception: pass
    try:
        w("== 五子棋对局助手 自测 ==")
        w("引擎模块: %s" % getattr(E, "__file__", "?"))
        w("是否编译版(Nuitka __compiled__ 标记): %s" % str(hasattr(E, "__compiled__")))
        def mk(stones):
            b = [[0]*15 for _ in range(15)]
            for (r,c,p) in stones: b[r][c] = p
            return b
        cases = [
            ("跳空四必堵", mk([(5,3,2),(5,4,2),(5,5,2),(5,7,2)]), 1, ((5,6),)),
            ("冲四堵口",   mk([(5,3,2),(5,4,2),(5,5,2),(5,6,2),(5,2,1)]), 1, ((5,7),)),
            ("斜跳空四必堵", mk([(4,4,2),(5,5,2),(6,6,2),(8,8,2)]), 1, ((7,7),)),
            ("先赢不防",   mk([(9,5,1),(9,6,1),(9,7,1),(9,8,1),(5,3,2),(5,4,2),(5,5,2),(5,7,2)]), 1, ((9,4),(9,9))),
            ("双杀必拆",   mk([(7,4,2),(7,5,2),(7,6,2),(4,7,2),(5,7,2),(6,7,2),(7,2,1),(7,8,1),(2,7,1)]), 1, ((7,7),)),
        ]
        nfail = 0
        for name, b, side, want in cases:
            E.new_game()
            m, rr = E.best_move(b, side)
            good = m in want
            if not good: nfail += 1
            w("[%s] %s -> %s" % ("PASS" if good else "FAIL", name, m))
        # 开局库
        b0 = [[0]*15 for _ in range(15)]
        E.new_game()
        m0, r0 = E.best_move(b0, 1)
        w("[%s] 开局库首着 -> %s (%s)" % ("PASS" if m0 is not None else "FAIL", m0, r0))
        if m0 is None: nfail += 1
        # VCF/搜索集成: 白双四必胜局(用户实战复盘局)
        b2 = [[0]*15 for _ in range(15)]
        for (r,c) in [(3,8),(4,5),(6,3),(6,8),(7,6),(8,3),(8,5),(8,6),(8,7),(8,9),(9,4),(9,6),(10,6)]: b2[r][c] = 1
        for (r,c) in [(4,7),(5,6),(6,4),(6,5),(6,6),(6,7),(7,4),(7,7),(8,4),(8,8),(11,6)]: b2[r][c] = 2
        E.new_game()
        m2, r2 = E.best_move(b2, 2)
        w("[%s] 实战双四必胜局 -> %s (%s)" % ("PASS" if m2 == (4,4) else "WARN", m2, r2))
        # 日志
        _log("自测完成, 失败项: %d" % nfail)
        try:
            w("日志目录存在: %s" % os.path.isdir(LOG_DIR))
        except Exception as e:
            w("日志异常: %r" % e)
        w("== 自测结束, 失败项: %d ==" % nfail)
    except Exception as e:
        w("自测异常: %r" % e)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "selftest_result.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass

def main():
    root=tk.Tk()
    root.title("五子棋对局助手（程序=你）")
    root.configure(bg="#2b2b2b")
    global board_widget
    MAIN["board"]=new_board()
    # 顶部标题栏 + 开局按钮
    top=tk.Frame(root,bg="#2b2b2b")
    top.pack(fill="x",pady=(10,0))
    tk.Label(top,text="五子棋对局助手",fg="#f5d78a",bg="#2b2b2b",
             font=("Microsoft YaHei",16,"bold")).pack()
    btnrow=tk.Frame(top,bg="#2b2b2b"); btnrow.pack(pady=4)
    board_widget=Board(root)
    def pick(side): board_widget.start(side)
    tk.Button(btnrow,text="执黑先手",command=lambda:pick(1),bg="#1a1a1a",fg="#fff",
              activebackground="#333",relief="flat",padx=14,pady=4,font=("Microsoft YaHei",10,"bold")).pack(side="left",padx=6)
    tk.Button(btnrow,text="执白后手",command=lambda:pick(2),bg="#f0f0f0",fg="#222",
              activebackground="#ccc",relief="flat",padx=14,pady=4,font=("Microsoft YaHei",10,"bold")).pack(side="left",padx=6)
    tk.Label(top,text="点上方按钮开局 · 对面落子后点击棋盘上对面那颗 · Esc 退出",
             fg="#cfcfcf",bg="#2b2b2b",font=("Microsoft YaHei",9)).pack(pady=(4,2))
    root.bind("<Escape>", lambda e: root.destroy())
    # 底部状态栏
    st=tk.Label(root,text="",font=("Microsoft YaHei",9),fg="#eafbe7",bg="#3a5a40",
                wraplength=620,justify="left",anchor="w",padx=10,pady=6)
    st.pack(fill="x",side="bottom")
    MAIN["status_label"]=st
    board_widget.set_status("点上方『执黑先手』或『执白后手』开始对局。")
    root.mainloop()

if __name__=="__main__":
    if "--selftest" in sys.argv:
        _run_selftest()
    else:
        main()