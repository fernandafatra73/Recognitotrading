"""Recognito Trading Fernanda (versi Python) - Created By: Fernanda Fatria Fatra,SST.MM"""
import glob
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
                             QFormLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
                             QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                             QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
                             QVBoxLayout, QWidget)

import rt_analysis as A
import rt_data as D
import rt_sessions as S
import rt_sr as SR
from rt_chart import ChartWidget, fmt_price

APP_NAME = "Recognito Trading Fernanda"
if getattr(sys, "frozen", False):
    BASE = os.path.dirname(sys.executable)
    RES = getattr(sys, "_MEIPASS", BASE)
else:
    BASE = RES = os.path.dirname(os.path.abspath(__file__))
CAPTURE_DIR = os.path.join(BASE, "Capture")
CAPTURE_LOG = os.path.join(CAPTURE_DIR, "capture.txt")
EVENTS_TXT = os.path.join(BASE, "events.txt")
TF_ORDER = ["1m", "5m", "15m", "1H", "4H", "1D"]
SCAN_W = {"15m": 0.2, "1H": 0.3, "4H": 0.3, "1D": 0.2}

STYLE = """
QWidget { background:#0b0e14; color:#d5dae3; font-family:'Segoe UI'; font-size:9pt; }
QTabWidget::pane { border:1px solid #1d2432; }
QTabBar::tab { background:#121826; padding:7px 16px; border:1px solid #1d2432; }
QTabBar::tab:selected { background:#1b2436; color:#ffb020; }
QPushButton { background:#1b2436; border:1px solid #2a3550; padding:5px 12px; border-radius:3px; }
QPushButton:hover { background:#25314b; }
QPushButton:checked { background:#ffb020; color:#0b0e14; font-weight:bold; }
QListWidget, QTableWidget, QTextBrowser, QPlainTextEdit { background:#0d121b; border:1px solid #1d2432; gridline-color:#1d2432; }
QHeaderView::section { background:#121826; border:0; padding:4px; color:#aab2c0; }
QDoubleSpinBox, QComboBox { background:#121826; border:1px solid #2a3550; padding:3px; }
QStatusBar { background:#0d121b; }
"""


# ---------------------------------------------------------------- util async
class _Bus(QObject):
    done = pyqtSignal(object, object)

    def __init__(self):
        super().__init__()
        self.done.connect(self._run)

    @pyqtSlot(object, object)
    def _run(self, cb, res):
        cb(res)


_bus = None
_pool = ThreadPoolExecutor(8)


def run_async(fn, cb, *args):
    def job():
        try:
            res = fn(*args)
        except Exception as e:
            res = e
        _bus.done.emit(cb, res)
    _pool.submit(job)


def beep():
    def go():
        try:
            import winsound
            for f in (880, 1175, 1568):
                winsound.Beep(f, 220)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#ffb020"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    p.setPen(QColor("#0b0e14"))
    f = QFont("Segoe UI", 30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "R")
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- data chart
_pv_cache = {}


def fetch_chart(sym, tf, limit=1000):
    cd = D.fetch_klines(sym, tf, limit)
    a = A.analyze(cd)
    pv = None
    hit = _pv_cache.get(sym)
    if hit and time.time() - hit[0] < 600:
        pv = hit[1]
    else:
        try:
            d = D.fetch_klines(sym, "1D", 5)
            pv = A.pivots_from_daily(d.h[-2], d.l[-2], d.c[-2])
            _pv_cache[sym] = (time.time(), pv)
        except Exception:
            pv = hit[1] if hit else None
    return sym, tf, cd, a, pv


def scan_symbol(sym):
    out = {}
    for tf in SCAN_W:
        cd = D.fetch_klines(sym, tf, 300)
        a = A.analyze(cd)
        out[tf] = dict(signal=a.signal, score=a.score, trend=a.trend, rsi=a.rsi, up=a.up, down=a.down,
                       price=a.price, atr=a.atr, label=cd.label, direction=a.direction)
    return out


def do_scan(symbols):
    res = {}
    with ThreadPoolExecutor(6) as ex:
        futs = {s: ex.submit(scan_symbol, s) for s in symbols}
        for s, f in futs.items():
            try:
                res[s] = f.result()
            except Exception:
                pass
    return res


def coin_scores(per_tf):
    tw = sum(SCAN_W[t] for t in per_tf)
    if not tw:
        return 0.0, 0.0
    return (sum(SCAN_W[t] * d["up"] for t, d in per_tf.items()) / tw,
            sum(SCAN_W[t] * d["down"] for t, d in per_tf.items()) / tw)


def short_name(sym):
    return sym.replace("USDT", "")


