#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成软考高级漫画风格 SVG 图解(统一拟人风格)"""
import os

INK = "#2D3748"
BLUE = "#4A90D9"; ORANGE = "#F5A623"; GREEN = "#6DBE45"; RED = "#E8574F"
PURPLE = "#9067C6"; TEAL = "#35BCBF"; GRAY = "#8A94A6"; SKIN = "#FFD9B3"
YELLOW = "#F7C948"; PINK = "#EE7FA0"

FONT = "font-family='PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif'"

def person(x, y, shirt, tag_text=None, tag_fill=INK, scale=1.0, face="happy"):
    """拟人小人,脚底在 y。"""
    s = []
    s.append(f'<ellipse cx="{x}" cy="{y+4}" rx="{30*scale}" ry="{7*scale}" fill="{INK}" opacity="0.12"/>')
    s.append(f'<line x1="{x-10*scale}" y1="{y-8*scale}" x2="{x-12*scale}" y2="{y}" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>')
    s.append(f'<line x1="{x+10*scale}" y1="{y-8*scale}" x2="{x+12*scale}" y2="{y}" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>')
    s.append(f'<rect x="{x-24*scale}" y="{y-58*scale}" width="{48*scale}" height="{52*scale}" rx="{16*scale}" fill="{shirt}" stroke="{INK}" stroke-width="3"/>')
    s.append(f'<line x1="{x-24*scale}" y1="{y-40*scale}" x2="{x-42*scale}" y2="{y-22*scale}" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>')
    s.append(f'<line x1="{x+24*scale}" y1="{y-40*scale}" x2="{x+42*scale}" y2="{y-22*scale}" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>')
    s.append(f'<circle cx="{x-42*scale}" cy="{y-22*scale}" r="{5*scale}" fill="{SKIN}" stroke="{INK}" stroke-width="2.5"/>')
    s.append(f'<circle cx="{x+42*scale}" cy="{y-22*scale}" r="{5*scale}" fill="{SKIN}" stroke="{INK}" stroke-width="2.5"/>')
    hx, hy, hr = x, y-88*scale, 27*scale
    s.append(f'<circle cx="{hx}" cy="{hy}" r="{hr}" fill="{SKIN}" stroke="{INK}" stroke-width="3"/>')
    s.append(f'<path d="M {hx-hr} {hy-6*scale} Q {hx} {hy-hr-14*scale} {hx+hr} {hy-6*scale} L {hx+hr} {hy-14*scale} Q {hx} {hy-hr-2*scale} {hx-hr} {hy-14*scale} Z" fill="{INK}"/>')
    if face == "happy":
        s.append(f'<circle cx="{hx-9*scale}" cy="{hy+2*scale}" r="{3.4*scale}" fill="{INK}"/>')
        s.append(f'<circle cx="{hx+9*scale}" cy="{hy+2*scale}" r="{3.4*scale}" fill="{INK}"/>')
        s.append(f'<path d="M {hx-10*scale} {hy+11*scale} Q {hx} {hy+19*scale} {hx+10*scale} {hy+11*scale}" fill="none" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>')
    else:
        s.append(f'<circle cx="{hx-9*scale}" cy="{hy+2*scale}" r="{3.4*scale}" fill="{INK}"/>')
        s.append(f'<circle cx="{hx+9*scale}" cy="{hy+2*scale}" r="{3.4*scale}" fill="{INK}"/>')
        s.append(f'<line x1="{hx-9*scale}" y1="{hy+14*scale}" x2="{hx+9*scale}" y2="{hy+14*scale}" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>')
    if tag_text:
        w = len(tag_text) * 22 + 30
        s.append(tag(x, y + 16, tag_text, tag_fill, w))
    return "".join(s)

def tag(x, y, text, fill, w=None, font_size=21, color="#FFFFFF"):
    if w is None:
        w = len(text) * (font_size + 2) + 28
    h = font_size + 18
    return (f'<g><rect x="{x-w/2}" y="{y}" width="{w}" height="{h}" rx="{h/2}" fill="{fill}" stroke="{INK}" stroke-width="2.5"/>'
            f'<text x="{x}" y="{y+h/2+font_size*0.36}" text-anchor="middle" font-size="{font_size}" fill="{color}" {FONT}>{text}</text></g>')

def title(x, y, text, size=34, color=INK):
    return f'<text x="{x}" y="{y}" text-anchor="middle" font-size="{size}" font-weight="bold" fill="{color}" {FONT}>{text}</text>'

def label(x, y, text, size=19, color=INK, anchor="middle"):
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{color}" {FONT}>{text}</text>'

