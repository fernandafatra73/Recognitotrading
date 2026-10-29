"""Widget grafik candlestick (digambar manual) dengan kontrol zoom/geser ala TradingView."""
import math
from datetime import datetime

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from rt_analysis import BULL_LABELS, MA_PERIODS
from rt_sessions import WIB

BG = QColor("#0b0e14")
GRID = QColor(255, 255, 255, 18)
TXT = QColor("#aab2c0")
UP = QColor(35, 206, 140)
DN = QColor(242, 80, 110)
MA_COL = {9: "#e8e8e8", 25: "#d65bff", 99: "#35d6d6", 200: "#ff9f1c", 500: "#3b82f6", 700: "#c8f03a"}
BB_COL = QColor("#9b7cf0")
AXR, AXB = 72, 22


def fmt_price(p):
    if p >= 100:
        return "%.2f" % p
    if p >= 1:
        return "%.3f" % p
    if p >= 0.1:
        return "%.4f" % p
    return "%.6f" % p


def nice_step(rng, target=8):
    raw = max(rng, 1e-12) / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 420)
        self.setMouseTracking(True)
        self.cd = self.ana = self.pv = self.sr = None
        self.title, self.tf = "", "1H"
        self.info = []  # [(teks, warna, tebal)]
        self.bar_w, self.shift, self.pr = 8.0, 0.0, None
        self._drag = None
        self._g = None

    # ---------- data ----------
    def set_data(self, title, tf, cd, ana, pv, info):
        if tf != self.tf or title != self.title:
            self.shift, self.pr = 0.0, None
        self.title, self.tf, self.cd, self.ana, self.pv, self.info = title, tf, cd, ana, pv, info
        self.update()

    def set_info(self, info):
        self.info = info
        self.update()

    # ---------- geometri ----------
    def _geom(self):
        W, H = self.width(), self.height()
        strip = 8 + 17 * len(self.info)
        chart_h = H - strip - AXB
        pw = W - AXR
        vol_h = int(chart_h * 0.2)
        ph = chart_h - vol_h - 4
        return W, H, strip, chart_h, pw, ph, vol_h

    def _range(self, i0, i1):
        if self.pr:
            return self.pr
        lo, hi = float(self.cd.l[i0:i1 + 1].min()), float(self.cd.h[i0:i1 + 1].max())
        pad = (hi - lo) * 0.08 or hi * 0.001
        return lo - pad, hi + pad

    # ---------- gambar ----------
    def paintEvent(self, _):
        p = QPainter(self)
        W, H, strip, chart_h, pw, ph, vol_h = self._geom()
        self._g = (pw, ph, chart_h)
        p.fillRect(0, 0, W, H, BG)
        font = QFont("Segoe UI", 8)
        p.setFont(font)
        if self.cd is None or len(self.cd) < 2:
            p.setPen(TXT)
            p.drawText(20, 30, "Memuat data...")
            return
        cd, a = self.cd, self.ana
        n, bw = len(cd), self.bar_w
        right_idx = n + 4 - self.shift
        i0 = max(0, int(right_idx - pw / bw) - 1)
        i1 = min(n - 1, int(math.ceil(right_idx)))
        if i1 <= i0:
            i0 = max(0, i1 - 1)
        lo, hi = self._range(i0, i1)
        if hi - lo <= 0:
            hi = lo + 1e-9

        def X(i):
            return pw - (right_idx - i - 0.5) * bw

        def Y(v):
            return (hi - v) / (hi - lo) * ph

        # grid + sumbu harga
        step = nice_step(hi - lo)
        p.setPen(TXT)
        v = math.ceil(lo / step) * step
        while v <= hi:
            y = Y(v)
            p.fillRect(QRectF(0, y, pw, 1), GRID)
            p.drawText(QRectF(pw + 6, y - 8, AXR - 6, 16), Qt.AlignmentFlag.AlignVCenter, fmt_price(v))
            v += step

        p.save()
        p.setClipRect(QRectF(0, 0, pw, ph))
        # zona pivot
        if self.pv and a:
            band = a.atr * 0.35
            for k, col in (("R1", "#ff6b81"), ("R2", "#ff6b81"), ("R3", "#ff6b81"),
                           ("S1", "#2fe6a0"), ("S2", "#2fe6a0")):
                lv = self.pv[k]
                c = QColor(col)
                c.setAlpha(30)
                p.fillRect(QRectF(0, Y(lv + band), pw, Y(lv - band) - Y(lv + band)), c)
        # Bollinger
        if a and a.bb:
            up_b, mid, dn_b = a.bb
            idx = [i for i in range(i0, i1 + 1) if not np.isnan(up_b[i])]
            if len(idx) > 1:
                poly = QPolygonF([QPointF(X(i), Y(up_b[i])) for i in idx] +
                                 [QPointF(X(i), Y(dn_b[i])) for i in reversed(idx)])
                f = QColor(BB_COL)
                f.setAlpha(28)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(f))
                p.drawPolygon(poly)
                p.setBrush(Qt.BrushStyle.NoBrush)
                for arr in (up_b, mid, dn_b):
                    self._line(p, arr, i0, i1, X, Y, BB_COL, 1)
        # MA
        if a:
            for per in MA_PERIODS:
                self._line(p, a.ma[per], i0, i1, X, Y, QColor(MA_COL[per]), 1.2)
        # candle
        body_w = max(1.0, bw * 0.7)
        for i in range(i0, i1 + 1):
            col = UP if cd.c[i] >= cd.o[i] else DN
            x = X(i)
            p.setPen(QPen(col, 1))
            p.drawLine(QPointF(x, Y(cd.h[i])), QPointF(x, Y(cd.l[i])))
            yo, yc = Y(cd.o[i]), Y(cd.c[i])
            p.fillRect(QRectF(x - body_w / 2, min(yo, yc), body_w, max(1.0, abs(yo - yc))), col)
        # struktur BOS / CHoCH dan pola candle
        if a:
            p.setFont(QFont("Segoe UI", 7))
            for (i, kind, d, lvl, j) in a.events[-14:]:
                if i < i0 or j > i1:
                    continue
                col = QColor("#35d6b0") if kind == "BOS" else QColor("#ffb020")
                p.setPen(QPen(col, 1, Qt.PenStyle.DotLine))
                y = Y(lvl)
                p.drawLine(QPointF(X(j), y), QPointF(X(i), y))
                p.setPen(col)
                p.drawText(QPointF((X(j) + X(i)) / 2 - 10, y - 3), kind)
            for i, labels in a.patterns.items():
                if i < i0 or i > i1:
                    continue
                for r, lb in enumerate(labels):
                    bull = lb in BULL_LABELS
                    p.setPen(UP if bull else DN)
                    if bull:
                        p.drawText(QPointF(X(i) - 8, Y(cd.l[i]) + 12 + 10 * r), "▲" + lb)
                    else:
                        p.drawText(QPointF(X(i) - 8, Y(cd.h[i]) - 5 - 10 * r), lb + "▼")
            p.setFont(font)
        # level
        labels = []
        if self.pv:
            for k, col, ds in (("R3", "#ff6b81", 0), ("R2", "#ff6b81", 0), ("R1", "#ff6b81", 0),
                               ("P", "#e5c100", 1), ("S1", "#2fe6a0", 0), ("S2", "#2fe6a0", 0)):
                labels.append(("Pivot" if k == "P" else k, self.pv[k], QColor(col), ds))
        if a and a.sl:
            labels.append(("SL", a.sl, QColor("#ff4d6d"), 2))
            labels.append(("TP1 (1:2)", a.tp1, QColor("#2fe6a0"), 1))
        if self.sr and self.tf == "4H":
            q = self.sr
            labels += [("Support BUY", q.sup, QColor("#2fe6a0"), 2), ("Resisten SELL", q.res, QColor("#ff6b81"), 2),
                       ("Cut loss BUY", q.cut_buy, QColor("#ff4d6d"), 0), ("Cut loss SELL", q.cut_sell, QColor("#ff4d6d"), 0),
                       ("Modal habis BUY", q.wipe_buy, QColor("#ff9f1c"), 1), ("Modal habis SELL", q.wipe_sell, QColor("#ff9f1c"), 1)]
        styles = [Qt.PenStyle.DashLine, Qt.PenStyle.DotLine, Qt.PenStyle.SolidLine]
        fm = QFontMetrics(font)
        for name, lv, col, ds in labels:
            if not (lo <= lv <= hi):
                continue
            y = Y(lv)
            p.setPen(QPen(col, 1, styles[ds]))
            p.drawLine(QPointF(0, y), QPointF(pw, y))
            txt = "%s %s" % (name, fmt_price(lv))
            p.setPen(col)
            p.drawText(QPointF(pw - 8 - fm.horizontalAdvance(txt), y - 3), txt)
        p.restore()

        # label harga terakhir
        last = float(cd.c[-1])
        if lo <= last <= hi:
            col = UP if cd.c[-1] >= cd.o[-1] else DN
            y = Y(last)
            p.setPen(QPen(col, 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(0, y), QPointF(pw, y))
            p.fillRect(QRectF(pw, y - 9, AXR, 18), col)
            p.setPen(QColor("#0b0e14"))
            p.drawText(QRectF(pw + 4, y - 9, AXR - 4, 18), Qt.AlignmentFlag.AlignVCenter, fmt_price(last))
        # volume
        vt = ph + 4
        vmax = float(cd.v[i0:i1 + 1].max()) or 1.0
        for i in range(i0, i1 + 1):
            col = QColor(UP if cd.c[i] >= cd.o[i] else DN)
            col.setAlpha(120)
            hh = cd.v[i] / vmax * (vol_h - 14)
            p.fillRect(QRectF(X(i) - body_w / 2, vt + vol_h - hh, body_w, hh), col)
        p.setPen(TXT)
        p.drawText(QPointF(4, vt + 12), "Vol %.2f" % cd.v[-1])
        # sumbu waktu
        ty = ph + 4 + vol_h
        every = max(1, int(math.ceil(95 / bw)))
        p.setPen(TXT)
        for i in range(i0, i1 + 1):
            if i % every:
                continue
            dt = datetime.fromtimestamp(cd.t[i] / 1000, WIB)
            if self.tf == "1D" or (dt.hour == 0 and dt.minute == 0):
                s = dt.strftime("%d %b")
            else:
                s = dt.strftime("%H:%M")
            p.drawText(QRectF(X(i) - 30, ty + 3, 60, 16), Qt.AlignmentFlag.AlignHCenter, s)
        self._header(p)
        # strip info di bawah grafik
        sy = H - 8 - 17 * len(self.info)
        p.fillRect(0, sy - 4, W, H - sy + 4, QColor("#0d121b"))
        for r, (txt, col, bold) in enumerate(self.info):
            f = QFont("Segoe UI", 9)
            f.setBold(bold)
            p.setFont(f)
            p.setPen(QColor(col))
            p.drawText(QRectF(8, sy + 17 * r, W - 16, 17), Qt.AlignmentFlag.AlignVCenter, txt)
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor("#6b7280"))
        p.drawText(QRectF(0, H - 20, W - 10, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Recognito Trading Fernanda")
        p.end()

    def _line(self, p, arr, i0, i1, X, Y, col, w):
        path, on = QPainterPath(), False
        for i in range(i0, i1 + 1):
            v = arr[i]
            if np.isnan(v):
                on = False
                continue
            if on:
                path.lineTo(X(i), Y(v))
            else:
                path.moveTo(X(i), Y(v))
                on = True
        p.setPen(QPen(col, w))
        p.drawPath(path)

    def _header(self, p):
        cd, a = self.cd, self.ana
        f = QFont("Segoe UI", 8)
        fm = QFontMetrics(f)
        i = len(cd) - 1
        chg = (cd.c[i] / cd.o[i] - 1) * 100
        amp = (cd.h[i] - cd.l[i]) / cd.o[i] * 100
        pos = {"x": 8, "y": 14}

        def seg(txt, col, bold=False):
            ff = QFont(f)
            ff.setBold(bold)
            p.setFont(ff)
            p.setPen(QColor(col))
            p.drawText(QPointF(pos["x"], pos["y"]), txt)
            pos["x"] += QFontMetrics(ff).horizontalAdvance(txt)

        seg("%s  %s   " % (self.title, self.tf), "#ffffff", True)
        cc = "#23ce8c" if chg >= 0 else "#f2506e"
        seg("O %s  H %s  L %s  C %s (%+.2f%%)  Amp %.2f%%" % (
            fmt_price(cd.o[i]), fmt_price(cd.h[i]), fmt_price(cd.l[i]), fmt_price(cd.c[i]), chg, amp), cc)
        if a and a.ma:
            pos.update(x=8, y=29)
            for per in MA_PERIODS:
                v = a.ma[per][i]
                if not np.isnan(v):
                    seg("MA(%d): %s   " % (per, fmt_price(v)), MA_COL[per])
            if a.bb is not None and not np.isnan(a.bb[0][i]):
                pos.update(x=8, y=44)
                seg("BOLL(20,2)  UP: %s  MB: %s  DN: %s" % (
                    fmt_price(a.bb[0][i]), fmt_price(a.bb[1][i]), fmt_price(a.bb[2][i])), "#9b7cf0")
        if self.pr:
            p.setFont(f)
            p.setPen(QColor("#ffb020"))
            p.drawText(QRectF(0, 4, self._g[0] - 8, 16),
                       Qt.AlignmentFlag.AlignRight, "Skala manual (klik ganda = otomatis)")

    # ---------- mouse ----------
    def _region(self, pos):
        if self._g is None:
            return "pan"
        pw, ph, chart_h = self._g
        if pos.x() > pw and pos.y() < chart_h:
            return "price"
        if chart_h <= pos.y() <= chart_h + AXB:
            return "time"
        return "pan"

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.cd is not None:
            self._drag = (self._region(e.position()), e.position())

    def mouseReleaseEvent(self, _):
        self._drag = None

    def mouseMoveEvent(self, e):
        pos = e.position()
        reg = self._region(pos)
        self.setCursor(Qt.CursorShape.SizeVerCursor if reg == "price" else
                       Qt.CursorShape.SizeHorCursor if reg == "time" else Qt.CursorShape.ArrowCursor)
        if not self._drag or self.cd is None:
            return
        kind, last = self._drag
        dx, dy = pos.x() - last.x(), pos.y() - last.y()
        self._drag = (kind, pos)
        if kind == "pan":
            self.shift = self._clamp_shift(self.shift + dx / self.bar_w)
            if self.pr:
                lo, hi = self.pr
                d = dy / self._g[1] * (hi - lo)
                self.pr = (lo + d, hi + d)
        elif kind == "price":
            lo, hi = self._cur_range()
            mid, half = (lo + hi) / 2, (hi - lo) / 2 * math.exp(-dy / 200)
            self.pr = (mid - half, mid + half)
        else:
            self.bar_w = min(40.0, max(1.5, self.bar_w * math.exp(dx / 200)))
        self.update()

    def _cur_range(self):
        if self.pr:
            return self.pr
        pw = self._g[0]
        n = len(self.cd)
        right_idx = n + 4 - self.shift
        i0 = max(0, int(right_idx - pw / self.bar_w) - 1)
        i1 = min(n - 1, int(math.ceil(right_idx)))
        return self._range(i0, max(i1, i0 + 1))

    def _clamp_shift(self, s):
        return max(-3.0, min(len(self.cd) - 10.0, s))

    def wheelEvent(self, e):
        if self.cd is None:
            return
        steps = e.angleDelta().y() / 120
        mod = e.modifiers()
        if mod & Qt.KeyboardModifier.ShiftModifier:
            self.shift = self._clamp_shift(self.shift + steps * 5)
        elif mod & Qt.KeyboardModifier.ControlModifier:
            lo, hi = self._cur_range()
            mid, half = (lo + hi) / 2, (hi - lo) / 2 * (0.9 ** steps)
            self.pr = (mid - half, mid + half)
        else:
            self.bar_w = min(40.0, max(1.5, self.bar_w * (1.1 ** steps)))
        self.update()

    def mouseDoubleClickEvent(self, _):
        self.pr = None
        self.update()