def breakout_line(scan, threshold):
    if not scan:
        return "BREAKOUT / BREAKDOWN ≥%d%%: scan pasar sedang berjalan..." % threshold
    ups, downs, best = [], [], []
    for sym, per in scan.items():
        u, d = coin_scores(per)
        if u >= threshold:
            ups.append((u, sym))
        if d >= threshold:
            downs.append((d, sym))
        best.append((max(u, d), "naik" if u >= d else "turun", sym))
    f = lambda L: ", ".join("%s %d%%" % (short_name(s), round(v)) for v, s in sorted(L, reverse=True)) or "-"
    txt = "BREAKOUT ≥%d%%: %s   |   BREAKDOWN ≥%d%%: %s" % (threshold, f(ups), threshold, f(downs))
    if not ups and not downs:
        v, arah, s = max(best)
        txt += "   (belum ada; terdekat %s %d%% %s)" % (short_name(s), round(v), arah)
    return txt


def build_info(label, tf, ana, now, scan, threshold, kind=None, plan=None):
    sig = ana.signal if ana else "-"
    head = "GRAFIK: %s %s   |   %s WIB   |   Harga %s   |   Sinyal %s" % (
        label, tf, now.strftime("%d/%m/%Y %H:%M"), fmt_price(ana.price) if ana else "-", sig)
    if kind:
        head += "   |   capture: " + kind
    l2, l3, _ = S.session_line(now)
    return [(head, "#ffb020", True), (l2, "#2fe6a0", True), (l3, "#c0c7d3", False),
            (breakout_line(scan, threshold), "#7dd3fc", True)] + SR.sr_info(plan, fmt_price)


# ---------------------------------------------------------------- tab Multi-TF
class MultiTFTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.history = []
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.lbl = QLabel("")
        self.lbl.setStyleSheet("font-weight:bold; color:#ffb020;")
        top.addWidget(self.lbl, 1)
        top.addWidget(QLabel("Ambang breakout/breakdown (%):"))
        self.thr = QDoubleSpinBox()
        self.thr.setRange(50, 100)
        self.thr.setDecimals(0)
        self.thr.setValue(90)
        self.thr.valueChanged.connect(lambda _: main.refresh_scan_views())
        top.addWidget(self.thr)
        b = QPushButton("SCAN SEKARANG")
        b.clicked.connect(main.start_scan)
        top.addWidget(b)
        lay.addLayout(top)

        mid = QHBoxLayout()
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["TF", "Sinyal", "Tren", "RSI", "Skor breakout", "Skor breakdown"])
        self._setup(self.tbl)
        mid.addWidget(self.tbl, 3)
        self.concl = QTextBrowser()
        mid.addWidget(self.concl, 2)
        lay.addLayout(mid, 2)

        lay.addWidget(QLabel("Pemindai semua koin (skor gabungan 15m/1H/4H/1D)"))
        self.scan_tbl = QTableWidget(0, 8)
        self.scan_tbl.setHorizontalHeaderLabels(["Koin", "15m", "1H", "4H", "1D", "Breakout %", "Breakdown %", "Status"])
        self._setup(self.scan_tbl)
        lay.addWidget(self.scan_tbl, 3)
        lay.addWidget(QLabel("Riwayat kesimpulan"))
        self.hist = QListWidget()
        self.hist.setMaximumHeight(90)
        lay.addWidget(self.hist)

    @staticmethod
    def _setup(t):
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    @staticmethod
    def _cell(text, color=None, bold=False):
        it = QTableWidgetItem(text)
        if color:
            it.setForeground(QColor(color))
        if bold:
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        return it

    @staticmethod
    def _sig_color(sig):
        return "#23ce8c" if "BUY" in sig else "#f2506e" if "SELL" in sig else "#aab2c0"

    def refresh(self, scan, scan_time, sym, threshold):
        thr = threshold
        per = scan.get(sym)
        self.tbl.setRowCount(0)
        label = per[next(iter(per))]["label"] if per else sym
        self.lbl.setText("Multi-TF: %s   (scan %s WIB)" % (
            label, scan_time.strftime("%d/%m/%Y %H:%M") if scan_time else "belum"))
        if per:
            for tf in SCAN_W:
                d = per.get(tf)
                if not d:
                    continue
                r = self.tbl.rowCount()
                self.tbl.insertRow(r)
                tren = "Naik" if d["trend"] > 0 else "Turun" if d["trend"] < 0 else "-"
                for c, (txt, col) in enumerate([(tf, None), (d["signal"], self._sig_color(d["signal"])),
                                                (tren, None), ("%.0f" % d["rsi"], None),
                                                ("%.0f%%" % d["up"], "#23ce8c"), ("%.0f%%" % d["down"], "#f2506e")]):
                    self.tbl.setItem(r, c, self._cell(txt, col, c == 1))
            self._conclusion(sym, per, scan_time, thr)
        self.scan_tbl.setRowCount(0)
        rows = []
        for s, p in scan.items():
            u, d = coin_scores(p)
            rows.append((max(u, d), s, p, u, d))
        for _, s, p, u, d in sorted(rows, reverse=True):
            r = self.scan_tbl.rowCount()
            self.scan_tbl.insertRow(r)
            status = "BREAKOUT" if u >= thr else "BREAKDOWN" if d >= thr else "-"
            self.scan_tbl.setItem(r, 0, self._cell(s, bold=True))
            for c, tf in enumerate(SCAN_W):
                sg = p[tf]["signal"] if tf in p else "-"
                self.scan_tbl.setItem(r, c + 1, self._cell(sg, self._sig_color(sg)))
            self.scan_tbl.setItem(r, 5, self._cell("%.0f%%" % u, "#23ce8c", u >= thr))
            self.scan_tbl.setItem(r, 6, self._cell("%.0f%%" % d, "#f2506e", d >= thr))
            self.scan_tbl.setItem(r, 7, self._cell(status, "#ffb020" if status != "-" else None, status != "-"))

    def _conclusion(self, sym, per, scan_time, thr):
        buys = sum(1 for d in per.values() if d["direction"] > 0)
        sells = sum(1 for d in per.values() if d["direction"] < 0)
        total = len(per)
        if buys >= 3 or (buys == total and total):
            bias, col = "NAIK (cenderung BUY)", "#23ce8c"
        elif sells >= 3 or (sells == total and total):
            bias, col = "TURUN (cenderung SELL)", "#f2506e"
        else:
            bias, col = "CAMPURAN - tunggu konfirmasi", "#ffb020"
        u, d = coin_scores(per)
        detail = ", ".join("%s %s" % (tf, per[tf]["signal"]) for tf in SCAN_W if tf in per)
        stamp = (scan_time or S.now_wib()).strftime("%d/%m/%Y pukul %H:%M WIB")
        msg = ("<b>Kesimpulan dibuat %s</b><br><b>%s</b>: bias <span style='color:%s'><b>%s</b></span><br>"
               "%d TF buy, %d TF sell dari %d TF.<br>%s<br>Skor breakout %.0f%% | breakdown %.0f%%<br>%s" % (
                   stamp, sym, col, bias, buys, sells, total, detail, u, d,
                   "<b style='color:#ffb020'>Mencapai ambang %d%%.</b>" % thr if max(u, d) >= thr
                   else "Belum mencapai ambang %d%%." % thr))
        self.concl.setHtml(msg)
        line = "%s - %s: %s (breakout %.0f%%, breakdown %.0f%%)" % (
            (scan_time or S.now_wib()).strftime("%d/%m/%Y %H:%M"), sym, bias, u, d)
        if not self.history or self.history[0].split(" - ", 1)[1].split(" (")[0] != line.split(" - ", 1)[1].split(" (")[0]:
            self.history.insert(0, line)
            self.hist.insertItem(0, line)
            while self.hist.count() > 100:
                self.hist.takeItem(self.hist.count() - 1)


