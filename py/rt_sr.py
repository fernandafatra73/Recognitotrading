"""Rencana support/resisten candle 4 jam: beli di support, jual di resisten, cut loss 1% modal."""
from dataclasses import dataclass

CUT_PCT = 1.0  # cut loss bila tembus support/resisten dan rugi sudah 1% dari modal


@dataclass
class SRPlan:
    sup: float
    res: float
    cut_buy: float
    cut_sell: float
    wipe_buy: float    # harga turun sampai di sini -> modal habis (beli di support)
    wipe_sell: float   # harga naik sampai di sini -> modal habis (jual di resisten)
    modal: float
    lot: float
    cut_usd: float
    price: float
    status: str
    secs_left: int


def sr_plan(cd, modal, lot, cs, tf_sec, now_ts):
    """S/R = low/high candle 4 jam terakhir yang sudah tutup. Ganti candle -> dihitung ulang."""
    if cd is None or len(cd) < 3 or lot <= 0 or cs <= 0:
        return None
    sup, res = float(cd.l[-2]), float(cd.h[-2])
    price = float(cd.c[-1])
    per_unit = lot * cs                      # rugi/untung dalam USD per 1 satuan harga
    cut_usd = modal * CUT_PCT / 100
    d_cut, d_wipe = cut_usd / per_unit, modal / per_unit
    if price < sup:
        status = "HARGA TEMBUS SUPPORT -> posisi BUY dari support kena CUT LOSS"
    elif price > res:
        status = "HARGA TEMBUS RESISTEN -> posisi SELL dari resisten kena CUT LOSS"
    else:
        zone = (price - sup) / (res - sup) if res > sup else 0.5
        status = "Harga di dalam range (%.0f%% dari support ke resisten)" % (zone * 100)
    secs_left = int(tf_sec - (now_ts - cd.t[-1] / 1000))
    return SRPlan(sup, res, sup - d_cut, res + d_cut, sup - d_wipe, res + d_wipe,
                  modal, lot, cut_usd, price, status, max(0, secs_left))


def sr_info(plan, fmt):
    if plan is None:
        return []
    h, m = divmod(plan.secs_left // 60, 60)
    return [
        ("4 JAM  Support (BUY) %s  |  Resisten (SELL) %s  |  %s  |  ganti candle %dj %02dm lagi -> hitung ulang" % (
            fmt(plan.sup), fmt(plan.res), plan.status, h, m), "#ffb020", True),
        ("Modal $%.2f, lot %.3f:  CUT LOSS (rugi %.0f%% = $%.2f)  BUY < %s   SELL > %s" % (
            plan.modal, plan.lot, 1.0, plan.cut_usd, fmt(plan.cut_buy), fmt(plan.cut_sell)), "#f2506e", True),
        ("MODAL HABIS bila beli di support %s -> turun ke %s   |   jual di resisten %s -> naik ke %s" % (
            fmt(plan.sup), fmt(plan.wipe_buy), fmt(plan.res), fmt(plan.wipe_sell)), "#c0c7d3", False),
    ]
