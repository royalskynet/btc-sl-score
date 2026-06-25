#!/usr/bin/env python3
"""BTC bottom composite score 0-100. Higher = closer to bottom.

7-signal composite (4 macro + 3 on-chain).
Free APIs only, no auth. Stores daily history to sqlite.

  python3 btc_bottom_score.py            # full table + observation
  python3 btc_bottom_score.py --summary  # 3-section TG-friendly summary
  python3 btc_bottom_score.py --history 30

v2.1 changes (methodology hardening, no new signals):
  - source-level fallback for the 4 bitcoin-data.com on-chain metrics
  - retry with exponential backoff in _get
  - piecewise-LINEAR scoring (interpolated) instead of stepped buckets
  - Hash Ribbon converted from boolean to continuous depth-of-capitulation
  - confidence flag when signals are missing
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = {"User-Agent": "btc-bottom-score/2.1"}

DB_PATH = Path(
    os.environ.get(
        "BTC_SL_DB",
        str(Path.home() / ".btc-sl-score" / "history.db"),
    )
)

BOTTOM_ANCHOR = 85  # 抄底錨點
TOP_ANCHOR = 20     # 清倉錨點


def _get(url: str, retries: int = 3, backoff: float = 1.5):
    """GET JSON with retry + exponential backoff. Returns None on total failure."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff ** attempt)
    return None


def _get_first(urls, extractor):
    """Try each url in order; return extractor(resp) for the first that works."""
    for u in urls:
        d = _get(u)
        if d is None:
            continue
        try:
            v = extractor(d)
            if v is not None:
                return v
        except Exception:  # noqa: BLE001
            continue
    return None


# --- fetchers ----------------------------------------------------------------

def fear_greed():
    return _get_first(
        ["https://api.alternative.me/fng/?limit=1"],
        lambda d: int(d["data"][0]["value"]),
    )


def mvrv_zscore():
    return _get_first(
        [
            "https://bitcoin-data.com/api/v1/mvrv-zscore/last",
            "https://bitcoin-data.com/v1/mvrv-zscore/last",
        ],
        lambda d: float(
            next(d[k] for k in ("mvrvZscore", "value", "mvrv_zscore") if k in d)
        ),
    )


def hash_ribbon_depth():
    """Return signed depth of (ma30 - ma60) / ma60.

    Negative => 30D MA below 60D MA => miner capitulation.
    The more negative, the deeper the capitulation.
    Returns float ratio, or None on failure.
    """
    d = _get("https://mempool.space/api/v1/mining/hashrate/3y")
    if d is None:
        return None
    try:
        rates = [x["avgHashrate"] for x in d["hashrates"]][-180:]
        if len(rates) < 60:
            return None
        ma30 = sum(rates[-30:]) / 30
        ma60 = sum(rates[-60:]) / 60
        return (ma30 - ma60) / ma60
    except Exception:  # noqa: BLE001
        return None


def price_ma200_ratio():
    d = _get(
        "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        "?vs_currency=usd&days=200&interval=daily"
    )
    if d is None:
        # fallback: coincap daily history (~200d)
        d2 = _get(
            "https://api.coincap.io/v2/assets/bitcoin/history"
            "?interval=d1"
        )
        if d2 is None:
            return None
        try:
            closes = [float(p["priceUsd"]) for p in d2["data"]][-200:]
            return closes[-1] / (sum(closes) / len(closes))
        except Exception:  # noqa: BLE001
            return None
    try:
        closes = [p[1] for p in d["prices"]]
        return closes[-1] / (sum(closes) / len(closes))
    except Exception:  # noqa: BLE001
        return None


def sth_mvrv():
    return _get_first(
        [
            "https://bitcoin-data.com/api/v1/sth-mvrv/last",
            "https://bitcoin-data.com/v1/sth-mvrv/last",
        ],
        lambda d: float(d["sthMvrv"]),
    )


def lth_sopr():
    return _get_first(
        [
            "https://bitcoin-data.com/api/v1/lth-sopr/last",
            "https://bitcoin-data.com/v1/lth-sopr/last",
        ],
        lambda d: float(d["lthSopr"]),
    )


def nupl():
    return _get_first(
        [
            "https://bitcoin-data.com/api/v1/nupl/last",
            "https://bitcoin-data.com/v1/nupl/last",
        ],
        lambda d: float(d["nupl"]),
    )


# --- scoring (0-100; higher = closer to bottom) ------------------------------