# ---------------------------------------------------------------- tab Kalkulator
class CalcTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        lay = QHBoxLayout(self)
        form = QFormLayout()

        def spin(val, lo, hi, dec=2, step=1.0):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSingleStep(step)
            s.setValue(val)
            s.valueChanged.connect(self.calc)
            return s

        self.modal = spin(100, 1, 1e9)
        self.preset = QComboBox()
        for name, v in (("Emas XAUUSD (100 oz / lot)", 100), ("BTC (1 / lot)", 1), ("ETH (1 / lot)", 1),
                        ("Kontrak lain (isi manual)", 1)):
            self.preset.addItem(name, v)
        self.preset.currentIndexChanged.connect(self._preset)
        self.cs = spin(100, 0.0001, 1e9, 4)
        self.lot = spin(0.01, 0.001, 1000, 3, 0.01)
        self.price = spin(4000, 0, 1e9, 4)
        self.sl = spin(30, 0.0001, 1e9, 4)
        self.atr = spin(16, 0.0001, 1e9, 4)
        self.lev = spin(500, 1, 3000, 0)
        self.win = spin(50, 1, 99, 0)
        self.rr = spin(2, 0.1, 20, 2, 0.5)
        self.jph = spin(8, 1, 24, 0)
        form.addRow("Modal (USD)", self.modal)
        form.addRow("Instrumen", self.preset)
        form.addRow("Ukuran kontrak per 1 lot", self.cs)
        form.addRow("Lot", self.lot)
        form.addRow("Harga sekarang", self.price)
        form.addRow("Jarak Stop Loss (satuan harga)", self.sl)
        form.addRow("Rata-rata gerak 1 jam (ATR 1H)", self.atr)
        form.addRow("Leverage (1:x)", self.lev)
        form.addRow("Win rate (%)", self.win)
        form.addRow("Risk : Reward (1 : x)", self.rr)
        form.addRow("Jam trading per hari", self.jph)
        b = QPushButton("ISI OTOMATIS DARI PASAR (harga dan ATR 1H koin terpilih)")
        b.clicked.connect(self.autofill)
        left = QVBoxLayout()
        left.addLayout(form)
        left.addWidget(b)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setMaximumWidth(420)
        lay.addWidget(lw)
        self.out = QTextBrowser()
        lay.addWidget(self.out, 1)
        self.calc()

    def _preset(self):
        self.cs.setValue(self.preset.currentData())

    def autofill(self):
        sym = self.main.symbol
        self.out.setHtml("Mengambil data %s..." % sym)
        run_async(lambda: D.fetch_klines(sym, "1H", 200), self._filled)

    def _filled(self, cd):
        if isinstance(cd, Exception):
            self.out.setHtml("Gagal mengambil data: %s" % cd)
            return
        a = A.analyze(cd)
        for s in (self.price, self.atr, self.sl):
            s.blockSignals(True)
        self.price.setValue(a.price)
        self.atr.setValue(a.atr)
        self.sl.setValue(round(a.atr * 1.5, 4))
        for s in (self.price, self.atr, self.sl):
            s.blockSignals(False)
        self.preset.setCurrentIndex(0 if "XAU" in cd.label else 1)
        self.calc()

    @staticmethod
    def _dur(h):
        if h < 1:
            return "kurang dari 1 jam"
        d, r = divmod(int(h), 24)
        return "%d jam" % h if not d else "%d jam (≈ %d hari %d jam)" % (h, d, r)

    def calc(self, *_):
        M, cs, lot = self.modal.value(), self.cs.value(), self.lot.value()
        sl, atr, price = self.sl.value(), self.atr.value(), self.price.value()
        w, rr, jph = self.win.value() / 100, self.rr.value(), self.jph.value()
        loss = lot * cs * sl
        loss_atr = lot * cs * atr
        margin = lot * cs * price / self.lev.value()
        n_sl = int(M // loss) if loss else 0
        n_atr = int(M // loss_atr) if loss_atr else 0
        risk = loss / M * 100
        exp = loss * (w * rr - (1 - w))
        safe_lot = M * 0.02 / (cs * sl)
        ruin = (1 - w) ** n_sl * 100 if n_sl else 100
        h = []
        h.append("<h3 style='color:#ffb020'>Kekuatan modal bila trading 1 jam (timeframe 1H)</h3>")
        h.append("<p>Modal <b>$%.2f</b>, lot <b>%.3f</b>, SL <b>%s</b>. Setiap trade 1 jam rugi penuh "
                 "<b>$%.2f</b> (%.1f%% modal).</p>" % (M, lot, fmt_price(sl), loss, risk))
        h.append("<p style='font-size:12pt'>⏱ Bila <b>kalah terus tiap jam</b> (SL kena): modal bertahan "
                 "<b style='color:#f2506e'>%s</b>.</p>" % self._dur(n_sl))
        h.append("<p>⏱ Bila tiap jam hanya terkena gerak rata-rata 1 jam melawan posisi (ATR %s = $%.2f): "
                 "bertahan <b style='color:#ffb020'>%s</b>.</p>" % (fmt_price(atr), loss_atr, self._dur(n_atr)))
        h.append("<p>Dalam hari trading %d jam: SL penuh habis dalam ≈ <b>%.1f hari</b>.</p>" % (
            jph, n_sl / jph if jph else 0))
        h.append("<p>Peluang kalah berturut-turut %d kali (win rate %.0f%%): <b>%.2f%%</b>.</p>" % (
            n_sl, w * 100, ruin))
        if exp >= 0:
            h.append("<p>Ekspektasi per jam: <b style='color:#23ce8c'>+$%.2f</b> (modal cenderung tumbuh bila win rate "
                     "terjaga).</p>" % exp)
        else:
            hrs = int(M // -exp)
            h.append("<p>Ekspektasi per jam: <b style='color:#f2506e'>-$%.2f</b>; modal habis rata-rata dalam "
                     "≈ <b>%s</b>.</p>" % (-exp, self._dur(hrs)))
        h.append("<hr><p>Margin dibutuhkan: <b>$%.2f</b> %s<br>Lot aman (risiko 2%% per trade): <b>%.3f</b>" % (
            margin, "<b style='color:#f2506e'>(melebihi modal!)</b>" if margin > M else "", safe_lot))
        if risk > 5:
            h.append("<br><b style='color:#f2506e'>Risiko per trade %.1f%% terlalu besar</b> (disarankan ≤ 2%%)." % risk)
        h.append("</p><p style='color:#6b7280'>Perkiraan alat bantu, bukan jaminan. Spread, swap, dan slippage tidak dihitung.</p>")
        self.out.setHtml("".join(h))


# ---------------------------------------------------------------- tab MT5
class MT5Tab(QWidget):
    COMMON = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "Common", "Files")

    def __init__(self):
        super().__init__()
        self.auto = False
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.lot_b, self.lot_s = QDoubleSpinBox(), QDoubleSpinBox()
        for s, nm in ((self.lot_b, "Lot BUY"), (self.lot_s, "Lot SELL")):
            s.setRange(0.01, 100)
            s.setDecimals(2)
            s.setSingleStep(0.01)
            s.setValue(0.01)
            row.addWidget(QLabel(nm))
            row.addWidget(s)
        self.btn_auto = QPushButton("AUTO TRADE: OFF")
        self.btn_auto.setCheckable(True)
        self.btn_auto.clicked.connect(self.toggle_auto)
        b_close = QPushButton("TUTUP SEMUA POSISI")
        b_close.clicked.connect(self.close_all)
        b_ea = QPushButton("PASANG EA KE MT5")
        b_ea.clicked.connect(self.install_ea)
        for b in (self.btn_auto, b_close, b_ea):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.rules = QLabel(
            "BUY 0.01 saat BuE / CHoCH bullish, ditutup di candle ke-3 Three Black Crows. "
            "SELL 0.01 saat BeE / CHoCH bearish, ditutup di candle ke-3 Three White Soldiers. "
            "Maks. 1 BUY dan 1 SELL. UJI DULU DI AKUN DEMO.")
        self.rules.setWordWrap(True)
        self.rules.setStyleSheet("color:#ffb020")
        lay.addWidget(self.rules)
        self.status = QLabel("EA belum terdeteksi")
        self.status.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.status)
        self.pos = QTableWidget(0, 5)
        self.pos.setHorizontalHeaderLabels(["Tiket", "Tipe", "Lot", "Harga buka", "Profit"])
        self.pos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pos.setMaximumHeight(150)
        lay.addWidget(self.pos)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        t = QTimer(self)
        t.timeout.connect(self.poll)
        t.start(2000)

    def _write_cmd(self, closeall=False):
        try:
            os.makedirs(self.COMMON, exist_ok=True)
            with open(os.path.join(self.COMMON, "RecognitoCmd.txt"), "w", encoding="ascii") as f:
                f.write("ID=%d\r\nAUTO=%d\r\nLOTBUY=%.2f\r\nLOTSELL=%.2f\r\nCLOSEALL=%d\r\n" % (
                    int(time.time() * 1000), 1 if self.auto else 0, self.lot_b.value(), self.lot_s.value(),
                    1 if closeall else 0))
            return True
        except OSError as e:
            QMessageBox.warning(self, "MT5", "Gagal menulis perintah ke MT5:\n%s" % e)
            return False

    def toggle_auto(self):
        want = self.btn_auto.isChecked()
        if want and QMessageBox.question(
                self, "AUTO TRADE", "Aktifkan auto trade? Pastikan EA terpasang dan memakai akun DEMO dulu."
        ) != QMessageBox.StandardButton.Yes:
            self.btn_auto.setChecked(False)
            return
        self.auto = want
        self.btn_auto.setText("AUTO TRADE: ON" if want else "AUTO TRADE: OFF")
        self._write_cmd()

    def close_all(self):
        if QMessageBox.question(self, "Tutup semua", "Tutup semua posisi milik EA?") == QMessageBox.StandardButton.Yes:
            self._write_cmd(closeall=True)

    def install_ea(self):
        src = os.path.join(RES, "RecognitoBridge.mq5")
        dirs = glob.glob(os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "*", "MQL5", "Experts"))
        if not os.path.exists(src) or not dirs:
            QMessageBox.warning(self, "Pasang EA", "Folder MQL5\\Experts MetaTrader 5 tidak ditemukan.\n"
                                "Buka MT5 sekali lalu coba lagi, atau salin RecognitoBridge.mq5 manual.")
            return
        for d in dirs:
            shutil.copy(src, os.path.join(d, "RecognitoBridge.mq5"))
        QMessageBox.information(
            self, "Pasang EA", "EA disalin ke %d terminal MT5.\n\nDi MT5: Refresh Navigator / Compile (F7) > "
            "seret RecognitoBridge ke chart XAUUSD > izinkan Algo Trading." % len(dirs))

    def poll(self):
        path = os.path.join(self.COMMON, "RecognitoStatus.txt")
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
        except OSError:
            return
        kv, pos, logs = {}, [], []
        for ln in lines:
            if "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            if k == "POS":
                pos.append(v.split(";"))
            elif k == "LOG":
                logs.append(v)
            else:
                kv[k] = v
        alive = False
        try:
            alive = abs((datetime.now() - datetime.strptime(kv.get("LOCAL", ""), "%Y.%m.%d %H:%M:%S")).total_seconds()) < 20
        except ValueError:
            pass
        col = "#23ce8c" if alive and kv.get("EA") == "ON" else "#f2506e"
        self.status.setText(
            "<span style='color:%s'><b>EA %s</b></span> | Akun %s (%s) | %s %s | Harga %s | Saldo %s %s | Equity %s | "
            "BUY %s / SELL %s | Profit %s | Auto %s" % (
                col, "AKTIF" if alive else "TIDAK AKTIF", kv.get("ACCOUNT", "-"), kv.get("SERVER", "-"),
                kv.get("SYMBOL", "-"), kv.get("TF", ""), kv.get("PRICE", "-"), kv.get("BALANCE", "-"),
                kv.get("CURRENCY", ""), kv.get("EQUITY", "-"), kv.get("POS_BUY", "0"), kv.get("POS_SELL", "0"),
                kv.get("PROFIT", "0"), "ON" if kv.get("AUTO") == "1" else "OFF"))
        self.pos.setRowCount(len(pos))
        for r, row in enumerate(pos):
            for c, v in enumerate(row[:5]):
                self.pos.setItem(r, c, QTableWidgetItem(v))
        self.log.setPlainText("\n".join(reversed(logs)))


