"""Indikator, pola candle, struktur BOS/CHoCH, sinyal, dan skor breakout/breakdown."""
from dataclasses import dataclass, field

import numpy as np

MA_PERIODS = (9, 25, 99, 200, 500, 700)
BULL_LABELS = ("BuE", "MS", "BWS")
SWING_LEN = 3


def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def rsi(c, n=14):
    out = np.full(len(c), np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    up, dn = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    au, ad = up[:n].mean(), dn[:n].mean()
    for i in range(n, len(c)):
        if i > n:
            au = (au * (n - 1) + up[i - 1]) / n
            ad = (ad * (n - 1) + dn[i - 1]) / n
        out[i] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def atr(h, l, c, n=14):
    if len(c) < 2:
        return float(h[-1] - l[-1]) if len(c) else 0.0
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean())


def boll(c, n=20, k=2.0):
    mid = sma(c, n)
    sd = np.full(len(c), np.nan)
    for i in range(n - 1, len(c)):
        sd[i] = c[i - n + 1:i + 1].std()
    return mid + k * sd, mid, mid - k * sd


def find_patterns(o, h, l, c, end):
    """Pola candle pada candle tertutup [0, end). Hasil: {indeks: [label]}."""
    m = {}

    def add(i, lb):
        m.setdefault(i, []).append(lb)

    body = np.abs(c - o)
    for i in range(2, end):
        bull, bear = c > o, c < o
        if bear[i - 1] and bull[i] and o[i] <= c[i - 1] and c[i] >= o[i - 1] and body[i] > body[i - 1]:
            add(i, "BuE")
        if bull[i - 1] and bear[i] and o[i] >= c[i - 1] and c[i] <= o[i - 1] and body[i] > body[i - 1]:
            add(i, "BeE")
        if bear[i - 2] and body[i - 1] < 0.3 * body[i - 2] and bull[i] and c[i] > (o[i - 2] + c[i - 2]) / 2 \
                and body[i - 2] > 0:
            add(i, "MS")
        if bull[i - 2] and body[i - 1] < 0.3 * body[i - 2] and bear[i] and c[i] < (o[i - 2] + c[i - 2]) / 2 \
                and body[i - 2] > 0:
            add(i, "ES")
        if all(bear[i - k] for k in (0, 1, 2)) and c[i] < c[i - 1] < c[i - 2] \
                and c[i - 2] < o[i - 1] <= o[i - 2] and c[i - 1] < o[i] <= o[i - 1]:
            add(i, "BBC")  # Three Black Crows
        if all(bull[i - k] for k in (0, 1, 2)) and c[i] > c[i - 1] > c[i - 2] \
                and o[i - 2] <= o[i - 1] < c[i - 2] and o[i - 1] <= o[i] < c[i - 1]:
            add(i, "BWS")  # Three White Soldiers
    return m


def find_structure(h, l, c, end, L=SWING_LEN):
    """BOS / CHoCH. Hasil: (events, trend). event=(idx, jenis, arah, level, idx_swing)."""
    events, trend = [], 0
    sh = sl = None
    sh_done = sl_done = True
    for i in range(end):
        j = i - L
        if j >= L:
            if h[j] == h[j - L:j + L + 1].max():
                sh, sh_done = (j, h[j]), False
            if l[j] == l[j - L:j + L + 1].min():
                sl, sl_done = (j, l[j]), False
        if sh and not sh_done and c[i] > sh[1]:
            events.append((i, "CHoCH" if trend == -1 else "BOS", 1, sh[1], sh[0]))
            trend, sh_done = 1, True
        if sl and not sl_done and c[i] < sl[1]:
            events.append((i, "CHoCH" if trend == 1 else "BOS", -1, sl[1], sl[0]))
            trend, sl_done = -1, True
    return events, trend


def pivots_from_daily(dh, dl, dc):
    p = (dh + dl + dc) / 3
    return {"P": p, "R1": 2 * p - dl, "S1": 2 * p - dh, "R2": p + (dh - dl),
            "S2": p - (dh - dl), "R3": dh + 2 * (p - dl)}