def _interp(v, table):
    """Piecewise-linear interpolation.

    table: list of (breakpoint_value, score) sorted by breakpoint ascending.
    Score is interpolated linearly between adjacent breakpoints, and clamped
    to the end scores outside the range.
    """
    pts = sorted(table, key=lambda p: p[0])
    if v <= pts[0][0]:
        return float(pts[0][1])
    if v >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= v <= x1:
            if x1 == x0:
                return float(y0)
            t = (v - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return float(pts[-1][1])


def _fng(v):
    if v is None:
        return None, "N/A"
    return max(0.0, min(100.0, 100.0 - v)), f"{v}"


def _mvrv(z):
    if z is None:
        return None, "N/A"
    # higher score = closer to bottom; low/negative MVRV-Z = undervalued
    return _interp(z, [
        (-0.5, 100), (0.0, 92), (1.0, 72), (2.5, 42), (5.0, 18), (8.0, 5),
    ]), f"{z:.2f}"


def _hr(depth):
    """Continuous hash-ribbon score from (ma30-ma60)/ma60 deviation.

    depth <= -0.10 (deep capitulation) -> 100
    depth ==  0.00 (cross point)        -> 55
    depth >=  0.10 (strong expansion)   -> 20
    """
    if depth is None:
        return None, "N/A"
    score = _interp(depth, [
        (-0.15, 100), (-0.05, 85), (0.0, 55), (0.05, 35), (0.15, 20),
    ])
    pct = depth * 100
    return score, f"{pct:+.1f}%"


def _ma(r):
    if r is None:
        return None, "N/A"
    return _interp(r, [
        (0.60, 100), (0.70, 95), (0.85, 82), (1.0, 62), (1.2, 42), (1.5, 22), (2.0, 8),
    ]), f"{r:.3f}"


def _sth(v):
    if v is None:
        return None, "N/A"
    return _interp(v, [
        (0.65, 100), (0.70, 96), (0.85, 88), (1.0, 68), (1.2, 48), (1.5, 28), (2.0, 12),
    ]), f"{v:.2f}"


def _lth_s(v):
    if v is None:
        return None, "N/A"
    return _interp(v, [
        (0.90, 100), (0.95, 96), (1.0, 90), (1.1, 68), (1.5, 48), (2.5, 28), (4.0, 12),
    ]), f"{v:.3f}"


def _nupl_s(v):
    if v is None:
        return None, "N/A"
    return _interp(v, [
        (-0.10, 100), (0.0, 94), (0.25, 80), (0.5, 56), (0.65, 38), (0.75, 22), (0.85, 8),
    ]), f"{v:.3f}"


# --- interpretation ----------------------------------------------------------

ZONES = [
    (90, "DEEP CAPITULATION", "🟢🟢", "歷史級底部"),
    (80, "CAPITULATION",      "🟢",   "抄底區"),
    (65, "BOTTOM FORMING",    "🟡",   "築底中"),
    (50, "MID",               "⚪",   "中性"),
    (35, "ELEVATED",          "🟠",   "偏多倉"),
    (20, "EUPHORIA",          "🔴",   "過熱"),
    (0,  "TOP",               "🔴🔴", "頂部"),
]


def interpret(score):
    for cut, name, emoji, zh in ZONES:
        if score >= cut:
            return emoji, name, zh
    return "🔴🔴", "TOP", "頂部"


def _label(name, val, s):
    """plain-language label per signal"""
    if s is None:
        return f"{name} 無資料"
    if name == "Fear & Greed":
        v = int(val)
        mood = ("極度恐懼" if v <= 25 else "恐懼" if v <= 45 else "中性"
                if v <= 55 else "貪婪" if v <= 75 else "極度貪婪")
        return f"情緒{mood} {val}"
    if name == "MVRV Z-Score":
        z = float(val)
        return f"MVRV {'低估' if z < 1 else '偏低' if z < 2.5 else '高估'} {val}"
    if name == "Hash Ribbon":
        # val is like "-4.2%"
        dep = float(val.rstrip("%"))
        return f"礦工{'投降' if dep < 0 else '擴張'} {val}"
    if name == "Price / MA200":
        r = float(val)
        pct = (r - 1) * 100
        return f"價格{'低於' if r < 1 else '高於'} 200MA {abs(pct):.0f}%"
    if name == "STH-MVRV":
        v = float(val)
        return f"短期持有者{'投降' if v < 0.85 else '帳面虧損' if v < 1 else '獲利中'} {val}"
    if name == "LTH-SOPR":
        v = float(val)
        return f"老錢{'割肉' if v < 1 else '賺著賣' if v < 1.5 else '派發'} {val}"
    if name == "NUPL":
        v = float(val)
        z = ("capitulation" if v < 0.25 else "hope" if v < 0.5 else "optimism"
             if v < 0.65 else "belief" if v < 0.75 else "euphoria")
        return f"NUPL 進 {z} {val}"
    return f"{name} {val}"


def observation(score, rows, confidence):
    capitulation = sum(1 for _, s, _, _ in rows if s is not None and s >= 80)
    conf_note = "" if confidence >= 0.85 else f"（僅 {confidence*100:.0f}% 權重有資料，可信度下降）"
    if score >= 90:
        return f"七訊號中 {capitulation} 個在抄底區；五年一遇等級。全倉。{conf_note}"
    if score >= 85:
        return f"七訊號中 {capitulation} 個在抄底區；高出抄底錨點 {BOTTOM_ANCHOR} 分 {score-BOTTOM_ANCHOR:.1f} → 重倉時機。{conf_note}"
    if score >= 70:
        return f"{capitulation}/7 訊號投降；距抄底錨點 {BOTTOM_ANCHOR} 還差 {BOTTOM_ANCHOR-score:.1f} 分 → 試倉、等最後一插針。{conf_note}"
    if score >= 50:
        return f"中性區，鏈上訊號未集體投降。觀望。{conf_note}"
    if score >= 35:
        return f"偏多倉時期；持倉不加碼。{conf_note}"
    if score >= 20:
        return f"過熱區，距清倉錨點 {TOP_ANCHOR} 還差 {score-TOP_ANCHOR:.1f} 分 → 減倉防守。{conf_note}"
    return f"歷史級頂部。清倉。{conf_note}"


# --- output ------------------------------------------------------------------

def summary(rows, composite, confidence):
    emoji, zone_en, zone_zh = interpret(composite)
    labels = [_label(name, val, s) for name, s, val, _ in rows]
    line1 = " / ".join(labels[:3])
    line2 = " / ".join(labels[3:5])
    line3 = " / ".join(labels[5:])
    return (
        f"🪙 BTC 抄底分數：{composite:.1f}/100 → {emoji} {zone_en}（{zone_zh}）\n"
        f"📊 {line1}\n"
        f"    {line2}\n"
        f"    {line3}\n"
        f"💡 {observation(composite, rows, confidence)}"
    )


# --- history -----------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS sl_score (
  d TEXT PRIMARY KEY,
  composite REAL,
  fng INTEGER, mvrv_z REAL, hash_depth REAL, price_ma REAL,
  sth_mvrv REAL, lth_sopr REAL, nupl REAL,
  confidence REAL,
  raw_json TEXT
);
"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(SCHEMA)
    return c