# ---------------------------------------------------------------- tab Capture
class CaptureTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        for text, fn in (("CAPTURE SEKARANG", main.manual_capture), ("HAPUS", self.delete_sel),
                         ("HAPUS SEMUA", self.delete_all), ("BUKA FOLDER", self.open_folder)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addWidget(QLabel("Otomatis: tiap 1 jam (1H), blok 4 jam WIB (4H), dan pergantian sesi."))
        row.addStretch(1)
        lay.addLayout(row)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.tbl = QTableWidget(0, 7)
        self.tbl.setHorizontalHeaderLabels(["Waktu (WIB)", "Grafik", "Sesi", "Harga", "Sinyal", "Jenis", "File"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.itemSelectionChanged.connect(self.preview)
        sp.addWidget(self.tbl)
        self.img = QLabel("Pilih capture untuk melihat gambar")
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setMinimumHeight(200)
        sp.addWidget(self.img)
        sp.setSizes([260, 400])
        lay.addWidget(sp, 1)
        self.load()

    def load(self):
        self.tbl.setRowCount(0)
        if not os.path.exists(CAPTURE_LOG):
            return
        with open(CAPTURE_LOG, encoding="utf-8") as f:
            rows = [ln.rstrip("\n").split("\t") for ln in f if ln.strip()]
        for r in reversed(rows):
            r = (r + [""] * 7)[:7]
            self._add_row(r[:5] + [r[6], r[5]])  # berkas: ... file, jenis -> tabel: ... jenis, file

    def _add_row(self, cols, top=False):
        cols = (cols + [""] * 7)[:7]
        r = 0 if top else self.tbl.rowCount()
        self.tbl.insertRow(r)
        for c, v in enumerate(cols):
            self.tbl.setItem(r, c, QTableWidgetItem(v))

    def add_record(self, label, tf, sess, price, signal, fname, kind, now):
        cols = [now.strftime("%d/%m/%Y %H:%M"), "%s %s" % (label, tf), sess, "%.2f" % price, signal, fname, kind]
        with open(CAPTURE_LOG, "a", encoding="utf-8") as f:
            f.write("\t".join(cols[:5] + [fname, kind]) + "\n")
        self._add_row([cols[0], cols[1], cols[2], cols[3], cols[4], kind, fname], top=True)

    def _rewrite(self):
        rows = []
        for r in range(self.tbl.rowCount() - 1, -1, -1):
            v = [self.tbl.item(r, c).text() for c in range(7)]
            rows.append("\t".join([v[0], v[1], v[2], v[3], v[4], v[6], v[5]]))
        with open(CAPTURE_LOG, "w", encoding="utf-8") as f:
            f.write("".join(x + "\n" for x in rows))

    def preview(self):
        r = self.tbl.currentRow()
        if r < 0:
            return
        pm = QPixmap(os.path.join(CAPTURE_DIR, self.tbl.item(r, 6).text()))
        if pm.isNull():
            self.img.setText("Gambar tidak ditemukan")
        else:
            self.img.setPixmap(pm.scaled(self.img.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))

    def delete_sel(self):
        rows = sorted({i.row() for i in self.tbl.selectedItems()}, reverse=True)
        for r in rows:
            try:
                os.remove(os.path.join(CAPTURE_DIR, self.tbl.item(r, 6).text()))
            except OSError:
                pass
            self.tbl.removeRow(r)
        self._rewrite()
        self.img.clear()

    def delete_all(self):
        if QMessageBox.question(self, "Hapus semua", "Hapus semua gambar capture?") != QMessageBox.StandardButton.Yes:
            return
        for f in glob.glob(os.path.join(CAPTURE_DIR, "*.jpg")):
            try:
                os.remove(f)
            except OSError:
                pass
        self.tbl.setRowCount(0)
        self._rewrite()
        self.img.clear()

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(CAPTURE_DIR))


# ---------------------------------------------------------------- jendela utama
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_icon())
        self.resize(1500, 950)
        self.symbol, self.tf = "XAUUSDT", "1H"
        self.ana = self.cd = self.pv = None
        self.scan, self.scan_time, self.scanning = {}, None, False
        self.events, self.fired, self.last_alert = [], set(), {}
        self.alarm_on = True
        self.tickers = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        bar = QHBoxLayout()
        title = QLabel("RECOGNITO TRADING FERNANDA")
        title.setStyleSheet("font-size:13pt; font-weight:bold; color:#ffb020;")
        bar.addWidget(title)
        bar.addSpacing(20)
        self.tf_btns = {}
        for tf in TF_ORDER:
            b = QPushButton(tf)
            b.setCheckable(True)
            b.setChecked(tf == self.tf)
            b.clicked.connect(lambda _, t=tf: self.set_tf(t))
            self.tf_btns[tf] = b
            bar.addWidget(b)
        bar.addSpacing(20)
        self.btn_alarm = QPushButton("ALARM: ON")
        self.btn_alarm.setCheckable(True)
        self.btn_alarm.setChecked(True)
        self.btn_alarm.clicked.connect(self.toggle_alarm)
        bar.addWidget(self.btn_alarm)
        bc = QPushButton("CAPTURE")
        bc.clicked.connect(self.manual_capture)
        bar.addWidget(bc)
        bar.addStretch(1)
        self.lbl_clock = QLabel("")
        bar.addWidget(self.lbl_clock)
        root.addLayout(bar)

        body = QHBoxLayout()
        self.coin_list = QListWidget()
        self.coin_list.setMaximumWidth(230)
        self.coin_list.setFont(QFont("Consolas", 9))
        for s in D.WATCHLIST:
            QListWidgetItem(s, self.coin_list)
        self.coin_list.setCurrentRow(0)
        self.coin_list.currentRowChanged.connect(self.pick_coin)
        body.addWidget(self.coin_list)
        self.tabs = QTabWidget()
        self.chart = ChartWidget()
        self.mtf = MultiTFTab(self)
        self.calc = CalcTab(self)
        self.mt5 = MT5Tab()
        self.cap = CaptureTab(self)
        for w, n in ((self.chart, "Grafik"), (self.mtf, "Multi-TF"), (self.calc, "Kalkulator"),
                     (self.mt5, "MT5"), (self.cap, "Capture")):
            self.tabs.addTab(w, n)
        body.addWidget(self.tabs, 1)
        root.addLayout(body, 1)
        self.lbl_src = QLabel("")
        self.statusBar().addPermanentWidget(self.lbl_src)
        self.statusBar().showMessage("Memuat data Binance...")

        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.show()

        self.events = S.builtin_events(S.now_wib().year) + S.builtin_events(S.now_wib().year + 1) \
            + S.read_events_txt(EVENTS_TXT)
        self._timer(10000, self.load_chart)
        self._timer(15000, self.load_tickers)
        self._timer(20000, self.tick)
        self._timer(30000, self.check_signal)
        self._timer(120000, self.start_scan)
        self._timer(3 * 3600 * 1000, self.load_online_events)
        self._timer(1000, self.clock)
        self.load_chart()
        self.load_tickers()
        self.start_scan()
        self.load_online_events()

    def _timer(self, ms, fn):
        t = QTimer(self)
        t.timeout.connect(fn)
        t.start(ms)

    # ---- kontrol
    def clock(self):
        self.lbl_clock.setText(S.now_wib().strftime("%d/%m/%Y %H:%M:%S WIB"))

    def set_tf(self, tf):
        self.tf = tf
        for t, b in self.tf_btns.items():
            b.setChecked(t == tf)
        self.chart.set_data(self.chart.title, self.chart.tf, None, None, None, [])
        self.load_chart()

    def pick_coin(self, row):
        if row >= 0:
            self.symbol = D.WATCHLIST[row]
            self.chart.set_data("", self.tf, None, None, None, [])
            self.load_chart()
            self.refresh_scan_views()

    def toggle_alarm(self):
        self.alarm_on = self.btn_alarm.isChecked()
        self.btn_alarm.setText("ALARM: ON" if self.alarm_on else "ALARM: OFF")

    @property
    def threshold(self):
        return int(self.mtf.thr.value())

    # ---- data
    def sr_plan(self, cd, tf):
        if tf != "4H":
            return None
        c = self.calc
        return SR.sr_plan(cd, c.modal.value(), c.lot.value(), c.cs.value(), D.TF_SECONDS["4H"], time.time())

    def load_chart(self):
        run_async(fetch_chart, self._chart_done, self.symbol, self.tf)

    def _chart_done(self, res):
        if isinstance(res, Exception):
            self.statusBar().showMessage("Gagal memuat data: %s" % res)
            return
        sym, tf, cd, a, pv = res
        if sym != self.symbol or tf != self.tf:
            return
        self.cd, self.ana, self.pv = cd, a, pv
        plan = self.sr_plan(cd, tf)
        self.chart.sr = plan
        self.chart.set_data(cd.label, tf, cd, a, pv,
                            build_info(cd.label, tf, a, S.now_wib(), self.scan, self.threshold, plan=plan))
        self.lbl_src.setText("Sumber: Binance %s | update %s" % (cd.label, S.now_wib().strftime("%H:%M:%S")))
        self.statusBar().showMessage("Sinyal %s: %s" % (cd.label, a.signal))

    def load_tickers(self):
        run_async(lambda: D.fetch_tickers(D.WATCHLIST), self._tickers_done)

    def _tickers_done(self, res):
        if isinstance(res, Exception):
            return
        for i, s in enumerate(D.WATCHLIST):
            if s in res:
                p, ch = res[s]
                it = self.coin_list.item(i)
                it.setText("%-9s %10s  %+.2f%%" % (short_name(s), fmt_price(p), ch))
                it.setForeground(QColor("#23ce8c" if ch >= 0 else "#f2506e"))

    def start_scan(self):
        if self.scanning:
            return
        self.scanning = True
        run_async(do_scan, self._scan_done, list(D.WATCHLIST))

    def _scan_done(self, res):
        self.scanning = False
        if isinstance(res, Exception) or not res:
            return
        self.scan, self.scan_time = res, S.now_wib()
        self.refresh_scan_views()

    def refresh_scan_views(self):
        self.mtf.refresh(self.scan, self.scan_time, self.symbol, self.threshold)
        if self.cd is not None:
            self.chart.set_info(build_info(self.cd.label, self.tf, self.ana, S.now_wib(), self.scan, self.threshold))

    def load_online_events(self):
        run_async(S.fetch_online_events, self._events_done)

    def _events_done(self, res):
        if isinstance(res, Exception):
            return
        known = {(e[0], e[1]) for e in self.events}
        self.events += [e for e in res if (e[0], e[1]) not in known]

    # ---- alarm
    def notify(self, title, msg):
        self.statusBar().showMessage("%s - %s" % (title, msg), 60000)
        if self.alarm_on:
            beep()
            self.tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 10000)
            QApplication.alert(self, 5000)

    def once(self, key):
        if key in self.fired:
            return False
        self.fired.add(key)
        return True

    def tick(self):
        now = S.now_wib()
        # pergantian sesi
        for h in S.SESSION_HOURS:
            t = now.replace(hour=h, minute=0, second=0, microsecond=0)
            for off, tag in ((-5, "pre"), (0, "at")):
                dt = (now - (t + timedelta(minutes=off))).total_seconds()
                if 0 <= dt < 90 and self.once(("sess", t.date(), h, tag)):
                    nm = S.segment(h)[2]
                    self.notify("Pergantian sesi", ("5 menit lagi: " if tag == "pre" else "Sekarang: ") + nm)
        # berita
        for dt0, title, impact in self.events:
            if impact.lower() != "high":
                continue
            for off, tag in ((-5, "pre"), (0, "at")):
                dt = (now - (dt0 + timedelta(minutes=off))).total_seconds()
                if 0 <= dt < 90 and self.once(("news", dt0, title, tag)):
                    self.notify("Berita high-impact", ("5 menit lagi: " if tag == "pre" else "RILIS: ") + title)
        # capture terjadwal
        if now.minute == 0 and self.once(("cap", now.date(), now.hour)):
            h = now.hour
            self.start_capture("Sesi" if h in S.SESSION_HOURS else "1 jam", "1H")
            if h in S.BLOCK_ENDS:
                self.start_capture("4 jam " + S.BLOCK_ENDS[h], "4H")

    def check_signal(self):
        if not (self.alarm_on and self.ana):
            return
        key = (self.symbol, self.tf)
        sig = self.ana.signal
        if "STRONG" in sig and self.last_alert.get(key) != sig:
            self.last_alert[key] = sig
            self.notify("Sinyal kuat", "%s %s: %s @ %s" % (self.symbol, self.tf, sig, fmt_price(self.ana.price)))
        elif "STRONG" not in sig:
            self.last_alert.pop(key, None)

    # ---- capture
    def manual_capture(self):
        if self.cd is None:
            QMessageBox.information(self, "Capture", "Tunggu grafik tampil dulu.")
            return
        self._save_capture(self.cd, self.ana, self.pv, self.tf, "Manual")

    def start_capture(self, kind, tf):
        run_async(fetch_chart, lambda res: self._capture_ready(res, kind), self.symbol, tf, 500)

    def _capture_ready(self, res, kind):
        if isinstance(res, Exception):
            self.statusBar().showMessage("Capture gagal: %s" % res)
            return
        _, tf, cd, a, pv = res
        self._save_capture(cd, a, pv, tf, kind)

    def _save_capture(self, cd, a, pv, tf, kind):
        now = S.now_wib()
        w = ChartWidget()
        w.resize(1084, 885)
        w.bar_w = 22.0
        plan = self.sr_plan(cd, tf)
        w.sr = plan
        w.set_data(cd.label, tf, cd, a, pv, build_info(cd.label, tf, a, now, self.scan, self.threshold, kind, plan))
        fname = "%s_%s_%s.jpg" % (re.sub(r"[^A-Za-z0-9]", "_", cd.label), tf, now.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        if not w.grab().save(os.path.join(CAPTURE_DIR, fname), "JPG", 90):
            self.statusBar().showMessage("Gagal menyimpan capture")
            return
        self.cap.add_record(cd.label, tf, S.segment(now.hour)[2], a.price, a.signal, fname, kind, now)
        self.statusBar().showMessage("Capture tersimpan: %s (%s)" % (fname, kind), 15000)


def main():
    global _bus
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    _bus = _Bus()
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
