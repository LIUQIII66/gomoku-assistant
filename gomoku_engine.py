# -*- coding: utf-8 -*-
"""五子棋 alpha-beta 搜索引擎。输入15x15棋盘(board, 0空1黑2白), my_side, 返回best_move,reason。"""
SIZE=15
DIRS=[(1,0),(0,1),(1,1),(1,-1)]
_CAND_LIMIT=10   # 每节点考虑的候选数上限(可调整以扩大/缩小搜索视野)
import time as _tm
_DEADLINE=None
# 开局库已移除: A/B实测证明硬编码套路不如搜索, 且原实现为死代码(总返回None)。

# ---- 标准棋型分级评估(根治威胁排序错误) ----
# 对某条线(长度>=5的一段连续可落区域), 统计己方子在其中的"最佳可成型"。
# 关键: 区分 连五 / 活四 / 冲四(含跳空四 X_XX,XX_X) / 活三 / 眠三 —— 按紧迫度严格分级。
FIVE   = 10000000
WIN_SCORE = 10**9      # 真实"已成五/必胜"的分, 远高于任何eval累加和, 用于区分胜负与评估
LIVE4  = 1000000     # 活四(两端开), 下一手必成五 -> 最高危之一
FOUR   = 100000      # 冲四/跳四(一端开或中间断但补上即五) -> 必须立刻处理
LIVE3  = 50000       # 活三(两端开), 下一步成活四
SLEEP3 = 1000        # 眠三(一端堵)
LIVE2  = 500
SLEEP2 = 100

def _pattern_score(board,r,c,player):
    """在(r,c)落player的威胁分 —— 基于'成五点集合'(根治跳空活四/双杀漏判)。"""
    if board[r][c]!=0: return 0
    return pattern_tier(board,r,c,player)

def line_scores(board,r,c,player):
    """兼容旧接口名: 返回(r,c)落player的形状威胁分(分级版)。"""
    if board[r][c]!=0: return 0
    return _pattern_score(board,r,c,player)

def threat(board,r,c,player):
    if board[r][c]!=0: return 0
    return _pattern_score(board,r,c,player)

def double_win(board, r, c, player):
    """落子(r,c)后是否形成'双杀'(>=2个独立成五点: 活四/双活三/四三/双四均含)。
    基于成五点集合, 天然覆盖跳空型双杀(治②)。"""
    if board[r][c]!=0: return False
    return len(win_points_after(board,r,c,player)) >= 2

def _near_stone(board,r,c):
    # 用预计算邻接表(性能轮1): 8斜邻+4 orth距离2, 与原偏移表一致
    for (rr,cc) in _NEIGH[r][c]:
        if board[rr][cc]!=0:
            return True
    return False

def _center_control(board, player):
    sc=0
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c]==player:
                d=abs(r-7)+abs(c-7)
                sc += max(0, 14-d)   # 越靠中心越高
    return sc

# ---- 增量评估状态: 每个空点的(我方分,对方分)缓存 + 全局累加值 ----
# 落子/撤销时只更新受影响的邻域点, 避免每次全盘重算 -> 大幅提速。
# (发展潜能分已彻底移除: 原实现每节点全盘重扫是高热点, 且与战术分信息重叠)
_PTS = None      # [r][c] = (score_for_1, score_for_2) 仅对空点有意义
_G_CTR = [0,0]   # 中心控制 [黑,白]
_G_TAC1 = 0      # 全盘 player1 即时分之和 (eval_board 增量化: 叶子 O(1))
_G_TAC2 = 0      # 全盘 player2 即时分之和

def _affected_points(r,c):
    """落子在(r,c)会影响哪些空点的评分: 8方向x最多4格 的米字邻域(含自身周围)。"""
    pts=set()
    for dr,dc in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
        for k in range(1,5):
            rr=r+dr*k; cc=c+dc*k
            if 0<=rr<SIZE and 0<=cc<SIZE: pts.add((rr,cc))
    pts.add((r,c))
    return pts

# ---- 预计算几何表(模块加载时一次构建; 性能轮1: 消除热路径边界判断与切片分配) ----
_LINE9 = [[None]*SIZE for _ in range(SIZE)]   # [r][c] = 4方向 x 9格坐标(越界为None)
_NEIGH = [[None]*SIZE for _ in range(SIZE)]   # [r][c] = 近子判定偏移(8斜邻+4 orth距离2)
_NEIGH_OFFS = ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1),(2,0),(-2,0),(0,2),(0,-2))
for _r in range(SIZE):
    for _c in range(SIZE):
        _dirs = []
        for _dr, _dc in DIRS:
            _cells = []
            for _k in range(-4, 5):
                _rr = _r + _dr*_k; _cc = _c + _dc*_k
                _cells.append((_rr, _cc) if 0 <= _rr < SIZE and 0 <= _cc < SIZE else None)
            _dirs.append(tuple(_cells))
        _LINE9[_r][_c] = tuple(_dirs)
        _nb = []
        for _dr, _dc in _NEIGH_OFFS:
            _rr = _r + _dr; _cc = _c + _dc
            if 0 <= _rr < SIZE and 0 <= _cc < SIZE:
                _nb.append((_rr, _cc))
        _NEIGH[_r][_c] = tuple(_nb)