def arrow(x1, y1, x2, y2, color=GRAY, w=5):
    import math
    ang = math.atan2(y2-y1, x2-x1)
    ah = 14
    p1 = (x2 - ah*math.cos(ang - 0.42), y2 - ah*math.sin(ang - 0.42))
    p2 = (x2 - ah*math.cos(ang + 0.42), y2 - ah*math.sin(ang + 0.42))
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{w}" stroke-linecap="round"/>'
            f'<polygon points="{x2},{y2} {p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}" fill="{color}"/>')

def svg(name, body, w=1200, h=800):
    content = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
               f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>'
               f'<rect x="16" y="16" width="{w-32}" height="{h-32}" rx="24" fill="none" stroke="{INK}" stroke-width="3" opacity="0.15"/>'
               + body + '</svg>')
    path = os.path.join(os.path.dirname(__file__), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK", path, len(content), "bytes")

def head(x, y, r, fill, stroke=INK):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'

# ============ A1 五大架构风格 ============
b = [title(600, 64, "五大架构风格家族(拟人版)")]
cx = [150, 375, 600, 825, 1050]
cols = [BLUE, TEAL, ORANGE, PURPLE, GREEN]
names = ["管道-过滤器", "分层", "事件驱动", "虚拟机/解释器", "仓库/黑板"]
descs = ["数据像水流过管道", "一层层向上汇报", "广播一声全城响应", "现场翻译逐步执行", "都来中央图书馆查"]
# 管道
b.append(f'<rect x="{cx[0]-70}" y="150" width="140" height="34" rx="17" fill="{cols[0]}" stroke="{INK}" stroke-width="3"/>')
b.append(f'<rect x="{cx[0]-70}" y="216" width="140" height="34" rx="17" fill="{cols[0]}" stroke="{INK}" stroke-width="3" opacity="0.55"/>')
for gx in (cx[0]-40, cx[0]+10):
    b.append(f'<circle cx="{gx}" cy="167" r="9" fill="#FFFFFF" stroke="{INK}" stroke-width="2.5"/>')
    b.append(f'<circle cx="{gx}" cy="233" r="9" fill="#FFFFFF" stroke="{INK}" stroke-width="2.5"/>')
# 分层楼
for i, c in enumerate([GREEN, ORANGE, BLUE]):
    b.append(f'<rect x="{cx[1]-62}" y="{216-i*62}" width="124" height="52" rx="10" fill="{c}" stroke="{INK}" stroke-width="3"/>')
# 电波
for i, r in enumerate([26, 44, 62]):
    b.append(f'<path d="M {cx[2]} {190-r} a {r} {r} 0 0 1 {r} {r}" fill="none" stroke="{cols[2]}" stroke-width="5" stroke-linecap="round"/>')
    b.append(f'<path d="M {cx[2]} {190-r} a {r} {r} 0 0 0 -{r} {r}" fill="none" stroke="{cols[2]}" stroke-width="5" stroke-linecap="round"/>')
b.append(head(cx[2], 196, 16, cols[2]))
# 翻译官耳机
b.append(f'<path d="M {cx[3]-34} 226 q 0 -52 34 -52 q 34 0 34 52" fill="none" stroke="{INK}" stroke-width="6"/>')
b.append(f'<rect x="{cx[3]-44}" y="218" width="20" height="30" rx="9" fill="{cols[3]}" stroke="{INK}" stroke-width="3"/>')
b.append(f'<rect x="{cx[3]+24}" y="218" width="20" height="30" rx="9" fill="{cols[3]}" stroke="{INK}" stroke-width="3"/>')
# 书架
b.append(f'<rect x="{cx[4]-66}" y="150" width="132" height="100" rx="10" fill="#F3E2C0" stroke="{INK}" stroke-width="3"/>')
for r in range(2):
    b.append(f'<line x1="{cx[4]-66}" y1="{200+r*50}" x2="{cx[4]+66}" y2="{200+r*50}" stroke="{INK}" stroke-width="3"/>')
    for i, c in enumerate([RED, BLUE, GREEN, PURPLE]):
        b.append(f'<rect x="{cx[4]-52+i*28}" y="{164+r*50}" width="18" height="36" rx="4" fill="{c}" stroke="{INK}" stroke-width="2"/>')
for i in range(5):
    b.append(person(cx[i], 400, cols[i]))
    b.append(label(cx[i], 500, descs[i], 18, GRAY))
    b.append(tag(cx[i], 520, names[i], cols[i]))
b.append(label(600, 640, "口诀:管道流水、分层上楼、事件广播、虚拟机翻译、仓库查书", 22, INK))
svg("01-系统架构设计师/架构-图解/A1-五大架构风格拟人图.svg", "".join(b))

# ============ A2 质量属性六战士 ============
b = [title(600, 60, "质量属性六战士(场景信号词见括号)")]
props = [("性能", "3秒内响应", BLUE, "秒表"), ("可用性", "7×24不宕机", GREEN, "盾牌"),
         ("安全性", "加密+权限", RED, "头盔"), ("可修改性", "随时换零件", PURPLE, "扳手"),
         ("可测试性", "一测就明白", TEAL, "放大镜"), ("易用性", "小白也会用", ORANGE, "笑脸")]
for i, (nm, hint, c, prop) in enumerate(props):
    px = 240 + (i % 3) * 370
    py = 210 + (i // 3) * 300
    b.append(f'<rect x="{px-160}" y="{py-96}" width="320" height="252" rx="20" fill="#FFFFFF" stroke="{c}" stroke-width="4"/>')
    b.append(f'<rect x="{px-160}" y="{py-96}" width="320" height="56" rx="20" fill="{c}"/>')
    b.append(f'<rect x="{px-160}" y="{py-68}" width="320" height="28" fill="{c}"/>')
    b.append(f'<text x="{px}" y="{py-58}" text-anchor="middle" font-size="28" font-weight="bold" fill="#FFFFFF" {FONT}>{nm}</text>')
    # 道具
    if prop == "秒表":
        b.append(f'<circle cx="{px}" cy="{py+4}" r="34" fill="#FFFFFF" stroke="{INK}" stroke-width="4"/><line x1="{px}" y1="{py+4}" x2="{px+14}" y2="{py-10}" stroke="{INK}" stroke-width="4" stroke-linecap="round"/><line x1="{px}" y1="{py-30}" x2="{px}" y2="{py-22}" stroke="{INK}" stroke-width="4"/>')
    elif prop == "盾牌":
        b.append(f'<path d="M {px} {py-34} L {px+30} {py-22} L {px+26} {py+14} Q {px} {py+40} {px-26} {py+14} L {px-30} {py-22} Z" fill="{GREEN}" stroke="{INK}" stroke-width="3.5"/><path d="M {px-12} {py+2} l 9 10 l 17 -20" fill="none" stroke="#FFFFFF" stroke-width="5" stroke-linecap="round"/>')
    elif prop == "头盔":
        b.append(f'<path d="M {px-32} {py+14} a 32 32 0 0 1 64 0 Z" fill="{RED}" stroke="{INK}" stroke-width="3.5"/><rect x="{px-32}" y="{py+8}" width="64" height="10" rx="5" fill="{INK}"/>')
    elif prop == "扳手":
        b.append(f'<rect x="{px-6}" y="{py-26}" width="12" height="52" rx="6" fill="{GRAY}" stroke="{INK}" stroke-width="3" transform="rotate(35 {px} {py})"/><circle cx="{px-20}" cy="{py-20}" r="14" fill="none" stroke="{INK}" stroke-width="4" transform="rotate(35 {px} {py})"/>')
    elif prop == "放大镜":
        b.append(f'<circle cx="{px-6}" cy="{py-2}" r="24" fill="#DFF3FF" stroke="{INK}" stroke-width="4"/><line x1="{px+12}" y1="{py+16}" x2="{px+30}" y2="{py+34}" stroke="{INK}" stroke-width="6" stroke-linecap="round"/>')
    else:
        b.append(f'<circle cx="{px}" cy="{py+2}" r="30" fill="{YELLOW}" stroke="{INK}" stroke-width="3.5"/><circle cx="{px-10}" cy="{py-4}" r="4" fill="{INK}"/><circle cx="{px+10}" cy="{py-4}" r="4" fill="{INK}"/><path d="M {px-11} {py+10} q 11 10 22 0" fill="none" stroke="{INK}" stroke-width="3.5" stroke-linecap="round"/>')
    b.append(label(px, py + 118, hint, 18, GRAY))
svg("01-系统架构设计师/架构-图解/A2-质量属性六战士.svg", "".join(b))

# ============ A3 PV 操作生产者消费者 ============
b = [title(600, 64, "生产者-消费者问题(P/V 操作)")]
# 信号灯
b.append(f'<rect x="540" y="100" width="60" height="120" rx="14" fill="{INK}"/>')
for i, c in enumerate([RED, YELLOW, GREEN]):
    b.append(f'<circle cx="570" cy="{134+i*38}" r="13" fill="{c if i==2 else "#5A6572"}" stroke="#111" stroke-width="2"/>')
b.append(f'<line x1="570" y1="220" x2="570" y2="250" stroke="{INK}" stroke-width="6"/>')
b.append(tag(700, 120, "信号量 S(计数还能放几个)", INK))
# 货架
b.append(f'<rect x="460" y="300" width="280" height="230" rx="14" fill="#F3E2C0" stroke="{INK}" stroke-width="4"/>')
b.append(f'<line x1="460" y1="385" x2="740" y2="385" stroke="{INK}" stroke-width="4"/>')
b.append(f'<line x1="460" y1="455" x2="740" y2="455" stroke="{INK}" stroke-width="4"/>')
for r in range(2):
    for cxx in (505, 590, 675):
        b.append(f'<rect x="{cxx}" y="{322+r*70}" width="52" height="40" rx="6" fill="{ORANGE}" stroke="{INK}" stroke-width="2.5"/>')
b.append(tag(600, 560, "缓冲区(仓库)", INK))
# 左生产者
b.append(person(200, 470, BLUE))
b.append(tag(200, 486, "生产者", BLUE))
b.append(f'<rect x="300" y="418" width="56" height="44" rx="6" fill="{ORANGE}" stroke="{INK}" stroke-width="3"/>')
b.append(arrow(270, 380, 450, 360, GREEN))
b.append(label(360, 340, "P 操作:放一个,S-1", 20, GREEN))
# 右消费者
b.append(person(1000, 470, ORANGE))
b.append(tag(1000, 486, "消费者", ORANGE))
b.append(arrow(750, 360, 930, 380, RED))
b.append(label(840, 340, "V 操作:取一个,S+1", 20, RED))
b.append(f'<rect x="860" y="418" width="56" height="44" rx="6" fill="{ORANGE}" stroke="{INK}" stroke-width="3"/>')
b.append(label(600, 690, "仓库满 S=0:生产者睡觉等 V|仓库空 S=0:消费者睡觉等 P".replace("|", "  ;  "), 22, INK))
svg("01-系统架构设计师/架构-图解/A3-PV操作生产者消费者.svg", "".join(b))

# ============ A4 缓存三兄弟 ============
b = [title(600, 60, "缓存三大事故(穿透·击穿·雪崩)与对策")]
panels = [
    (210, "穿透", "查的数据根本不存在", "对策:布隆过滤器拦截", BLUE),
    (600, "击穿", "热点 key 到期瞬间被挤爆", "对策:互斥锁重建", ORANGE),
    (990, "雪崩", "一大批 key 同时过期", "对策:过期时间加随机打散", RED),
]
for px, nm, hint, fix, c in panels:
    b.append(f'<rect x="{px-180}" y="110" width="360" height="420" rx="20" fill="#F8FAFD" stroke="{c}" stroke-width="4"/>')
    b.append(tag(px, 130, nm, c))
if True:
    # 穿透:小人穿墙
    b.append(f'<rect x="80" y="240" width="70" height="200" rx="10" fill="{GRAY}" stroke="{INK}" stroke-width="3"/>')
    b.append(person(215, 400, YELLOW, face="happy"))
    b.append(arrow(230, 340, 290, 340, RED))
    b.append(label(210, 470, "小偷直奔数据库", 18, GRAY))
    # 击穿:锤砸宝箱
    hx = 600
    b.append(f'<line x1="{hx-10}" y1="220" x2="{hx+6}" y2="290" stroke="{INK}" stroke-width="8" stroke-linecap="round"/>')
    b.append(f'<rect x="{hx-14}" y="290" width="52" height="34" rx="6" fill="{GRAY}" stroke="{INK}" stroke-width="3" transform="rotate(18 {hx+10} 300)"/>')
    b.append(f'<rect x="{hx-70}" y="330" width="140" height="86" rx="10" fill="{YELLOW}" stroke="{INK}" stroke-width="3.5"/>')
    b.append(f'<path d="M {hx-70} 330 L {hx} 300 L {hx+70} 330 Z" fill="{ORANGE}" stroke="{INK}" stroke-width="3.5"/>')
    for sx, sy in [(hx-58, 300), (hx+56, 296), (hx+2, 272)]:
        b.append(f'<path d="M {sx} {sy} l 6 10 l 10 2 l -8 8 l 2 11 l -10 -5 l -10 5 l 2 -11 l -8 -8 l 10 -2 Z" fill="{RED}"/>')
    # 雪崩:雪山压服务器
    ax = 990
    b.append(f'<polygon points="{ax-150},330 {ax-60},190 {ax+20},330" fill="#DDEBF7" stroke="{INK}" stroke-width="3"/>')
    b.append(f'<polygon points="{ax-40},330 {ax+40},220 {ax+120},330" fill="#C6DCF0" stroke="{INK}" stroke-width="3"/>')
    for r in range(3):
        b.append(f'<rect x="{ax-70}" y="{352+r*44}" width="140" height="34" rx="6" fill="{GRAY}" stroke="{INK}" stroke-width="3"/>')
        for dx in (-40, 0, 40):
            b.append(f'<circle cx="{ax+dx}" cy="{369+r*44}" r="5" fill="{GREEN}"/>')
for px, nm, hint, fix, c in panels:
    b.append(label(px, 490, hint, 19, INK))
    b.append(tag(px, 560, fix, c))
b.append(label(600, 700, "记忆:穿透是查无此人,击穿是打一个,雪崩是塌一片", 22, INK))
svg("01-系统架构设计师/架构-图解/A4-缓存三兄弟.svg", "".join(b))

# ============ A5 CAP 三选二 ============
b = [title(600, 64, "CAP 定理:三选二(分布式必选 P)")]
bx, by = 600, 430
for i, (nm, c, d) in enumerate([("C 一致性", BLUE, " everyone 看到一样的数据".replace(" everyone ", "人人")),
                                ("A 可用性", GREEN, "永远能响应(可能旧数据)"),
                                ("P 分区容忍", RED, "网络断了也得活着")]):
    ang = -90 + i * 120
    import math
    hx = bx + 260 * math.cos(math.radians(ang)); hy = by + 200 * math.sin(math.radians(ang))
    b.append(f'<line x1="{bx}" y1="{by}" x2="{hx:.0f}" y2="{hy:.0f}" stroke="{GRAY}" stroke-width="4" stroke-dasharray="8 8"/>')
    b.append(head(hx, hy-26, 40, c))
    b.append(f'<rect x="{hx-56}" y="{hy+18}" width="112" height="66" rx="12" fill="{c}" stroke="{INK}" stroke-width="3"/>')
    b.append(f'<text x="{hx}" y="{hy+46}" text-anchor="middle" font-size="22" font-weight="bold" fill="#FFF" {FONT}>{nm}</text>')
    b.append(label(hx, hy+128, d, 17, GRAY))
b.append(f'<circle cx="{bx}" cy="{by-40}" r="46" fill="{YELLOW}" stroke="{INK}" stroke-width="3.5"/>')
b.append(f'<text x="{bx}" y="{by-32}" text-anchor="middle" font-size="24" font-weight="bold" fill="{INK}" {FONT}>三选二</text>')
b.append(person(bx, 640, PURPLE))
b.append(bubble := f'<g><rect x="{bx+60}" y="560" width="240" height="56" rx="16" fill="#FFF" stroke="{INK}" stroke-width="3"/><polygon points="{bx+70},616 {bx+90},636 {bx+96},610" fill="#FFF" stroke="{INK}" stroke-width="3"/><text x="{bx+180}" y="595" text-anchor="middle" font-size="20" fill="{INK}" {FONT}>分布式系统,P 必选!</text></g>')
b.append(label(600, 730, "CP:保一致牺牲可用(如 ZooKeeper) | AP:保可用容忍旧数据(如 Eureka)", 21, INK))
svg("01-系统架构设计师/架构-图解/A5-CAP三选二.svg", "".join(b))

# ============ P1 挣值三兄弟 ============
b = [title(600, 64, "挣值三兄弟:PV · EV · AC")]
import math
pts = " ".join(f"{x},{560 - 320/(1+math.exp(-(x-620)/150)):.0f}" for x in range(120, 1090, 20))
b.append(f'<polyline points="{pts}" fill="none" stroke="{GRAY}" stroke-width="4" stroke-dasharray="10 8"/>')
b.append(label(170, 200, "S 曲线:花钱如流水", 18, GRAY))
b.append(person(240, 560, BLUE)); b.append(tag(240, 576, "PV 计划值", BLUE))
b.append(label(240, 660, "计划该干多少活", 19, INK))
b.append(f'<rect x="480" y="340" width="60" height="80" rx="8" fill="{YELLOW}" stroke="{INK}" stroke-width="3.5"/><text x="510" y="392" text-anchor="middle" font-size="34" {FONT}>🏆</text>')
b.append(person(510, 560, GREEN)); b.append(tag(510, 576, "EV 挣值", GREEN))
b.append(label(510, 660, "干完的活值多少钱", 19, INK))
b.append(f'<rect x="770" y="352" width="66" height="62" rx="8" fill="#FFF" stroke="{INK}" stroke-width="3"/><line x1="778" y1="370" x2="828" y2="370" stroke="{RED}" stroke-width="3"/><line x1="778" y1="386" x2="828" y2="386" stroke="{RED}" stroke-width="3"/><line x1="778" y1="402" x2="828" y2="402" stroke="{RED}" stroke-width="3"/>')
b.append(person(820, 560, RED)); b.append(tag(820, 576, "AC 实际成本", RED))
b.append(label(820, 660, "实际花了多少钱", 19, INK))
b.append(f'<rect x="150" y="688" width="900" height="70" rx="16" fill="#F8FAFD" stroke="{INK}" stroke-width="3"/>')
b.append(label(600, 718, "CV=EV-AC(负=超支)   SV=EV-PV(负=落后)   CPI=EV/AC   SPI=EV/PV(小于1都是坏消息)", 21, INK))
b.append(label(600, 746, "EV 永远站 C 位:偏差都拿它打头,指数都拿它当分子", 19, GRAY))
svg("02-信息系统项目管理师/项管-图解/P1-挣值三兄弟.svg", "".join(b))

# ============ P2 变更八步关卡 ============
b = [title(600, 60, "变更控制八步流程(先审批·后实施)")]
steps = [("1 提出申请", BLUE, "书面提交"), ("2 记录", TEAL, "登记在册"), ("3 评估影响", ORANGE, "动哪些基准"),
         ("4 CCB 审批", RED, "盖章才算数"), ("5 更新基准", PURPLE, "计划先改对"), ("6 实施", GREEN, "按新基准干"),
         ("7 验证", TEAL, "确认改好了"), ("8 归档", GRAY, "全程留痕")]
for i, (nm, c, hint) in enumerate(steps):
    px = 230 + (i % 4) * 250
    py = 220 + (i // 4) * 300
    big = (i == 3)
    r = 74 if big else 58
    b.append(f'<circle cx="{px}" cy="{py}" r="{r}" fill="{c}" stroke="{INK}" stroke-width="4"/>')
    b.append(f'<text x="{px}" y="{py+9}" text-anchor="middle" font-size="{34 if big else 26}" font-weight="bold" fill="#FFF" {FONT}>{nm.split(" ")[0]}</text>')
    b.append(tag(px, py + r + 12, nm.split(" ", 1)[1], c, font_size=22))
    b.append(label(px, py + r + 74, hint, 18, GRAY))
    if i % 4 != 3:
        b.append(arrow(px + r + 8, py, px + 250 - r - 8, py, GRAY, 4))
for r0 in (0, 1):
    pass
b.append(arrow(980 - 58 - 8, 220, 1080, 220, GRAY, 0)) if False else None
# 蛇形连接第二行
b.append(arrow(980, 296, 980, 350, GRAY, 4))
b.append(arrow(980, 350, 220, 350, GRAY, 4))
b.append(arrow(220, 350, 220, 418 - 58, GRAY, 4))
b.append(label(600, 745, "口诀:申请→记录→评估→CCB→更新→实施→验证→归档 | 顺序错了就是案例找错题", 21, INK))
svg("02-信息系统项目管理师/项管-图解/P2-变更审批八步.svg", "".join(b))

# ============ P3 干系人四象限 ============
b = [title(600, 56, "干系人权力-利益方格")]
ox, oy = 600, 430
b.append(f'<line x1="180" y1="{oy}" x2="1020" y2="{oy}" stroke="{INK}" stroke-width="4"/>')
b.append(f'<line x1="{ox}" y1="150" x2="{ox}" y2="700" stroke="{INK}" stroke-width="4"/>')
b.append(label(1015, 458, "利益 →", 22, INK, "end"))
b.append(label(616, 170, "权力 ↑", 22, INK, "start"))
quads = [(390, 300, "高权力·低利益", "令其满意", TEAL, "定期汇报别惊扰"),
         (810, 300, "高权力·高利益", "重点管理", RED, "开会拉通+重点服务"),
         (390, 590, "低权力·低利益", "监督", GRAY, "盯一眼就行"),
         (810, 590, "低权力·高利益", "随时告知", GREEN, "多同步别让人失落")]
for qx, qy, pos, strat, c, hint in quads:
    b.append(f'<rect x="{qx-150}" y="{qy-110}" width="300" height="220" rx="18" fill="#F8FAFD" stroke="{c}" stroke-width="3.5"/>')
    b.append(label(qx, qy - 80, pos, 18, GRAY))
    b.append(person(qx, qy + 40, c, scale=0.9))
    b.append(tag(qx, qy + 58, strat, c, font_size=22))
    b.append(label(qx, qy + 130, hint, 17, GRAY))
b.append(label(600, 760, "易混:高权力低利益要『满意』(别折腾他),低权力高利益要『告知』(别冷落他)", 21, INK))
svg("02-信息系统项目管理师/项管-图解/P3-干系人权力利益方格.svg", "".join(b))

# ============ P4 风险应对七招 ============
b = [title(600, 56, "风险应对七连招(威胁五招+机会四招,上报通用)")]
# 威胁侧
b.append(f'<rect x="40" y="100" width="560" height="520" rx="20" fill="#FDF1F0" stroke="{RED}" stroke-width="4"/>')
b.append(tag(320, 118, "威胁(坏事要来)", RED))
b.append(head(320, 250, 44, "#8A94A6"))
for i in range(5):
    b.append(f'<path d="M {288+i*16} 262 q 8 -10 16 0" fill="none" stroke="{INK}" stroke-width="2.5"/>')
b.append(label(320, 320, "乌云怪来了,怎么办?", 19, INK))
th = [("规避", "绕着走,改计划让它发生不了", BLUE), ("转移", "买保险/外包,把后果递给别人", TEAL),
      ("减轻", "举盾,降概率降影响", GREEN), ("接受", "躺平:主动留应急储备,被动硬扛", GRAY)]
for i, (nm, hint, c) in enumerate(th):
    px = 150 + (i % 2) * 240; py = 400 + (i // 2) * 110
    b.append(f'<circle cx="{px}" cy="{py}" r="40" fill="{c}" stroke="{INK}" stroke-width="3.5"/>')
    b.append(f'<text x="{px}" y="{py+9}" text-anchor="middle" font-size="22" font-weight="bold" fill="#FFF" {FONT}>{nm}</text>')
    b.append(label(px, py + 64, hint, 15.5, INK))
b.append(label(320, 596, "※ 上报:超出项目权限,交给上级组织", 18, ORANGE))
# 机会侧
b.append(f'<rect x="600" y="100" width="560" height="520" rx="20" fill="#F0F9F1" stroke="{GREEN}" stroke-width="4"/>')
b.append(tag(880, 118, "机会(好事也可能来)", GREEN))
b.append(head(880, 250, 44, YELLOW))
b.append(label(880, 320, "金元宝掉下来,接不接?", 19, INK))
op = [("开拓", "主动创造条件,确保它发生", BLUE), ("分享", "找伙伴合伙,一起把蛋糕做大", TEAL),
      ("提高", "浇灌施肥,放大概率和收益", GREEN)]
for i, (nm, hint, c) in enumerate(op):
    px = 760 + (i % 2) * 240; py = 400 + (i // 2) * 110
    b.append(f'<circle cx="{px}" cy="{py}" r="40" fill="{c}" stroke="{INK}" stroke-width="3.5"/>')
    b.append(f'<text x="{px}" y="{py+9}" text-anchor="middle" font-size="22" font-weight="bold" fill="#FFF" {FONT}>{nm}</text>')
    b.append(label(px, py + 64, hint, 15.5, INK))
b.append(label(940, 596, "※ 机会也可以『接受』:不主动追,来了不拒", 18, ORANGE))
b.append(label(600, 690, "口诀:威胁-避转减受,机会-开分提受,搞不定就上报", 22, INK))
svg("02-信息系统项目管理师/项管-图解/P4-风险应对七招.svg", "".join(b))

# ============ P5 配置三库 ============
b = [title(600, 60, "配置管理三库(草稿间→档案室→展柜)")]
rooms = [(220, "开发库(动态库)", BLUE, "开发人员随便读写", "0.YZ 草稿态", "乱贴便签的草稿间"),
         (600, "受控库(主库)", ORANGE, "变更受控,CCB 把门", "X.Y 正式态", "有门禁的档案室"),
         (980, "产品库(静态库)", GREEN, "只进不出,对外发布", "X.YZ 修改态", "玻璃展柜放成品")]
for rx, nm, c, perm, ver, hint in rooms:
    b.append(f'<rect x="{rx-160}" y="140" width="320" height="400" rx="18" fill="#F8FAFD" stroke="{c}" stroke-width="4"/>')
    b.append(f'<rect x="{rx-160}" y="140" width="320" height="58" rx="18" fill="{c}"/><rect x="{rx-160}" y="172" width="320" height="26" fill="{c}"/>')
    b.append(f'<text x="{rx}" y="177" text-anchor="middle" font-size="25" font-weight="bold" fill="#FFF" {FONT}>{nm}</text>')
if True:
    # 开发库:便签墙
    for i, (dx, dy, rot) in enumerate([(-100, 240, -6), (-30, 260, 4), (40, 236, -3), (-70, 330, 5), (10, 344, -5)]):
        b.append(f'<rect x="{220+dx}" y="{dy}" width="60" height="52" rx="6" fill="{YELLOW}" stroke="{INK}" stroke-width="2" transform="rotate({rot} {220+dx+30} {dy+26})"/>')
    # 受控库:门禁+守卫
    b.append(f'<rect x="540" y="250" width="90" height="180" rx="10" fill="#B08968" stroke="{INK}" stroke-width="3.5"/>')
    b.append(f'<circle cx="612" cy="345" r="8" fill="{YELLOW}" stroke="{INK}" stroke-width="2.5"/>')
    b.append(person(700, 420, ORANGE, scale=0.9))
    # 产品库:展柜奖杯
    b.append(f'<rect x="860" y="260" width="240" height="170" rx="12" fill="#EAF7FF" stroke="{INK}" stroke-width="3"/>')
    b.append(f'<rect x="960" y="300" width="40" height="70" rx="8" fill="{YELLOW}" stroke="{INK}" stroke-width="3"/>')
    b.append(f'<path d="M 960 312 q -34 4 -30 -22 q 18 2 30 22 Z M 1000 312 q 34 4 30 -22 q -18 2 -30 22 Z" fill="{YELLOW}" stroke="{INK}" stroke-width="3"/>')
    b.append(f'<rect x="946" y="382" width="68" height="14" rx="6" fill="#B08968" stroke="{INK}" stroke-width="2.5"/>')
for rx, nm, c, perm, ver, hint in rooms:
    b.append(label(rx, 470, hint, 18, GRAY))
    b.append(tag(rx, 560, perm, c))
    b.append(tag(rx, 620, ver, INK))
b.append(label(600, 720, "流程:开发库乱改没人管 → 进受控库要审批 → 进产品库=已发布 | 案例找错高频:跳过受控库直接进产品库", 20, INK))
svg("02-信息系统项目管理师/项管-图解/P5-配置三库.svg", "".join(b))

# ============ P6 赶工 vs 快速跟进 ============
b = [title(600, 60, "进度压缩两招:赶工 vs 快速跟进")]
b.append(f'<rect x="40" y="110" width="560" height="520" rx="20" fill="#F0F6FF" stroke="{BLUE}" stroke-width="4"/>')
b.append(tag(320, 128, "赶工 Crashing", BLUE))
for i, (y, w, c) in enumerate([(240, 300, BLUE), (310, 240, TEAL), (380, 200, GREEN)]):
    b.append(f'<rect x="120" y="{y}" width="{w}" height="40" rx="10" fill="{c}" stroke="{INK}" stroke-width="3"/>')
b.append(person(480, 300, RED, scale=0.85)); b.append(person(500, 390, ORANGE, scale=0.85))
b.append(label(320, 490, "加人加班加点:工期↓ 成本↑", 20, INK))
b.append(tag(320, 530, "适用:关键路径上成本最低的活动", BLUE, font_size=18))
b.append(f'<rect x="600" y="110" width="560" height="520" rx="20" fill="#FFF7EE" stroke="{ORANGE}" stroke-width="4"/>')
b.append(tag(880, 128, "快速跟进 Fast Tracking", ORANGE))
b.append(f'<rect x="680" y="240" width="300" height="40" rx="10" fill="{BLUE}" stroke="{INK}" stroke-width="3"/>')
b.append(f'<rect x="780" y="300" width="300" height="40" rx="10" fill="{GREEN}" stroke="{INK}" stroke-width="3"/>')
b.append(f'<rect x="680" y="240" width="400" height="100" rx="10" fill="none" stroke="{RED}" stroke-width="3" stroke-dasharray="9 7"/>')
b.append(label(880, 216, "原本串行的任务,提前并行搭着干", 18, GRAY))
b.append(label(880, 380, "重叠区=返工风险区", 20, RED))
b.append(label(880, 490, "工期↓(不加钱) 风险↑", 20, INK))
b.append(tag(880, 530, "适用:任务间逻辑依赖可松动时", ORANGE, font_size=18))
b.append(label(600, 710, "案例答法:先压关键路径上『赶工成本最低』的活;多关键路径要同时压,否则白压", 21, INK))
svg("02-信息系统项目管理师/项管-图解/P6-赶工vs快速跟进.svg", "".join(b))

print("ALL DONE")
