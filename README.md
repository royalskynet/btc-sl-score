# BTC SL 抄底分數

7 訊號 on-chain composite score。一個 0–100 數字告訴你現在離 BTC 底部多近。

## TL;DR

```bash
python3 btc_bottom_score.py             # 全表 + 白話觀察
python3 btc_bottom_score.py --summary   # 3 段 TG 友善摘要
python3 btc_bottom_score.py --history 30
```

**分數方向**：越高 = 越接近底。**抄底錨點 85**、清倉錨點 20。

## 分區

| 分數 | 區段 | 動作 |
|---|---|---|
| 90–100 | DEEP CAPITULATION | 五年一遇，全倉 |
| 80–89  | CAPITULATION      | 抄底區，重倉 70% |
| 65–79  | BOTTOM FORMING    | 築底中，試倉 30% |
| 50–64  | MID               | 觀望 |
| 35–49  | ELEVATED          | 持倉不加 |
| 20–34  | EUPHORIA          | 減倉一半 |
| 0–19   | TOP               | 清倉 |

## 訊號池

| # | 訊號 | 來源 | 權重 |
|---|---|---|---|
| 1 | Fear & Greed | alternative.me | 0.10 |
| 2 | MVRV Z-Score | bitcoin-data.com | 0.20 |
| 3 | Hash Ribbon Capitulation | mempool.space | 0.10 |
| 4 | Price / MA200 | coingecko | 0.15 |
| 5 | STH-MVRV | bitcoin-data.com | 0.15 |
| 6 | LTH-SOPR | bitcoin-data.com | 0.20 |
| 7 | NUPL | bitcoin-data.com | 0.10 |

全免 auth。bitcoin-data.com 共用 hourly 限速（10 reqs/hr）→ 一次跑 4 個。日跑一次不會炸。

## 設計細節

見 `DESIGN.md`。

## 依賴

Python 3 stdlib only。無 pip install。