def _both_tiers(board, r, c):
    """空点(r,c)分别落黑/落白后的棋型分, 与
    (pattern_tier(board,r,c,1), pattern_tier(board,r,c,2)) 严格一致。
    单趟融合+预计算几何表+免切片窗口扫描(性能轮1, 4800点等价验证)。"""
    five = [set(), set()]
    best = [0, 0]
    line9 = _LINE9[r][c]
    for d in range(4):
        cells = line9[d]
        # 构建9格线(墙=-1): 列表推导在编译态比手工 append 更快且无边界判断
        line = [-1 if p is None else board[p[0]][p[1]] for p in cells]
        c1 = line.count(1); c2 = line.count(2)
        # 单趟双算: 玩家在该方向棋子数为0则跳过; <3 不可能有成五点
        do1 = c1 >= 1; do2 = c2 >= 1
        if not (do1 or do2): continue
        five1 = c1 >= 3; five2 = c2 >= 3
        for i in (0, 1, 2, 3, 4):
            w0 = line[i]; w1 = line[i+1]; w2 = line[i+2]; w3 = line[i+3]; w4 = line[i+4]
            if w0 < 0 or w1 < 0 or w2 < 0 or w3 < 0 or w4 < 0: continue   # 含墙窗口
            c1s = (w0==1) + (w1==1) + (w2==1) + (w3==1) + (w4==1)
            c2s = (w0==2) + (w1==2) + (w2==2) + (w3==2) + (w4==2)
            opens = 0
            if i > 0 and line[i-1] == 0: opens += 1
            if i+5 < 9 and line[i+5] == 0: opens += 1
            # 玩家1(对方子=2 出现则该窗无效)
            if do1 and c2s == 0:
                if five1 and c1s == 3:
                    for j in (0, 1, 2, 3, 4):
                        if line[i+j] == 0 and (i+j) != 4:   # 落点自身不计(虚拟落子后它已是己子)
                            five[0].add(cells[i+j]); break
                cnt = c1s + 1   # 落点计入(与 _line_pattern_score 的 line[4]!=player 语义一致)
                if cnt >= 2:
                    if cnt >= 5: t = FIVE    # 落子即成五的点必须最高分, 否则会掉出候选表(治:堵五/制胜点不可见)
                    elif cnt == 4: t = LIVE4 if opens >= 1 else FOUR
                    elif cnt == 3: t = LIVE3 if opens == 2 else SLEEP3
                    elif cnt == 2: t = LIVE2 if opens == 2 else SLEEP2
                    else: t = 0
                    if t > best[0]: best[0] = t
            # 玩家2(对方子=1 出现则该窗无效)
            if do2 and c1s == 0:
                if five2 and c2s == 3:
                    for j in (0, 1, 2, 3, 4):
                        if line[i+j] == 0 and (i+j) != 4:
                            five[1].add(cells[i+j]); break
                cnt = c2s + 1
                if cnt >= 2:
                    if cnt >= 5: t = FIVE    # 落子即成五的点必须最高分
                    elif cnt == 4: t = LIVE4 if opens >= 1 else FOUR
                    elif cnt == 3: t = LIVE3 if opens == 2 else SLEEP3
                    elif cnt == 2: t = LIVE2 if opens == 2 else SLEEP2
                    else: t = 0
                    if t > best[1]: best[1] = t
    res = []
    for p in (0, 1):
        n = len(five[p])
        if best[p] >= FIVE: res.append(FIVE)      # 落子即成五: 最高优先(2026-10-08B2修, 与 pattern_tier 同步)
        elif n >= 2: res.append(LIVE4)
        elif n == 1: res.append(FOUR)
        else: res.append(best[p])
    return res[0], res[1]

def _recompute_pt(board,r,c):
    """重算空点(r,c)的两方即时分并写回缓存; 同步维护全局战术分累加值。"""
    global _PTS,_G_TAC1,_G_TAC2
    if board[r][c]!=0:
        newpt=(0,0)
    else:
        newpt=_both_tiers(board,r,c)
    old=_PTS[r][c]
    if old!=newpt:
        _G_TAC1 += newpt[0]-old[0]
        _G_TAC2 += newpt[1]-old[1]
        _PTS[r][c]=newpt

def _init_eval(board):
    global _PTS,_G_CTR,_G_TAC1,_G_TAC2
    _PTS=[[(0,0)]*SIZE for _ in range(SIZE)]
    t1=0; t2=0
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c]==0 and _near_stone(board,r,c):
                a,d=line_scores(board,r,c,1),line_scores(board,r,c,2)
                _PTS[r][c]=(a,d)
                t1+=a; t2+=d
    _G_TAC1=t1; _G_TAC2=t2
    _G_CTR=[_center_control(board,1)*8,_center_control(board,2)*8]

def _apply_move(board,r,c,p):
    """在增量评估下落子p于(r,c): 记录受影响点旧值->更新。返回undo信息。"""
    global _G_CTR
    aff=_affected_points(r,c)
    old={}
    for (rr,cc) in aff:
        old[(rr,cc)]=_PTS[rr][cc]
    board[r][c]=p
    for (rr,cc) in aff:
        _recompute_pt(board,rr,cc)
    # 中心控制: 精确增量(落子只加自己这一点的中心权重)
    _G_CTR[p-1]+= max(0, 14-(abs(r-7)+abs(c-7)))*8
    # 发展分_DEV已彻底移除(见 eval_board / _init_eval), _CTR 为唯一全局增量项
    return (aff,old,r,c,p)

def _undo_move(board,info):
    global _G_CTR,_G_TAC1,_G_TAC2
    aff,old,r,c,p=info
    board[r][c]=0
    for (rr,cc) in aff:
        oldv=old[(rr,cc)]
        cur=_PTS[rr][cc]
        if cur!=oldv:
            _G_TAC1 += oldv[0]-cur[0]
            _G_TAC2 += oldv[1]-cur[1]
            _PTS[rr][cc]=oldv
    _G_CTR[p-1]-= max(0, 14-(abs(r-7)+abs(c-7)))*8

