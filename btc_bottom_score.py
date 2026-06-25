#!/usr/bin/env python3
"""BTC bottom composite score 0-100. Higher = closer to bottom.

7-signal composite (4 macro + 3 on-chain).
Free APIs only, no auth. Stores daily history to sqlite.

  python3 btc_bottom_score.py            # full table + observation
  python3 btc_bottom_score.py --summary  # 3-section TG-friendly summary
  python3 btc_bottom_score.py --history 30
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = {"User-Agent": "btc-bottom-score/2.0"}

DB_PATH = Path(
    os.environ.get(
        "BTC_SL_DB",
        str(Path.home() / ".openalice" / "data" / "cache" / "btc_sl_history.db"),
    )
)

BOTTOM_ANCHOR = 85  # 抄底錨點
TOP_ANCHOR = 20     # 清倉錨點


def _get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


# --- fetchers ----------------------------------------------------------------

def fear_greed():
    try:
        d = _get("https://api.alternative.me/fng/?limit=1")
        return int(d["data"][0]["value"])
    except Exception:
        return None


def mvrv_zscore():
    # ponytail: bitcoin-data.com free endpoint, no auth, undocumented but stable
    try:
        d = _get("https://bitcoin-data.com/api/v1/mvrv-zscore/last")
        for k in ("mvrvZscore", "value", "mvrv_zscore"):
            if k in d:
                return float(d[k])
    except Exception:
        pass
    return None


def hash_ribbon_capitulation():
    """True when 30D hashrate MA < 60D MA → miner capitulation phase."""
    try:
        d = _get("https://mempool.space/api/v1/mining/hashrate/3y")
        rates = [x["avgHashrate"] for x in d["hashrates"]][-180:]
        if len(rates) < 60:
            return None
        ma30 = sum(rates[-30:]) / 30
        ma60 = sum(rates[-60:]) / 60
        return ma30 < ma60
    except Exception:
        return None


def price_ma200_ratio():
    try:
        d = _get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            "?vs_currency=usd&days=200&interval=daily"
        )
        closes = [p[1] for p in d["prices"]]
        return closes[-1] / (sum(closes) / len(closes))
    except Exception:
        return None


def sth_mvrv():
    try:
        return float(_get("https://bitcoin-data.com/api/v1/sth-mvrv/last")["sthMvrv"])
    except Exception:
        return None


def lth_sopr():
    try:
        return float(_get("https://bitcoin-data.com/api/v1/lth-sopr/last")["lthSopr"])
    except Exception:
        return None


def nupl():
    try:
        return float(_get("https://bitcoin-data.com/api/v1/nupl/last")["nupl"])
    except Exception:
        return None


# --- scoring (0-100; higher = closer to bottom) ------------------------------

def _bucket(v, table):
    return next(s for cut, s in table if v < cut)


def _fng(v):
    if v is None: return None, "N/A"
    return max(0, min(100, 100 - v)), f"{v}"

def _mvrv(z):
    if z is None: return None, "N/A"
    return _bucket(z, [(-0.5, 100), (0, 90), (1, 70), (2.5, 40), (5, 20), (99, 5)]), f"{z:.2f}"

def _hr(cap):
    if cap is None: return None, "N/A"
    return (90 if cap else 30), ("Yes" if cap else "No")

def _ma(r):
    if r is None: return None, "N/A"
    return _bucket(r, [(0.7, 100), (0.85, 85), (1.0, 65), (1.2, 45), (1.5, 25), (99, 10)]), f"{r:.3f}"

def _sth(v):
    if v is None: return None, "N/A"
    return _bucket(v, [(0.70, 100), (0.85, 90), (1.0, 70), (1.2, 50), (1.5, 30), (99, 15)]), f"{v:.2f}"

def _lth_s(v):
    if v is None: return None, "N/A"
    return _bucket(v, [(0.95, 100), (1.0, 92), (1.1, 70), (1.5, 50), (2.5, 30), (99, 15)]), f"{v:.3f}"

def _nupl_s(v):
    if v is None: return None, "N/A"
    return _bucket(v, [(0.0, 100), (0.25, 88), (0.5, 60), (0.65, 40), (0.75, 25), (99, 10)]), f"{v:.3f}"


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
    if s is None: return f"{name} 無資料"
    if name == "Fear & Greed":
        v = int(val)
        mood = "極度恐懼" if v <= 25 else "恐懼" if v <= 45 else "中性" if v <= 55 else "貪婪" if v <= 75 else "極度貪婪"
        return f"情緒{mood} {val}"
    if name == "MVRV Z-Score":
        return f"MVRV {'低估' if float(val) < 1 else '偏低' if float(val) < 2.5 else '高估'} {val}"
    if name == "Hash Ribbon":
        return f"礦工{'投降' if val == 'Yes' else '正常'} {val}"
    if name == "Price / MA200":
        r = float(val); pct = (r - 1) * 100
        return f"價格{'低於' if r < 1 else '高於'} 200MA {abs(pct):.0f}%"
    if name == "STH-MVRV":
        return f"短期持有者{'投降' if float(val) < 0.85 else '帳面虧損' if float(val) < 1 else '獲利中'} {val}"
    if name == "LTH-SOPR":
        return f"老錢{'割肉' if float(val) < 1 else '賺著賣' if float(val) < 1.5 else '派發'} {val}"
    if name == "NUPL":
        v = float(val)
        z = "capitulation" if v < 0.25 else "hope" if v < 0.5 else "optimism" if v < 0.65 else "belief" if v < 0.75 else "euphoria"
        return f"NUPL 進 {z} {val}"
    return f"{name} {val}"


def observation(score, rows):
    capitulation = sum(1 for _, s, _, _ in rows if s is not None and s >= 80)
    if score >= 90:
        return f"七訊號中 {capitulation} 個在抄底區；五年一遇等級。全倉。"
    if score >= 85:
        return f"七訊號中 {capitulation} 個在抄底區；高出抄底錨點 {BOTTOM_ANCHOR} 分 {score-BOTTOM_ANCHOR:.1f} → 重倉時機。"
    if score >= 70:
        return f"{capitulation}/7 訊號投降；距抄底錨點 {BOTTOM_ANCHOR} 還差 {BOTTOM_ANCHOR-score:.1f} 分 → 試倉、等最後一插針。"
    if score >= 50:
        return "中性區，鏈上訊號未集體投降。觀望。"
    if score >= 35:
        return "偏多倉時期；持倉不加碼。"
    if score >= 20:
        return f"過熱區，距清倉錨點 {TOP_ANCHOR} 還差 {score-TOP_ANCHOR:.1f} 分 → 減倉防守。"
    return "歷史級頂部。清倉。"


# --- output ------------------------------------------------------------------

def summary(rows, composite):
    emoji, zone_en, zone_zh = interpret(composite)
    labels = [_label(name, val, s) for name, s, val, _ in rows]
    # split labels into 2-3 visually balanced lines
    line1 = " / ".join(labels[:3])
    line2 = " / ".join(labels[3:5])
    line3 = " / ".join(labels[5:])
    return (
        f"🪙 BTC 抄底分數：{composite:.1f}/100 → {emoji} {zone_en}（{zone_zh}）\n"
        f"📊 {line1}\n"
        f"    {line2}\n"
        f"    {line3}\n"
        f"💡 {observation(composite, rows)}"
    )


# --- history -----------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS sl_score (
  d TEXT PRIMARY KEY,
  composite REAL,
  fng INTEGER, mvrv_z REAL, hash_cap INTEGER, price_ma REAL,
  sth_mvrv REAL, lth_sopr REAL, nupl REAL,
  raw_json TEXT
);
"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(SCHEMA)
    return c


def save_history(raw_values, composite):
    """raw_values: dict name → raw float/int/bool/None"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO sl_score "
            "(d, composite, fng, mvrv_z, hash_cap, price_ma, sth_mvrv, lth_sopr, nupl, raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                today,
                composite,
                raw_values.get("fng"),
                raw_values.get("mvrv_z"),
                1 if raw_values.get("hash_cap") else (0 if raw_values.get("hash_cap") is False else None),
                raw_values.get("price_ma"),
                raw_values.get("sth_mvrv"),
                raw_values.get("lth_sopr"),
                raw_values.get("nupl"),
                json.dumps(raw_values, default=str),
            ),
        )


