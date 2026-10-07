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
    for dr,dc in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1),(2,0),(-2,0),(0,2),(0,-2)):
        rr=r+dr; cc=c+dc
        if 0<=rr<SIZE and 0<=cc<SIZE and board[rr][cc]!=0:
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

def _both_tiers(board, r, c):
    """空点(r,c)分别落黑/落白后的棋型分, 与
    (pattern_tier(board,r,c,1), pattern_tier(board,r,c,2)) 严格一致。
    单趟融合: 每方向只建一次线, 按双方棋子数跳过不可能有结果的扫描(性能热点,治于profile)。"""
    out = [[], []]   # 每玩家: [fivepts集合引用, dir_best]
    five = [set(), set()]
    best = [0, 0]
    for dr, dc in DIRS:
        line = []; coords = []
        c1 = c2 = 0
        for k in range(-4, 5):
            rr = r + dr*k; cc = c + dc*k
            if 0 <= rr < SIZE and 0 <= cc < SIZE:
                v = board[rr][cc]
                line.append(v); coords.append((rr, cc))
                if v == 1: c1 += 1
                elif v == 2: c2 += 1
            else:
                line.append(-1); coords.append(None)
        # 单趟双算: 每个窗口同时为黑白双方评分(玩家在该方向棋子数为0则跳过; <3 不可能有成五点)
        do1 = c1 >= 1; do2 = c2 >= 1
        five1 = c1 >= 3; five2 = c2 >= 3
        if not (do1 or do2): continue
        for i in range(5):
            seg = line[i:i+5]
            if -1 in seg: continue
            c1s = seg.count(1); c2s = seg.count(2)
            left_open = (i-1 >= 0 and line[i-1] == 0)
            right_open = (i+5 < 9 and line[i+5] == 0)
            opens = int(left_open) + int(right_open)
            # 玩家1(对方子=2 出现则该窗无效)
            if do1 and c2s == 0:
                if five1 and c1s == 3:
                    for j in range(5):
                        if seg[j] == 0 and (i+j) != 4:   # 落点自身不计(虚拟落子后它已是己子)
                            five[0].add(coords[i+j]); break
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
                    for j in range(5):
                        if seg[j] == 0 and (i+j) != 4:
                            five[1].add(coords[i+j]); break
                cnt = c2s + 1
                if cnt >= 2:
                    if cnt >= 5: t = FIVE    # 落子即成五的点必须最高分
                    elif cnt == 4: t = LIVE4 if opens >= 1 else FOUR
                    elif cnt == 3: t = LIVE3 if opens == 2 else SLEEP3
                    elif cnt == 2: t = LIVE2 if opens == 2 else SLEEP2
                    else: t = 0
                    if t > best[1]: best[1] = t
    for p in (1, 2):
        n = len(five[p-1])
        if n >= 2: out[p-1] = LIVE4
        elif n == 1: out[p-1] = FOUR
        else: out[p-1] = best[p-1]
    return out[0], out[1]

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
        for c in range(SIZE):
            if board[r][c]==0 and _near_stone(board,r,c):
                a,d=_PTS[r][c]
                cand.append((a+d,r,c))
    if not cand:
        return [(7,7)] if board[7][7]==0 else [(7,8)]
    cand.sort(key=lambda x:-x[0])
    return [(r,c) for _,r,c in cand[:_CAND_LIMIT]]

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
        nh=hsh^_ZOBRIST[r*SIZE+c][me]
        if has_win_at(board,me,r,c):     # 我这手直接赢
            _undo_move(board,info)
            best=WIN_SCORE+depth; best_mv=(r,c)
            alpha=max(alpha,best)
            break
        # PVS: 首着全窗口, 其余零窗口试探(着法排序质量高时省大量节点); 试探失败高位再补全窗口
        if first:
            v=-_search(board,op,depth-1,-beta,-alpha,nh)
            first=False
        else:
            v=-_search(board,op,depth-1,-alpha-1,-alpha,nh)
            if alpha < v < beta:
                v=-_search(board,op,depth-1,-beta,-alpha,nh)
        _undo_move(board,info)
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
    wp=win_points_after(board,r,c,player)
    n=len(wp)
    if n>=2:
        return LIVE4          # 两个及以上成五点 = 活四/双杀级(必胜)
    if n==1:
        return FOUR           # 单成五点 = 冲四(急)
    # 没有直接成五点: 用跳空窗口评估活三/眠三/活二(修复跳空三被评成1分的下偏)
    return _line_pattern_score(board,r,c,player)

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
    """VCF: 攻击方连续冲四/做杀能否强制取胜。返回获胜第一步或None。"""
    def rec(bd, atk, dep):
        if dep<=0 or (_DEADLINE is not None and _tm.time()>_DEADLINE):
            return False
        # 攻击方先找直接成五
        wp=_winning_points(bd,atk,_check=True)
        if wp: return True
        # 否则走冲四逼招: 对每个能造出'对方必应'的冲四点
        for (r,c) in _four_points(bd,atk,_check=True):
            bd[r][c]=atk
            # 防守方强应点 = 攻击方的成五点集合
            must=_winning_points(bd,atk,_check=True)
            distinct = set(must)
            if len(distinct)>=2 and len(must)>=2:
                # 双杀式冲四: 同一手造出>=2个不同位置的成五点, 防守方一子挡不完 -> 必胜
                bd[r][c]=0
                return True
            if must:
                # 单成五点: 防守方唯一应招就是堵它; 逐个试挡所有成五点, 任一种挡完攻击方仍有强制胜即成立
                blocked_all=True
                for br,bc in must:
                    bd[br][bc]=3-atk
                    # 防守方反击: 堵子这一手若同时形成己方冲四(成五威胁), 攻击链被打断(保守处理, 杜绝误报必胜)
                    if win_points_after(bd, br, bc, 3-atk):
                        blocked_all=False; bd[br][bc]=0; break
                    sub=rec(bd,atk,dep-1)
                    bd[br][bc]=0
                    if not sub:
                        blocked_all=False; break
                bd[r][c]=0
                if blocked_all: return True
            else:
                bd[r][c]=0
        return False
    # 尝试攻击方每个候选作为VCF第一手
    for (r,c) in candidates(board):
        if _DEADLINE is not None and _tm.time()>_DEADLINE:
            break
        board[r][c]=attacker
        win=rec(board, attacker, depth)
        board[r][c]=0
        if win:
            return (r,c)
    return None