def eval_board(board, me):
    # 战术分已由 _apply/_undo/_recompute_pt 增量维护(_G_TAC1/2), 叶子评估 O(1)
    op=3-me
    tac = _G_TAC1-_G_TAC2 if me==1 else _G_TAC2-_G_TAC1
    val = tac*1.15 + (_G_CTR[me-1]-_G_CTR[op-1])
    # 限制eval幅度远小于WIN_SCORE/WIN_TH, 避免把高分eval误判为必胜
    CAP = WIN_SCORE//100   # 1e7, 远低于 WIN_TH(1e8)
    if val>CAP: return CAP
    if val<-CAP: return -CAP
    return val

def candidates(board):
    cand=[]
    for r in range(SIZE):
        prow=board[r]
        nrow=_NEIGH[r]
        for c in range(SIZE):
            if prow[c]==0:
                for (qr,qc) in nrow[c]:
                    if board[qr][qc]!=0:
                        a,d=_PTS[r][c]
                        cand.append((a+d,r,c))
                        break
    if not cand:
        return [(7,7)] if board[7][7]==0 else [(7,8)]
    cand.sort(key=lambda x:-x[0])
    return [(r,c) for _,r,c in cand[:_CAND_LIMIT]]

def _any_four_point(player):
    """盘上是否存在'落子能成四(含以上)'的空点 —— VCF 阶段(E)的 O(225) 预检。
    依赖 _init_eval 建立的 _PTS 缓存; 无此点则 VCF 必不成立, 无需烧时间。"""
    i=player-1
    for r in range(SIZE):
        row=_PTS[r]
        for c in range(SIZE):
            if row[c][i]>=FOUR:
                return True
    return False

def has_win_at(board,p,r,c):
    """只检查经过(r,c)是否有p的五连(增量胜负判断, 比全盘has_win快)。"""
    for dr,dc in DIRS:
        cnt=1
        for s in range(1,5):
            nr,nc=r+dr*s,c+dc*s
            if 0<=nr<SIZE and 0<=nc<SIZE and board[nr][nc]==p: cnt+=1
            else: break
        for s in range(1,5):
            nr,nc=r-dr*s,c-dc*s
            if 0<=nr<SIZE and 0<=nc<SIZE and board[nr][nc]==p: cnt+=1
            else: break
        if cnt>=5: return True
    return False

def has_win(board,p):
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c]==p:
                for dr,dc in DIRS:
                    cnt=1
                    for s in range(1,5):
                        nr,nc=r+dr*s,c+dc*s
                        if 0<=nr<SIZE and 0<=nc<SIZE and board[nr][nc]==p: cnt+=1
                        else: break
                    if cnt>=5: return True
    return False

class _Timeout(Exception): pass

# 置换表: key=(zobrist_hash, depth) -> (value, flag, depth, best_move)
# (B)跨回合不清空, 加容量上限+按深度优先替换
_TT={}
_TT_MAX=2_000_000
_TT_ISOLATE=False   # 复核隔离(2026-10-08 补全双向): True 时 _search 对 TT 不读也不写。
                    # 不写: 窄窗口 bound 不得毒化主搜索(防 E 实验发现的写方向毒化);
                    # 不读: 复核不得复用主搜索在被测子树自写的 bound(裁判不得引用被告证词)。
                    # 代价: 复核变慢 -> 更易触发 level2/3 降级(守卫偏严, 不误杀由夹具监控)。
_KILLER=[None,None]   # 每层一个最佳着法(killer heuristic)
_HIST=[[0]* (SIZE*SIZE) for _ in range(3)]  # history heuristic: _HIST[player][r*SIZE+c] 累计剪枝成功着法

# ---- Zobrist 哈希表: 每个(格子,颜色)一个随机整数 ----
import random as _rnd
_rnd.seed(20260106)
_ZOBRIST=[[_rnd.getrandbits(64) for _ in range(3)] for _ in range(SIZE*SIZE)]
def _full_hash(board):
    h=0
    for r in range(SIZE):
        for c in range(SIZE):
            v=board[r][c]
            if v: h^=_ZOBRIST[r*SIZE+c][v]
    return h

def _tt_maybe_trim():
    if len(_TT)>_TT_MAX:
        for k in [k for k in list(_TT.keys()) if k[1]<=1][:400000]:
            _TT.pop(k,None)
        if len(_TT)>_TT_MAX:
            _TT.clear()

def _order_candidates(board, me, op, tt_best=None):
    """按即时威胁分排序候选; TT记录的best_move最优先, killer其次, 再按history启发。
    history分值较低, 只在同为低威胁候选时起作用, 不压制真正的急招。
    直接复用 _PTS 缓存(含me/op两侧威胁分), 不再逐点重算 win_points_after。"""
    scored=[]
    hist=_HIST[me]
    for (r,c) in candidates(board):
        a,d=_PTS[r][c]                 # (玩家1分, 玩家2分)
        s = (a if me==1 else d) + (d if me==1 else a)*0.9
        if tt_best and (r,c)==tt_best: s+=2e9
        if _KILLER[0]==(r,c) or _KILLER[1]==(r,c): s+=1e8
        s += hist[r*SIZE+c]             # history 分级分值(通常远小于1e8)
        scored.append((s,r,c))
    scored.sort(key=lambda x:-x[0])
    return [(r,c) for _,r,c in scored]

