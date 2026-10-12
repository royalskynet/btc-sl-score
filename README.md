# BCI — Bottom Confidence Index / 抄底信心指數

Single-file Python tool that turns seven market and on-chain signals into one
0–100 number: **higher means closer to a Bitcoin bottom.**

English below · [繁體中文](#zh-tw) below · 英文在前，[繁體中文](#zh-tw)在下半部

---

## Quick install

```bash
git clone https://github.com/royalskynet/btc-sl-score && cd btc-sl-score && python3 btc_bottom_score.py
```

No install step, no `pip install`, no API keys. Python 3 (standard library
only) and a network connection are the entire dependency list. The clone prints
the full signal table and your current score immediately.

For the Claude skill directory layout, clone straight into the skills folder
instead:

```bash
git clone https://github.com/royalskynet/btc-sl-score ~/.claude/skills/btc-sl-score
```

---

## What it is

BCI is a **market-condition monitor, not a trading bot**. It never places an
order and it never talks to an exchange. It answers exactly one question — *how
close is the market to a cycle bottom right now?* — and answers it with a single
number you can log over time.

The design premise is that watching seven scattered indicators is harder than
watching one aggregated number that still carries a semantic label. Each signal
is scored from 0 to 100, weighted, averaged into a composite, then mapped onto a
named zone (CAPITULATION, EUPHORIA, …) plus a plain-language reading.

Score direction: **higher = closer to the bottom.** The bottom anchor is **85**
(the point at which a heavy position is justified) and the top anchor is **20**
(the point at which you start trimming).

## Usage

```bash
python3 btc_bottom_score.py            # full table + plain-language reading
python3 btc_bottom_score.py --summary  # 3-line Telegram-friendly summary
python3 btc_bottom_score.py --history 30   # last 30 days from the local database
python3 btc_bottom_score.py --selftest # offline sanity check, makes no API calls
```

`--summary` prints one line per group of signals, which is the format to paste
into a chat or a note. `--selftest` verifies the interpolation math, the signal
directions and the zone boundaries without touching the network, so it is safe
for CI.

## Zones

| Score | Zone | Typical reading |
|---|---|---|
| 90–100 | DEEP CAPITULATION | Once-in-a-cycle bottom |
| 80–89 | CAPITULATION | Bottom zone, heavy position |
| 65–79 | BOTTOM FORMING | Still building a base, probe position |
| 50–64 | MID | Neutral, stand aside |
| 35–49 | ELEVATED | Bullish regime, do not add |
| 20–34 | EUPHORIA | Overheated, trim half |
| 0–19 | TOP | Cycle top, exit |

## Signal pool

| # | Signal | Source | Weight |
|---|---|---|---|
| 1 | Fear & Greed | alternative.me | 10% |
| 2 | MVRV Z-Score | bitcoin-data.com | 20% |
| 3 | Hash Ribbon capitulation | mempool.space | 10% |
| 4 | Price / MA200 | coingecko (fallback: coincap) | 15% |
| 5 | STH-MVRV | bitcoin-data.com | 15% |
| 6 | LTH-SOPR | bitcoin-data.com | 20% |
| 7 | NUPL | bitcoin-data.com | 10% |

The weights sum to exactly 1.0 (asserted at startup). Four macro/sentiment
signals and three on-chain signals. Every endpoint is public and free, with no
authentication.

**Rate limit:** the four on-chain signals all come from `bitcoin-data.com`,
which shares an hourly limit of 10 requests — one run spends 4 of them. Running
the tool once a day is comfortably within budget; running it in a tight loop is
not.

## Scoring

Each signal has a table of breakpoints mapping its raw value to a 0–100 score by
**piecewise-linear interpolation** (`_interp`), clamped to the end scores outside
the table range. Linear interpolation replaced the older step-bucket approach so
that the score stays sensitive to how far a reading sits from the anchor, instead
of flattening a whole range into one number.

If a source fails, its fetcher returns `None`, that signal drops out of the
weighted average, and the remaining weights are renormalized. Requests retry with
exponential backoff, and every on-chain signal has a secondary URL to fall back
to. Scoring is refused outright (exit code 2) if fewer than 3 of the 7 signals
came back, so a half-dead network can never produce a confident-looking number.

**DATA COVERAGE** in the output is the share of total weight that actually had
data. Below 85% the plain-language reading adds a caveat.

## History

Every successful run appends a row to a local SQLite database, one row per UTC
day (re-running the same day overwrites that row):

```bash
python3 btc_bottom_score.py --history 30
```

The database defaults to `~/.btc-sl-score/history.db` and can be relocated with
the `BTC_SL_DB` environment variable.

## Requirements

Python 3 standard library only — `urllib`, `sqlite3`, `json`. No third-party
packages, no `pip install`. Note that DB files written by v2.0 are not schema
compatible with v2.1+ (the `hash_cap` boolean became the `hash_depth` float and
`confidence` was added); delete or rename an old database when upgrading.

## Design notes

`DEVLOG.md` in this repository is the handover document: methodology,
tolerance/fallback behaviour, the SQLite schema, a change log and a list of open
problems for whoever picks this up next.

## Disclaimer

This is a personal decision-support tool. The output is not investment advice.
The score can lag, and signals capitulating together does not mean the market
cannot fall further. Every position decision is yours.

---

<a id="zh-tw"></a>

# BCI — 抄底信心指數（Bottom Confidence Index）

單一檔案的 Python 工具，把七個總經與鏈上訊號聚合成一個 0–100 的分數：
**分數越高，代表市場越接近底部。**

---

## 快速安裝

```bash
git clone https://github.com/royalskynet/btc-sl-score && cd btc-sl-score && python3 btc_bottom_score.py
```

不需要安裝步驟、不需要 `pip install`、不需要任何 API 金鑰。只要有 Python 3
（僅用標準函式庫）和網路連線就夠了。clone 完直接執行就會印出完整訊號表與
目前分數。

若要把它放進 Claude skill 的資料夾結構，直接 clone 到 skills 資料夾：

```bash
git clone https://github.com/royalskynet/btc-sl-score ~/.claude/skills/btc-sl-score
```

## 這是什麼

BCI 是**市場狀態監測工具，不是交易機器人**。它不會自動下單，也不會連任何
交易所。它只回答一個問題：*現在的市場離週期底部有多近？* 並且用一個你
可以每天記錄下來的數字回答。

設計前提是：盯七個分散的指標，比盯一個仍然帶著語意標籤的聚合數字更難。每個
訊號各自換算成 0–100 分數，加權平均成一個 composite，再對應到具名的分區
（CAPITULATION、EUPHORIA…）與一句白話判讀。

**分數方向**：越高 = 越接近底。**抄底錨點 85**（重倉時機的門檻）、
**清倉錨點 20**（開始減倉的門檻）。

## 使用方式

```bash
python3 btc_bottom_score.py            # 全表 + 白話觀察
python3 btc_bottom_score.py --summary  # 三段式 TG 友善摘要
python3 btc_bottom_score.py --history 30   # 印出最近 30 天歷史
python3 btc_bottom_score.py --selftest # 離線自我檢查，完全不打 API
```

`--summary` 會把七個訊號壓成三行，方便貼到聊天或筆記裡。`--selftest` 只驗證
插值數學、訊號方向與分區邊界，不會連網，所以可以安全地拿來跑 CI。

## 分區

| 分數 | 區段 | 動作 |
|---|---|---|
| 90–100 | DEEP CAPITULATION | 五年一遇，全倉 |
| 80–89 | CAPITULATION | 抄底區，重倉 70% |
| 65–79 | BOTTOM FORMING | 築底中，試倉 30% |
| 50–64 | MID | 觀望 |
| 35–49 | ELEVATED | 持倉不加 |
| 20–34 | EUPHORIA | 減倉一半 |
| 0–19 | TOP | 清倉 |

## 訊號池

| # | 訊號 | 來源 | 權重 |
|---|---|---|---|
| 1 | Fear & Greed | alternative.me | 10% |
| 2 | MVRV Z-Score | bitcoin-data.com | 20% |
| 3 | Hash Ribbon 投降 | mempool.space | 10% |
| 4 | Price / MA200 | coingecko（備援 coincap） | 15% |
| 5 | STH-MVRV | bitcoin-data.com | 15% |
| 6 | LTH-SOPR | bitcoin-data.com | 20% |
| 7 | NUPL | bitcoin-data.com | 10% |

權重加總嚴格等於 1.0（程式啟動時有 assert 檢查）。四個偏總經／情緒，三個偏
鏈上。所有端點都是免金鑰的公開 API。

**限速注意**：四個鏈上訊號都來自 `bitcoin-data.com`，該站共用每小時 10 次
的限速，單次執行會用掉其中 4 次。日跑一次完全安全；短時間狂跑就會超。

## 計分方式

每個訊號都有一張「斷點 → 分數」對照表，用**分段線性插值**（`_interp`）把原始
值映射到 0–100，超出表範圍則 clamp 到頭尾分數。線性插值取代了舊版的階梯式
bucket，這樣分數才會持續反映「離錨點多遠」，而不是把一整段原始值壓成同一個
數字。

某個來源掛掉時，fetcher 會回傳 `None`，該訊號退出加權平均，剩餘權重自動重新
正規化。請求會帶指數退避重試，每個鏈上訊號也都有備援網址。若 7 個訊號成功
的少於 3 個，程式會直接拒絕計分（exit code 2），避免用太少資料講出很有自信的
結論。

輸出中的 **DATA COVERAGE** 是「實際拿到資料的權重佔比」，低於 85% 時，白話
判讀會附上資料不完整的註記。

## 歷史紀錄

每次成功計分都會寫一列進本機 SQLite，一個 UTC 日一列（同一日重跑會覆寫當天
那列）：

```bash
python3 btc_bottom_score.py --history 30
```

預設路徑是 `~/.btc-sl-score/history.db`，可以用環境變數 `BTC_SL_DB` 改到別
處。

## 依賴

只用 Python 3 標準函式庫——`urllib`、`sqlite3`、`json`。沒有第三方套件、不用
`pip install`。另外 v2.0 寫出的資料庫與 v2.1+ 的 schema 不相容（布林欄位
`hash_cap` 改成浮點的 `hash_depth`，並新增 `confidence`），升級前請先刪除或
改名舊的資料庫。

## 設計細節

本 repo 的 `DEVLOG.md` 是交接文件：方法論、容錯與備援行為、SQLite schema、
變更紀錄，以及留給接手者的待辦與已知問題。

## 免責聲明

這是個人決策輔助工具，輸出不是投資建議。分數可能滯後，訊號集體投降也不代表
不會再跌。任何倉位決策都由使用者自負。