def _opponent_has_forcing_win(board, op, depth=6):
    """检测对方(op)是否存在VCF强制取胜。返回True/False。"""
    def rec(bd, dep):
        if dep<=0 or (_DEADLINE is not None and _tm.time()>_DEADLINE):
            return False
        # 对方直接成五点?
        if _winning_points(bd,op,_check=True): return True
        for (r,c) in _four_points(bd,op,_check=True):
            bd[r][c]=op
            must=_winning_points(bd,op,_check=True)
            distinct = set(must)
            if len(distinct)>=2 and len(must)>=2:   # 双杀式冲四, 一子挡不完 -> 对方必胜
                bd[r][c]=0
                return True
            if must:
                # 逐个试挡所有成五点; 防守方(我方)的堵子若同时形成己方冲四, 对方连击链被打断
                # -> 该冲四不成立(对称修复, 避免 C 路径误判对方有杀)
                blocked_all=True
                for br,bc in must:
                    bd[br][bc]=3-op
                    if win_points_after(bd, br, bc, 3-op):
                        blocked_all=False; bd[br][bc]=0; break
                    sub=rec(bd,dep-1)
                    bd[br][bc]=0
                    if not sub:
                        blocked_all=False; break
                bd[r][c]=0
                if blocked_all: return True
            else:
                bd[r][c]=0
        return False
    for (r,c) in candidates(board):
        if _DEADLINE is not None and _tm.time()>_DEADLINE:
            break
        board[r][c]=op
        w=rec(board,depth)
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
        # 快速判断: 落子后对方是否仍有强制胜(浅一点, 省时)
        still_deadly=_opponent_has_forcing_win(board, op, depth=4)
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
    # 关键: 深拷贝一份用于搜索, 绝不改动调用方传入的原board
    # (内部_search/vcf/defensive等会临时落子再撤销, 若中途超时异常会泄漏)
    board=[row[:] for row in board]
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

    # E. 我方 VCF 强制胜 -> 抢先杀
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

    # ---- 迭代加深搜索(用时间预算控制深度) ----
    budget=2.0  # 秒/步 (历史: 8s→4s→2s; 编译+算法优化后 2s 即达旧 4s 的深度, A/B 12局 7:5 无损)
    _DEADLINE=_tm.time()+budget
    final_best=None; final_bestv=-10**9
    root_hash=_full_hash(board)   # 根局面zobrist哈希, 落子时增量XOR更新
    prev_best=None   # 上一次迭代的最优着法, 用于本层优先搜索(提升剪枝效率)
    prev_bestv=None  # 上一次迭代的最优分值(时间管理: 收敛判定用)
    WIN_TH=E_WIN = 10**8   # 只有真实必胜(远高eval上限)才算; 由浅入深首个即最短胜法
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
                if has_win_at(board,my_side,r,c):
                    _undo_move(board,info)
                    cur=(r,c); curv=WIN_TH+d; break
                # 根层传已找到的最佳值作为上界: child搜索窗口(-1e9, -cur) -> 兄弟候选可据此剪枝
                v=-_search(board,op,d-1,-10**9,-curv,nh)
                _undo_move(board,info)
                if _DEADLINE is not None and _tm.time()>_DEADLINE:
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
            # 无需烧满预算; 选点仍在翻转的困难局面自动用满 4 秒
            converged = (curv < WIN_TH and d >= 4 and cur == prev_best
                         and prev_bestv is not None and abs(curv - prev_bestv) <= 2*10**6)
            final_best, final_bestv = cur, curv
            prev_best, prev_bestv = cur, curv
            # ③最短胜法: 本层已确认必胜 -> 由浅到深首个即最短, 立即返回不再加深
            if curv>=WIN_TH:
                _DEADLINE=None
                return cur,"这一步能强制取胜（选的是最快赢的路径）！"
            if converged:
                _DEADLINE=None
                break
    _DEADLINE=None
    best = final_best if final_best else cands[0]
    if best is None:
        best=(7,7)
    # 理由(基于新分级: LIVE4=1e6, FOUR=1e5, LIVE3=5e4)
    a=threat(board,best[0],best[1],my_side); d=threat(board,best[0],best[1],op)
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