def _search(board, me, depth, alpha, beta, hsh):
    # 注意: 调用方保证进入时"上一手没直接赢"(已用has_win_at过滤), 故此处不再全盘扫描胜负
    if depth==0:
        return eval_board(board,me)
    op=3-me
    tt_best=None
    if not _TT_ISOLATE:
        ent=_TT.get((hsh,depth))
        if ent is not None:
            val,flag,_d,tt_best=ent
            if flag==0: return val
            if flag==1 and val>=beta: return val
            if flag==-1 and val<=alpha: return val
    best=-10**9
    orig_alpha=alpha
    best_mv=None
    cands=_order_candidates(board, me, op, tt_best)
    first=True
    for (r,c) in cands:
        if _DEADLINE is not None and _tm.time()>_DEADLINE:
            raise _Timeout()
        info=_apply_move(board,r,c,me)   # 增量落子(含评估更新)
        # 超时安全(2026-10-08B, #38样本parity异常定位): 递归 _Timeout 穿出时必须撤销本手,
        # 否则整条 pv 线的未撤销落子会污染 best_move 后续深度迭代与复核(脏盘上验证"必胜")。
        win_now=False; v=None
        try:
            nh=hsh^_ZOBRIST[r*SIZE+c][me]
            if has_win_at(board,me,r,c):     # 我这手直接赢
                win_now=True
            elif first:
                v=-_search(board,op,depth-1,-beta,-alpha,nh)
                first=False
            else:
                # PVS: 零窗口试探, 失败高位补全窗口
                v=-_search(board,op,depth-1,-alpha-1,-alpha,nh)
                if alpha < v < beta:
                    v=-_search(board,op,depth-1,-beta,-alpha,nh)
        finally:
            _undo_move(board,info)
        if win_now:
            best=WIN_SCORE+depth; best_mv=(r,c)
            alpha=max(alpha,best)
            break
        if v>best:
            best=v; best_mv=(r,c)
            if v>alpha:
                alpha=v
                _KILLER[1]=_KILLER[0]; _KILLER[0]=(r,c)
        if alpha>=beta:
            # beta截断: 该着法证明有效, 计history(分值随深度增大), 优先在后续排序
            _HIST[me][r*SIZE+c] += depth*depth
            break
        else:
            # 仅当该着法成为当前最佳(更新了best)时才轻微计history, 避免"v>0恒真"把所有候选均匀灌满
            if v == best:
                _HIST[me][r*SIZE+c] += 1
    # 存TT: flag 0=exact, 1=lowerbound(剪枝), -1=upperbound
    if not _TT_ISOLATE:
        old=_TT.get((hsh,depth))
        if old is None or old[2]<=depth:   # depth-preferred 替换
            if best>=beta: flag=1
            elif best<=orig_alpha: flag=-1
            else: flag=0
            _TT[(hsh,depth)]=(best,flag,depth,best_mv)
        _tt_maybe_trim()
    return best

def _winning_points(board, player, _check=False):
    """返回所有'落子即成五'的空点(天然支持跳空: 落子后has_win检查整线)
    若 _check=True 则扫描中检查 _DEADLINE, 超时抛 _Timeout, 防止VCF/VCT递归里全盘扫爆时长。"""
    pts=[]
    for r in range(SIZE):
        if _check and _DEADLINE is not None and _tm.time()>_DEADLINE:
            raise _Timeout()
        for c in range(SIZE):
            if board[r][c]==0:
                board[r][c]=player
                if has_win_at(board,player,r,c): pts.append((r,c))
                board[r][c]=0
    return pts

def win_points_after(board, r, c, player):
    """核心判定(治①②④): 假设player在(r,c)落子后, 返回'能一步成五的空点集合'(去重、含跳空)。
    活四/双杀 = |集合|>=2; 冲四 = ==1。只考察受(r,c)影响的方向线, 高效且正确。"""
    # 临时落子
    board[r][c]=player
    pts=set()
    # 只看经过(r,c)的四条方向线上、能补成五的空点
    for dr,dc in DIRS:
        # 收集该方向上以(r,c)为中心的一段(前后各4格)
        line=[]
        coords=[]
        for k in range(-4,5):
            rr=r+dr*k; cc=c+dc*k
            if 0<=rr<SIZE and 0<=cc<SIZE:
                line.append(board[rr][cc]); coords.append((rr,cc))
            else:
                line.append(-1); coords.append(None)  # -1=墙
        n=len(line)
        # 滑窗长度5: 若窗口内 player子数==4 且 空==1 且 无对方/墙 -> 那个空就是成五点
        for i in range(n-4):
            seg=line[i:i+5]
            if -1 in seg or (3-player) in seg: continue
            if seg.count(player)==4:
                # 找到唯一的空位
                for j in range(5):
                    if seg[j]==0:
                        pts.add(coords[i+j])
    board[r][c]=0
    # 排除(r,c)本身(它已落子)
    pts.discard((r,c))
    return set(pts)

def _line_pattern_score(board,r,c,player):
    """无直接成五点时, 用'5格窗口内己方子数(允许跳空)'评估该点各方向最强棋型。
    能识别跳空活三 X_XX / XX_X、跳空活二 X_XX 等, 修复连续子计数把它们评成1分的问题。"""
    opp=3-player
    best=0
    for dr,dc in DIRS:
        # 过(r,c)取一段线(前后4), 滑窗长度5: 统计每窗 player数(含落点)且无对方/墙
        line=[];coords=[]
        for k in range(-4,5):
            rr=r+dr*k; cc=c+dc*k
            if 0<=rr<SIZE and 0<=cc<SIZE:
                line.append(board[rr][cc]); coords.append((rr,cc))
            else:
                line.append(-1); coords.append(None)
        n=len(line)
        dir_best=0
        for i in range(n-4):
            seg=line[i:i+5]
            if -1 in seg or opp in seg: continue
            # (r,c)在line中固定下标4; 统计窗口内player数, 落点若未被计入则+1
            cnt=seg.count(player)
            if line[4]!=player:   # 落点当前不是player(未真正落子), 需计入
                cnt+=1
            # 两端开放判断: 窗口外一格是否空
            left_open = (i-1>=0 and line[i-1]==0)
            right_open = (i+5<n and line[i+5]==0)
            opens=int(left_open)+int(right_open)
            if cnt>=5:
                t = FIVE    # 落子即成五的点必须最高分(治:五点/堵点不可见)
            elif cnt==4:
                t = LIVE4 if opens>=1 else FOUR
            elif cnt==3:
                t = LIVE3 if opens==2 else SLEEP3
            elif cnt==2:
                t = LIVE2 if opens==2 else SLEEP2
            else:
                t = 0
            if t>dir_best: dir_best=t
        if dir_best>best: best=dir_best
    return best