def print_history(n):
    if not DB_PATH.exists():
        print(f"no history yet at {DB_PATH}")
        return
    with _conn() as c:
        rows = c.execute(
            "SELECT d, composite, fng, mvrv_z, hash_cap, price_ma, sth_mvrv, lth_sopr, nupl "
            "FROM sl_score ORDER BY d DESC LIMIT ?", (n,)
        ).fetchall()
    if not rows:
        print("history table empty")
        return
    print(f"{'date':<12}{'score':>7}  {'fng':>4} {'mvrvZ':>6} {'hash':>5} {'p/ma':>6} {'sthM':>5} {'lthS':>6} {'nupl':>6}")
    print("-" * 72)
    for r in rows:
        d, comp, fng, mvz, hc, pma, sm, ls, nu = r
        fmt = lambda v, f="{:>6.2f}": (f.format(v) if isinstance(v, float) else (str(v) if v is not None else "—"))
        print(f"{d:<12}{comp:>7.1f}  {fng if fng is not None else '—':>4} "
              f"{fmt(mvz)} {('Y' if hc==1 else 'N' if hc==0 else '—'):>5} "
              f"{fmt(pma, '{:>6.3f}')} {fmt(sm, '{:>5.2f}')} {fmt(ls, '{:>6.3f}')} {fmt(nu, '{:>6.3f}')}")


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
    hc_v    = hash_ribbon_capitulation()
    pma_v   = price_ma200_ratio()
    sth_v   = sth_mvrv()
    lth_v   = lth_sopr()
    nupl_v  = nupl()

    raw = {
        "fng": fng_v, "mvrv_z": mvz_v, "hash_cap": hc_v, "price_ma": pma_v,
        "sth_mvrv": sth_v, "lth_sopr": lth_v, "nupl": nupl_v,
    }
    rows = [
        ("Fear & Greed",   *_fng(fng_v),    WEIGHTS["Fear & Greed"]),
        ("MVRV Z-Score",   *_mvrv(mvz_v),   WEIGHTS["MVRV Z-Score"]),
        ("Hash Ribbon",    *_hr(hc_v),      WEIGHTS["Hash Ribbon"]),
        ("Price / MA200",  *_ma(pma_v),     WEIGHTS["Price / MA200"]),
        ("STH-MVRV",       *_sth(sth_v),    WEIGHTS["STH-MVRV"]),
        ("LTH-SOPR",       *_lth_s(lth_v),  WEIGHTS["LTH-SOPR"]),
        ("NUPL",           *_nupl_s(nupl_v),WEIGHTS["NUPL"]),
    ]
    weighted = sum(s * w for _, s, _, w in rows if s is not None)
    used = sum(w for _, s, _, w in rows if s is not None)
    composite = weighted / used if used else 0.0
    return rows, composite, raw


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--history":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print_history(n)
        return 0

    if "--selftest" in sys.argv:
        # offline sanity: scoring tables monotonic + weights sum + zone coverage
        assert _bucket(-1, [(-0.5, 100), (99, 5)]) == 100
        assert _fng(5)[0] > _fng(95)[0]
        assert _sth(0.7)[0] > _sth(2)[0]
        assert _lth_s(0.9)[0] > _lth_s(3)[0]
        assert _nupl_s(0.1)[0] > _nupl_s(0.8)[0]
        for s in (0, 19, 20, 34, 35, 49, 50, 64, 65, 79, 80, 89, 90, 100):
            assert interpret(s)[1]  # non-empty zone
        print("selftest OK")
        return 0

    rows, composite, raw = collect()
    success = sum(1 for _, s, _, _ in rows if s is not None)
    # ponytail: 3/7 floor; bitcoin-data.com shares rate limit across 4 endpoints
    # so worst-case partial run is fng + hash + p/ma surviving
    if success < 3:
        print(f"ERROR: only {success}/7 signals fetched, refusing to score", file=sys.stderr)
        return 2

    save_history(raw, composite)

    if "--summary" in sys.argv:
        print(summary(rows, composite))
        return 0

    print(f"\n{'BTC Bottom Composite Score (v2)':^64}")
    print("=" * 64)
    print(f"{'Metric':<18}{'Value':<14}{'Score':>10}{'Weight':>14}")
    print("-" * 64)
    for name, s, val, w in rows:
        s_str = f"{s:.0f}" if s is not None else "—"
        print(f"{name:<18}{val:<14}{s_str:>10}{w * 100:>13.0f}%")
    print("-" * 64)
    print(f"{'COMPOSITE':<48}{composite:>7.1f} / 100")
    emoji, zone_en, zone_zh = interpret(composite)
    print(f"\n{emoji} {zone_en}（{zone_zh}）")
    print(f"\n💡 {observation(composite, rows)}\n")
    print("Zones:")
    for cut, name, _, zh in ZONES:
        print(f"  ≥{cut:<3} {name:<18} {zh}")
    print(f"\nAnchors: 抄底 {BOTTOM_ANCHOR} / 清倉 {TOP_ANCHOR}")
    print(f"History: {DB_PATH}\n")

    assert 0 <= composite <= 100
    return 0


if __name__ == "__main__":
    sys.exit(main())