@dataclass
class Analysis:
    n: int = 0
    ma: dict = field(default_factory=dict)
    bb: tuple = None
    atr: float = 0.0
    rsi: float = 50.0
    patterns: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    trend: int = 0
    score: float = 0.0
    signal: str = "WAIT"
    direction: int = 0
    sl: float = None
    tp1: float = None
    up: float = 0.0      # skor breakout 0-100
    down: float = 0.0    # skor breakdown 0-100
    price: float = 0.0


def analyze(cd):
    a = Analysis(n=len(cd))
    o, h, l, c, v = cd.o, cd.h, cd.l, cd.c, cd.v
    n = len(c)
    if n < 30:
        return a
    end = n - 1  # candle terakhir masih berjalan
    a.price = float(c[-1])
    a.ma = {p: sma(c, p) for p in MA_PERIODS}
    a.bb = boll(c)
    a.atr = atr(h, l, c)
    a.rsi = float(rsi(c)[-1])
    a.patterns = find_patterns(o, h, l, c, end)
    a.events, a.trend = find_structure(h, l, c, end)

    k = end - 1
    sc = 0.0
    px = c[k]
    for fast, slow in ((None, 25), (25, 99), (99, 200)):
        s = a.ma[slow][k]
        f = px if fast is None else a.ma[fast][k]
        if not (np.isnan(s) or np.isnan(f)):
            sc += 1 if f > s else -1
    sc += a.trend
    if a.events and k - a.events[-1][0] <= 10:
        e = a.events[-1]
        sc += e[2] * (2 if e[1] == "CHoCH" else 1)
    for i in range(max(0, k - 2), k + 1):
        for lb in a.patterns.get(i, []):
            sc += 1 if lb in BULL_LABELS else (-1 if lb in ("BeE", "ES", "BBC") else 0)
    a.score = sc
    a.direction = 1 if sc > 0 else (-1 if sc < 0 else 0)
    name = "BUY" if sc > 0 else "SELL"
    if abs(sc) >= 5:
        a.signal = "STRONG " + name
    elif abs(sc) >= 3:
        a.signal = name
    elif abs(sc) >= 1:
        a.signal = name + " lemah"
    if a.direction:
        a.sl = a.price - a.direction * 1.5 * a.atr
        a.tp1 = a.price + a.direction * 3.0 * a.atr
    a.up, a.down = breakout_scores(cd, a)
    return a


def breakout_scores(cd, a):
    """Skor gabungan 0-100: squeeze BB, kedekatan/penembusan level 50 candle, volume, tren."""
    h, l, c, v = cd.h, cd.l, cd.c, cd.v
    k = len(c) - 2  # candle tertutup terakhir
    if k < 60 or a.atr <= 0:
        return 0.0, 0.0
    up_b, mid, dn_b = a.bb
    bw = (up_b - dn_b) / np.where(mid == 0, np.nan, mid)
    win = bw[max(0, k - 120):k + 1]
    win = win[~np.isnan(win)]
    squeeze = 25 * (1 - float((win < bw[k]).mean())) if len(win) else 0.0
    vol_avg = v[k - 20:k].mean()
    volume = 15 * min(1.0, (v[k] / vol_avg) / 2) if vol_avg > 0 else 0.0
    hi, lo = h[k - 50:k].max(), l[k - 50:k].min()
    res = {}
    for d, lvl in ((1, hi), (-1, lo)):
        if d * (c[k] - lvl) > 0:
            prox = 30.0
        else:
            prox = 30 * max(0.0, 1 - abs(lvl - c[k]) / a.atr / 2)
        t = 0.0
        m25, m99 = a.ma[25][k], a.ma[99][k]
        if not np.isnan(m25):
            t += 5 if d * (c[k] - m25) > 0 else 0
        if not (np.isnan(m25) or np.isnan(m99)):
            t += 5 if d * (m25 - m99) > 0 else 0
        r = rsi(c[max(0, k - 60):k + 1])[-1]
        t += 5 if (d > 0 and r > 55) or (d < 0 and r < 45) else 0
        res[d] = (squeeze + volume + prox + t) / 85 * 100
    return min(100.0, res[1]), min(100.0, res[-1])