def pattern_tier(board, r, c, player):
    """落子(r,c)后的棋型等级。先看成五点集合(活四/冲四), 再用跳空窗口评活三/活二等。"""
    lp = _line_pattern_score(board,r,c,player)
    if lp >= FIVE:
        return FIVE   # 落子即成五(2026-10-08B2修): 此前一端可延伸的成五点会被 win_points_after
                      # 的延伸点误归为 FOUR(如实战误案: 斜四补口后线尾还有一空->wp={尾}->判冲四)
    wp=win_points_after(board,r,c,player)
    n=len(wp)
    if n>=2:
        return LIVE4          # 两个及以上成五点 = 活四/双杀级(必胜)
    if n==1:
        return FOUR           # 单成五点 = 冲四(急)
    return lp

def _four_points(board, player, _check=False):
    """返回所有'落子后能制造成五点(含跳空冲四)'的点 —— 供VCF枚举, 基于成五点集合(治④根)。
    若 _check=True 扫描中检查 _DEADLINE, 超时抛 _Timeout。"""
    pts=[]
    for r in range(SIZE):
        if _check and _DEADLINE is not None and _tm.time()>_DEADLINE:
            raise _Timeout()
        for c in range(SIZE):
            if board[r][c]==0 and _near_stone(board,r,c):
                if len(win_points_after(board,r,c,player))>=1:
                    pts.append((r,c))
    return pts

def vcf_search(board, attacker, defender, depth=6):
    """VCF: 攻击方连续冲四/做杀能否强制取胜。返回获胜第一步或None。
    超时安全(2026-10-07复查修): 所有临时落子用 try/finally 撤销 ——
    扫描过期抛出的 _Timeout 穿出时不会在盘上残留'幽灵子'。"""
    def rec(bd, atk, dep):
        if dep<=0 or (_DEADLINE is not None and _tm.time()>_DEADLINE):
            return False
        # 攻击方先找直接成五
        wp=_winning_points(bd,atk,_check=True)
        if wp: return True
        # 否则走冲四逼招: 对每个能造出'对方必应'的冲四点
        for (r,c) in _four_points(bd,atk,_check=True):
            bd[r][c]=atk
            try:
                # 防守方强应点 = 攻击方的成五点集合
                must=_winning_points(bd,atk,_check=True)
                distinct = set(must)
                if len(distinct)>=2 and len(must)>=2:
                    # 双杀式冲四: 同一手造出>=2个不同位置的成五点, 防守方一子挡不完 -> 必胜
                    return True
                if must:
                    # 单成五点: 防守方唯一应招就是堵它; 逐个试挡所有成五点, 任一种挡完攻击方仍有强制胜即成立
                    blocked_all=True
                    for br,bc in must:
                        bd[br][bc]=3-atk
                        try:
                            # 防守方反击: 堵子这一手若同时形成己方冲四(成五威胁), 攻击链被打断(保守处理, 杜绝误报必胜)
                            if win_points_after(bd, br, bc, 3-atk):
                                blocked_all=False; break
                            sub=rec(bd,atk,dep-1)
                        finally:
                            bd[br][bc]=0
                        if not sub:
                            blocked_all=False; break
                    if blocked_all: return True
            finally:
                bd[r][c]=0
        return False
    # 尝试攻击方每个候选作为VCF第一手
    for (r,c) in candidates(board):
        if _DEADLINE is not None and _tm.time()>_DEADLINE:
            break
        board[r][c]=attacker
        try:
            win=rec(board, attacker, depth)
        finally:
            board[r][c]=0
        if win:
            return (r,c)
    return None

def _opponent_has_forcing_win(board, op, depth=6):
    """检测对方(op)是否存在VCF强制取胜。返回True/False。
    超时安全: 同 vcf_search, 所有临时落子 try/finally 撤销。"""
    def rec(bd, dep):
        if dep<=0 or (_DEADLINE is not None and _tm.time()>_DEADLINE):
            return False
        # 对方直接成五点?
        if _winning_points(bd,op,_check=True): return True
        for (r,c) in _four_points(bd,op,_check=True):
            bd[r][c]=op
            try:
                must=_winning_points(bd,op,_check=True)
                distinct = set(must)
                if len(distinct)>=2 and len(must)>=2:   # 双杀式冲四, 一子挡不完 -> 对方必胜
                    return True
                if must:
                    # 逐个试挡所有成五点; 防守方(我方)的堵子若同时形成己方冲四, 对方连击链被打断
                    # -> 该冲四不成立(对称修复, 避免 C 路径误判对方有杀)
                    blocked_all=True
                    for br,bc in must:
                        bd[br][bc]=3-op
                        try:
                            if win_points_after(bd, br, bc, 3-op):
                                blocked_all=False; break
                            sub=rec(bd,dep-1)
                        finally:
                            bd[br][bc]=0
                        if not sub:
                            blocked_all=False; break
                    if blocked_all: return True
            finally:
                bd[r][c]=0
        return False
    for (r,c) in candidates(board):
        if _DEADLINE is not None and _tm.time()>_DEADLINE:
            break
        board[r][c]=op
        try:
            w=rec(board,depth)
        finally:
            board[r][c]=0
        if w: return True
    return False