def save_history(raw_values, composite, confidence):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO sl_score "
            "(d, composite, fng, mvrv_z, hash_depth, price_ma, sth_mvrv, lth_sopr, nupl, confidence, raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                today,
                composite,
                raw_values.get("fng"),
                raw_values.get("mvrv_z"),
                raw_values.get("hash_depth"),
                raw_values.get("price_ma"),
                raw_values.get("sth_mvrv"),
                raw_values.get("lth_sopr"),
                raw_values.get("nupl"),
                confidence,
                json.dumps(raw_values, default=str),
            ),
        )


def print_history(n):
    if not DB_PATH.exists():
        print(f"no history yet at {DB_PATH}")
        return
    with _conn() as c:
        rows = c.execute(
            "SELECT d, composite, fng, mvrv_z, hash_depth, price_ma, sth_mvrv, lth_sopr, nupl, confidence "
            "FROM sl_score ORDER BY d DESC LIMIT ?", (n,)
        ).fetchall()
    if not rows:
        print("history table empty")
        return
    print(f"{'date':<12}{'score':>7}  {'fng':>4} {'mvrvZ':>6} {'hash%':>6} {'p/ma':>6} {'sthM':>5} {'lthS':>6} {'nupl':>6} {'conf':>5}")
    print("-" * 82)
    for r in rows:
        d, comp, fng, mvz, hd, pma, sm, ls, nu, cf = r
        fmt = lambda v, f="{:>6.2f}": (f.format(v) if isinstance(v, float) else (str(v) if v is not None else "—"))
        print(f"{d:<12}{comp:>7.1f}  {fng if fng is not None else '—':>4} "
              f"{fmt(mvz)} {fmt(hd, '{:>6.3f}')} "
              f"{fmt(pma, '{:>6.3f}')} {fmt(sm, '{:>5.2f}')} {fmt(ls, '{:>6.3f}')} {fmt(nu, '{:>6.3f}')} "
              f"{fmt(cf, '{:>5.2f}')}")


# --- main --------------------------------------------------------------------