def defensive_vct(board, my_side, op, cands):
    """对方有强制杀招时, 选一手拆掉它; 在能拆的点里优先保留我方进攻的。
    返回(r,c)或None。"""
    # 先算对方当前的"直接成五点"(必须堵的), 缩小要试的拆招范围
    opp_wins=set(_winning_points(board,op))
    scored=[]
    for (r,c) in cands:
        board[r][c]=my_side
        try:
            # 快速判断: 落子后对方是否仍有强制胜(浅一点, 省时)
            still_deadly=_opponent_has_forcing_win(board, op, depth=4)
        finally:
            board[r][c]=0
        if not still_deadly:
            atk=line_scores(board,r,c,my_side)
            # 若该点还能堵住对方一个成五点, 加分(更稳)
            bonus=1e7 if (r,c) in opp_wins else 0
            scored.append((atk+bonus,r,c))
            if len(scored)>=6:   # 找到足够多拆招就停, 省时
                break
    if scored:
        scored.sort(key=lambda x:-x[0])
        return (scored[0][1], scored[0][2])
    return None

def new_game():
    """开新对局时调用: 清空置换表(局内复用, 跨局不残留)、重置killer/history。"""
    _TT.clear()
    _KILLER[0]=None; _KILLER[1]=None
    _HIST[1][:]=[0]*(SIZE*SIZE)
    _HIST[2][:]=[0]*(SIZE*SIZE)

# ---- 开局库: KataGomo(b10c128无禁手)离线挖掘的前N手强手, 查表O(1), 不占思考时间 ----
# 文件 gomoku_opening_book.json 与引擎同目录(exe内嵌于 _MEIPASS); 键=对称归一化局面串
import os as _os, sys as _sys, json as _json
_BOOK=None
_BOOK_MAX_STONES=6   # 只在盘面<=6子时查表(覆盖前0~6手)

def _load_book():
    global _BOOK
    if _BOOK is None:
        try:
            base=getattr(_sys,'_MEIPASS',None) or _os.path.dirname(_os.path.abspath(__file__))
            with open(_os.path.join(base,'gomoku_opening_book.json'),'r',encoding='utf-8') as f:
                _BOOK=_json.load(f).get('entries',{})
        except Exception:
            _BOOK={}
    return _BOOK

def _build_syms():
    """8个棋盘对称变换(4旋转x2翻转), 返回[(正变换,逆变换)], 作用于(r,c)。"""
    def compose(f,g):
        return lambda p: f(g(p))
    def rot90(p):
        r,c=p; return (c,SIZE-1-r)
    def flip(p):
        r,c=p; return (r,SIZE-1-c)
    syms=[]
    rot=(lambda p:p)
    for _ in range(4):
        for f in (rot, compose(flip,rot)):
            inv={}
            for r in range(SIZE):
                for c in range(SIZE):
                    inv[f((r,c))]=(r,c)
            syms.append((f, lambda p,inv=inv: inv[p]))
        rot=compose(rot90,rot)
    return syms
_SYM=_build_syms()

def _canon_board(board):
    """局面串的8对称规范形: 返回(最小串, 所用变换下标)。"""
    s="".join(str(board[r][c]) for r in range(SIZE) for c in range(SIZE))
    best=None; bi=0
    for i,(f,inv) in enumerate(_SYM):
        cells=['']*(SIZE*SIZE)
        for r in range(SIZE):
            for c in range(SIZE):
                rr,cc=f((r,c))
                cells[rr*SIZE+cc]=s[r*SIZE+c]
        ts="".join(cells)
        if best is None or ts<best:
            best=ts; bi=i
    return best,bi

def _book_lookup(board):
    """查开局库: 命中返回当前坐标系下的(r,c), 未命中返回None。"""
    stones=0
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r][c]:
                stones+=1
                if stones>_BOOK_MAX_STONES: return None
    B=_load_book()
    if not B: return None
    key,bi=_canon_board(board)
    ent=B.get(key)
    if not ent: return None
    return _SYM[bi][1](tuple(ent["mv"]))

def best_move(board, my_side):
    global _DEADLINE
    _DEADLINE=None   # 全局状态卫生(防御): 上一手若异常穿出可能残留过期deadline, 入口清零
    # 关键: 深拷贝一份用于搜索, 绝不改动调用方传入的原board
    # (内部_search/vcf/defensive等会临时落子再撤销, 若中途超时异常会泄漏)
    board=[row[:] for row in board]
    pristine=[row[:] for row in board]   # 干净快照: 搜索超时穿出时 board 可能有未撤销的临时落子,
                                         # 结尾 reason 判读一律用本快照(与搜索前真实局面一致)
    # TT 改为"局内共享"(由 new_game 在开新局时清空), 不再每步清 -> 复用本局转置局面
    _init_eval(board)   # 初始化增量评估缓存(candidates/eval依赖它)
    empties=sum(row.count(0) for row in board)
    if empties==0: return None,"棋盘已满"
    op=3-my_side
    # ---- 开局库(C): 极早期稳健应招 ----
    cands=list(candidates(board))
    if not cands:
        cands=[(7,7)] if board[7][7]==0 else [(7,8)]
    best=None; bestv=-10**9

    # ===== 攻防优先级链 A–G（治③：对方已有必杀优先于我方造杀）=====
    # A. 我方一步成五 -> 立即赢(最高, 唯一可越过防守的例外)
    for (r,c) in cands:
        board[r][c]=my_side
        w=has_win_at(board,my_side,r,c)
        board[r][c]=0
        if w:
            return (r,c),"直接连成五个，赢！"

    # B. 对方一步成五 -> 必须堵
    digs=[]
    for (r,c) in cands:
        board[r][c]=op
        if has_win_at(board,op,r,c): digs.append((r,c))
        board[r][c]=0
    if digs:
        return digs[0],"对方再走一步就连五了，必须先堵住这里！"

    # C. 对方有 VCF 强制胜 -> 拆（递归验证真拆干净）
    if empties<=44:
        _DEADLINE=_tm.time()+0.6
        try:
            opp_deadly=_opponent_has_forcing_win(board, op, depth=6)
            df=None
            if opp_deadly:
                df=defensive_vct(board, my_side, op, cands)
        except Exception:
            df=None
        _DEADLINE=None
        if df is not None:
            return df,"对方有连续做杀的攻势，先拆掉它的杀招！"

    # D(防双杀)已移除: 原"盲堵第一个双杀点"在多点双杀/冲四+活三组合下会选错防点
    # (用户实战局教训: (7,5)/(3,5) 两端只堵一端仍输)。五分点可见性修复后,
    # 搜索自身能看见 FIVE 级威胁并选最优防守 —— 交由 G 搜索。

    # ---- 开局库: KataGomo离线挖掘的强手(查表O(1)) ----
    # 位置在 A/B/C 之后: 战术安全(必胜/必堵/拆杀)永远优先于开局库;
    # 未命中的局面照常走搜索。
    bm=_book_lookup(board)
    if bm is not None:
        return bm,"开局库强手（KataGomo离线分析）。"

    # ---- 搜索共用设施(提前构造, E 与 G 共享): budget/根哈希/WIN_TH/必胜复核 ----
    budget=2.0  # 秒/步 (历史: 8s→4s→2s; 编译+算法优化后 2s 即达旧 4s 的深度, A/B 12局 7:5 无损)
    WIN_TH=E_WIN = 10**8   # 只有真实必胜(远高eval上限)才算; 由浅入深首个即最短胜法
    root_hash=_full_hash(board)   # 根局面zobrist哈希, 落子时增量XOR更新
    _vcount=[0]   # 每步复核次数上限(E+G 共享, 防成本叠加)
    def _verify_win(mv, d):
        """WIN_TH 复核+证伪值钳制(2026-10-07, 符号修复后升级)。negamax 约定:
        _search(board, X, ...) 返回轮走方 X 视角价值, 勿再取负。
        返回 (accept, bound):
          accept=True  -> 全部对方应招都被证明挡不住(每步 v2 有 >=WIN_TH 的下界), 宣告最短胜;
          accept=False -> bound=证伪值(真值上界): level1=全程 min / level2=超时前部分 min /
                          bound=None -> 调用方按 level3 钳到 1e7(最坏诚实度)。
        证伪值让幻觉着以诚实上界参与本层竞争, 而不是被弃用/顶格, 也避免假收敛。
        定位声明(2026-10-08 审查会): accept="top-10 应招集全过+vd内杀穿"仍是候选集内验证,
        与 E 二次实验的死因②共享同一剪枝偏差 —— 本守卫是降概率止血带非证明;
        放行精确率实测=收割样本 12/12(95%置信上界约22%), 扩样是 ④ 的任务。"""
        global _DEADLINE, _TT_ISOLATE
        m=10**9   # 先于任何可超时代码定义(超时兜底引用它)
        vr,vc=mv
        info=_apply_move(board,vr,vc,my_side)
        try:
            if has_win_at(board,my_side,vr,vc): return True,None   # 直接成五, 无可辩驳
            # 全宽: 对方立即成五 = 这手自杀 -> 钳到底
            for r_ in range(SIZE):
                for c_ in range(SIZE):
                    if board[r_][c_]==0:
                        board[r_][c_]=op
                        bad=has_win_at(board,op,r_,c_)
                        board[r_][c_]=0
                        if bad: return False,-(10**9)
            vd=max(2,d-2)   # 深度对齐: M(1)+应招(1)+vd = 主搜索 1+(d-1)
            rh=root_hash^_ZOBRIST[vr*SIZE+vc][my_side]
            replies=list(candidates(board))
            replies.sort(key=lambda rc:-_PTS[rc[0]][rc[1]][op-1])  # 见证排序: 最强证伪先查, 利于窗口跳过
            prev_nw=_TT_ISOLATE
            prev_k=_KILLER[:]            # 旁路无残留(DECISIONS #13规则): killer/history 同属主搜索
            prev_h1=_HIST[1][:]; prev_h2=_HIST[2][:]   # 状态, 复核期间的排序偏好不得泄漏回主搜索
            _TT_ISOLATE=True   # 复核双向隔离: 不读主TT(避免复用被测子树自写的bound), 不写(防毒化)
            try:
                for (br,bc) in replies:
                    info2=_apply_move(board,br,bc,op)
                    try:
                        if has_win_at(board,op,br,bc): return False,-(10**9)
                        # 见证旁路: 对方应招后我方有立即成五(必为高威胁分, 在候选内) -> 该应招免费通过
                        free=False
                        for (er,ec) in candidates(board):
                            board[er][ec]=my_side
                            if has_win_at(board,my_side,er,ec): free=True
                            board[er][ec]=0
                            if free: break
                        if free: continue
                        # 窗口 (-1e9, min(m,WIN_TH)): 返回<beta 为精确值(更新m); >=beta 为下界(>=beta 即可证 v2>=m 或 >=WIN_TH, 跳过)
                        beta = m if m < WIN_TH else WIN_TH
                        v2=_search(board,my_side,vd,-10**9,beta,rh^_ZOBRIST[br*SIZE+bc][op])
                        if v2 < beta: m=v2
                    finally:
                        _undo_move(board,info2)
            finally:
                _TT_ISOLATE=prev_nw
                _KILLER[:]=prev_k; _HIST[1][:]=prev_h1; _HIST[2][:]=prev_h2
            if m >= WIN_TH: return True,None   # 全部应招都有 >=WIN_TH 的下界
            return False,m
        except _Timeout:
            return False,(m if m < WIN_TH else None)   # m 未定义兜底: 超时前无更新 -> None(level3)
        finally:
            _undo_move(board,info)

    # E. 我方 VCF 强制胜 -> 抢先杀
    # (2026-10-07/08 两次开门实验均显著回退: 四点预检中盘高频命中致 vcf 白烧时间 +
    #  候选集内可验证!=真胜(A/B 4:8 与 4:12)。E 保持休眠; 复活唯一前提=节点级威胁注入架构)
    if empties<=40:
        _DEADLINE=_tm.time()+0.5
        try:
            vcf=vcf_search(board, my_side, op, depth=8)
        except Exception:
            vcf=None
        _DEADLINE=None
        if vcf is not None:
            return vcf,"用连续冲四/做杀，能强制取胜！"

    # F. 我方双杀 -> 走
    for (r,c) in cands:
        if double_win(board,r,c,my_side):
            return (r,c),"在这里能同时制造两个威胁，对方怎么挡都挡不住。"

    # ---- 迭代加深搜索(用时间预算控制深度; budget/复核设施已在 E 前构造) ----
    _DEADLINE=_tm.time()+budget
    root_deadline=_DEADLINE
    final_best=None; final_bestv=-10**9
    prev_best=None   # 上一次迭代的最优着法, 用于本层优先搜索(提升剪枝效率)
    prev_bestv=None  # 上一次迭代的最优分值(时间管理: 收敛判定用)
    for d in (2,3,4,5,6,7,8):
        if _tm.time()>_DEADLINE:
            break
        ordered=list(cands)
        if prev_best and prev_best in ordered:
            ordered.remove(prev_best); ordered.insert(0,prev_best)
        cur=None; curv=-10**9
        try:
            for (r,c) in ordered:
                if _DEADLINE is not None and _tm.time()>_DEADLINE:
                    # 候选级中断: 剩余时间不足即停止本层, 避免单层跑完才停
                    break
                info=_apply_move(board,r,c,my_side)
                nh=root_hash^_ZOBRIST[r*SIZE+c][my_side]
                try:
                    win_now = has_win_at(board,my_side,r,c)
                    if not win_now:
                        v=-_search(board,op,d-1,-10**9,-curv,nh)
                finally:
                    _undo_move(board,info)   # 超时穿出同样必须撤销(#38根因)
                if win_now:
                    _DEADLINE=None
                    return (r,c),"这一步能强制取胜（选的是最快赢的路径）！"   # 可判定: 直接成五
                timedout = _DEADLINE is not None and _tm.time()>_DEADLINE
                if v>=WIN_TH:
                    # WIN_TH 是剪枝集内证据非证明 -> 立即复核; 被证伪时用证伪值(真值上界)
                    # 参与本层竞争, 其余候选随之获得正常窗口
                    if _vcount[0] >= 2 or timedout:
                        v=10**7                       # level3: 无预算复核 -> 顶格(最坏诚实度)
                    else:
                        _vcount[0]+=1
                        _DEADLINE=_tm.time()+min(0.9, budget*0.45)
                        try:
                            accept,bound=_verify_win((r,c), d)
                        finally:
                            _DEADLINE=root_deadline
                        if accept:
                            _DEADLINE=None
                            # 文案带"复核通过"标记: 与守卫定位声明对齐(候选集内验证非数学证明)
                            return (r,c),"这一步能强制取胜（复核通过，选的是最快赢的路径）！"
                        v = bound if bound is not None else 10**7   # level1/2 降级, 超时未算->level3
                if timedout:
                    # 该候选搜完已超时: 仍采纳其结果(若有), 但不再搜本层其余候选
                    if v>curv:
                        curv=v; cur=(r,c)
                    break
                if v>curv:
                    curv=v; cur=(r,c)
        except _Timeout:
            pass
        if cur is not None:
            # 时间管理(提前收敛退出): 连续两次迭代选点相同且分值未剧烈波动 -> 局面已收敛,
            # 无需烧满预算; 选点仍在翻转的困难局面自动用满预算
            converged = (curv < WIN_TH and d >= 4 and cur == prev_best
                         and prev_bestv is not None and abs(curv - prev_bestv) <= 2*10**6)
            final_best, final_bestv = cur, curv
            prev_best, prev_bestv = cur, curv
            if converged:
                _DEADLINE=None
                break
    _DEADLINE=None
    best = final_best if final_best else cands[0]
    if best is None:
        best=(7,7)
    # 理由(基于新分级: LIVE4=1e6, FOUR=1e5, LIVE3=5e4)
    # 用 pristine 快照判读: 超时异常穿出时 board 残留脏子, 文案必须基于真实局面
    a=threat(pristine,best[0],best[1],my_side); d=threat(pristine,best[0],best[1],op)
    if a>=LIVE4: reason="形成活四/双杀，对方挡不住了。"
    elif a>=FOUR: reason="冲四，逼对方必须应。"
    elif d>=LIVE4: reason="抢先占住能破坏对方活四/双杀的关键点。"
    elif d>=FOUR: reason="堵住对方即将成四的致命一线。"
    elif a>=LIVE3: reason="做成活三，两头都开，下一步成活四。"
    elif d>=LIVE3: reason="先拦住对方的活三。"
    else: reason="稳固发展，兼顾攻防。"
    return best, reason


if __name__=="__main__":
    b=[[0]*SIZE for _ in range(SIZE)]
    for i in range(4): b[5][i+3]=2
    m,_=best_move(b,1)
    print("对方白四连，黑应堵:", m)