WEIGHTS = {
    "Fear & Greed":   0.10,
    "MVRV Z-Score":   0.20,
    "Hash Ribbon":    0.10,
    "Price / MA200":  0.15,
    "STH-MVRV":       0.15,
    "LTH-SOPR":       0.20,
    "NUPL":           0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "weights must sum to 1.0"


def collect():
    fng_v   = fear_greed()
    mvz_v   = mvrv_zscore()
    hd_v    = hash_ribbon_depth()
    pma_v   = price_ma200_ratio()
    sth_v   = sth_mvrv()
    lth_v   = lth_sopr()
    nupl_v  = nupl()

    raw = {
        "fng": fng_v, "mvrv_z": mvz_v, "hash_depth": hd_v, "price_ma": pma_v,
        "sth_mvrv": sth_v, "lth_sopr": lth_v, "nupl": nupl_v,
    }
    rows = [
        ("Fear & Greed",   *_fng(fng_v),    WEIGHTS["Fear & Greed"]),
        ("MVRV Z-Score",   *_mvrv(mvz_v),   WEIGHTS["MVRV Z-Score"]),
        ("Hash Ribbon",    *_hr(hd_v),      WEIGHTS["Hash Ribbon"]),
        ("Price / MA200",  *_ma(pma_v),     WEIGHTS["Price / MA200"]),
        ("STH-MVRV",       *_sth(sth_v),    WEIGHTS["STH-MVRV"]),
        ("LTH-SOPR",       *_lth_s(lth_v),  WEIGHTS["LTH-SOPR"]),
        ("NUPL",           *_nupl_s(nupl_v),WEIGHTS["NUPL"]),
    ]
    weighted = sum(s * w for _, s, _, w in rows if s is not None)
    used = sum(w for _, s, _, w in rows if s is not None)
    composite = weighted / used if used else 0.0
    confidence = used  # fraction of total weight that had data (weights sum to 1)
    return rows, composite, raw, confidence


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--history":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print_history(n)
        return 0

    if "--selftest" in sys.argv:
        # offline sanity: interpolation monotonic + weights sum + zone coverage
        assert _interp(-1, [(-0.5, 100), (8, 5)]) == 100
        assert _interp(10, [(-0.5, 100), (8, 5)]) == 5
        assert abs(_interp(0.5, [(0, 0), (1, 100)]) - 50) < 1e-9  # midpoint
        assert _fng(5)[0] > _fng(95)[0]
        assert _sth(0.7)[0] > _sth(2)[0]
        assert _lth_s(0.9)[0] > _lth_s(3)[0]
        assert _nupl_s(0.1)[0] > _nupl_s(0.8)[0]
        assert _mvrv(-0.5)[0] > _mvrv(5)[0]
        assert _ma(0.6)[0] > _ma(1.5)[0]
        assert _hr(-0.15)[0] > _hr(0.15)[0]  # deep capitulation scores higher
        for s in (0, 19, 20, 34, 35, 49, 50, 64, 65, 79, 80, 89, 90, 100):
            assert interpret(s)[1]
        print("selftest OK")
        return 0

    rows, composite, raw, confidence = collect()
    success = sum(1 for _, s, _, _ in rows if s is not None)
    if success < 3:
        print(f"ERROR: only {success}/7 signals fetched, refusing to score", file=sys.stderr)
        return 2

    save_history(raw, composite, confidence)

    if "--summary" in sys.argv:
        print(summary(rows, composite, confidence))
        return 0

    print(f"\n{'BTC Bottom Composite Score (v2.1)':^66}")
    print("=" * 66)
    print(f"{'Metric':<18}{'Value':<14}{'Score':>10}{'Weight':>14}")
    print("-" * 66)
    for name, s, val, w in rows:
        s_str = f"{s:.1f}" if s is not None else "—"
        print(f"{name:<18}{val:<14}{s_str:>10}{w * 100:>13.0f}%")
    print("-" * 66)
    print(f"{'COMPOSITE':<48}{composite:>7.1f} / 100")
    print(f"{'CONFIDENCE':<48}{confidence*100:>7.0f} %")
    emoji, zone_en, zone_zh = interpret(composite)
    print(f"\n{emoji} {zone_en}（{zone_zh}）")
    print(f"\n💡 {observation(composite, rows, confidence)}\n")
    print("Zones:")
    for cut, name, _, zh in ZONES:
        print(f"  ≥{cut:<3} {name:<18} {zh}")
    print(f"\nAnchors: 抄底 {BOTTOM_ANCHOR} / 清倉 {TOP_ANCHOR}")
    print(f"History: {DB_PATH}\n")

    assert 0 <= composite <= 100
    return 0


if __name__ == "__main__":
    sys.exit(main())
