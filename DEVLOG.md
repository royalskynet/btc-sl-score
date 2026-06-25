# DEVLOG — BCI (Bottom Confidence Index)

> 舊稱「BTC 抄底分數」/「SL score」。v2.2 起正式命名為 **BCI — Bottom Confidence Index（抄底信心指數）**。Repo / 檔名暫不改，避免破壞外部連結。

> 這份文件的目的：讓一個完全沒有上下文的開發者（或新的 AI session）能獨立接手本專案，理解設計意圖、現狀、與待辦，而不需要追問原作者。
> 維護規則：每次有實質變動就在「變更紀錄」最上方加一條。不要刪舊紀錄。

---

## 1. 這個專案是什麼

`btc_bottom_score.py` 是一支單檔 Python 腳本，輸出一個 0–100 的「BTC 抄底分數」。分數越高代表越接近市場底部（越值得加倉），越低代表越接近頂部（越該減倉）。

它是個人用的市場狀態監測工具，不是交易機器人。它**不會自動下單**，只給人類一個量化的進出場參考。

核心理念：與其盯七個分散的指標，不如把它們聚合成一個帶語意分區的單一數字。

---

## 2. 怎麼跑

```bash
python3 btc_bottom_score.py            # 完整表格 + 文字判讀
python3 btc_bottom_score.py --summary  # 三段式精簡輸出（適合貼 Telegram）
python3 btc_bottom_score.py --history 30   # 印出最近 30 天歷史
python3 btc_bottom_score.py --selftest # 離線單元測試，不打 API，CI 可用
```

- 只用 Python 標準函式庫（`urllib`, `sqlite3`, `json`）。**無第三方依賴、無需 pip install。**
- 所有 API 都是免費、免金鑰的公開端點。
- 每次成功計分會把結果寫進 sqlite，路徑預設 `~/.btc-sl-score/history.db`，可用環境變數 `BTC_SL_DB` 覆蓋。

⚠️ **常見執行錯誤**：不要把程式碼貼進 PowerShell/終端機逐行執行。要先存成 `.py` 檔，再用 `python btc_bottom_score.py` 執行整個檔案。

---

## 3. 方法論：七個訊號

分數由七個訊號加權平均而成。四個偏總經/情緒，三個偏鏈上。

| 訊號 | 權重 | 資料來源 | 抓什麼 | 計分方向 |
|------|------|----------|--------|----------|
| Fear & Greed | 10% | alternative.me | 市場情緒指數 0–100 | 越恐懼 → 分數越高 |
| MVRV Z-Score | 20% | bitcoin-data.com | 市值/實現市值的標準分 | 越低/負 → 越高 |
| Hash Ribbon | 10% | mempool.space | 30D vs 60D 算力均線乖離 | 礦工投降越深 → 越高 |
| Price / MA200 | 15% | coingecko（備援 coincap） | 現價 / 200日均價 | 越低於均線 → 越高 |
| STH-MVRV | 15% | bitcoin-data.com | 短期持有者 MVRV | 越虧損 → 越高 |
| LTH-SOPR | 20% | bitcoin-data.com | 長期持有者花費產出獲利比 | 越接近割肉 → 越高 |
| NUPL | 10% | bitcoin-data.com | 淨未實現損益 | 越接近 capitulation → 越高 |

權重加總嚴格等於 1.0（程式啟動時有 assert 檢查）。

### 計分機制（v2.1 後）

每個訊號用一張「斷點 → 分數」對照表，做**分段線性插值**（`_interp`）把原始值映射到 0–100。
- 在斷點之間，分數線性內插，所以原始值的細微變化會平滑反映到分數上。
- 超出表格範圍時，clamp 到頭尾分數。

> 設計理由：v2.0 用的是階梯式 bucket，會把一整段原始值壓成同一個分數（例如 MVRV-Z 0.99 跟 1.4 都給 70），在錨點邊界附近失真。改插值後分數對「離錨點多遠」更敏感。

### 分數分區（ZONES）

| 分數 | 區名 | 含意 |
|------|------|------|
| ≥90 | DEEP CAPITULATION | 歷史級底部，全倉 |
| ≥80 | CAPITULATION | 抄底區 |
| ≥65 | BOTTOM FORMING | 築底中 |
| ≥50 | MID | 中性，觀望 |
| ≥35 | ELEVATED | 偏多倉，不加碼 |
| ≥20 | EUPHORIA | 過熱，減倉 |
| <20 | TOP | 頂部，清倉 |

### 錨點

- `BOTTOM_ANCHOR = 85`：分數要 ≥85 才視為真正進入重倉時機。80–85 是「快到了但還沒到」的試倉區。
- `TOP_ANCHOR = 20`：分數 ≤20 開始減倉防守。

> 這兩個是個人風險偏好參數，不是市場常數。調整它們等於調整你的進出場積極度。

---

## 4. 程式結構（單檔，由上而下）

1. **設定區** — UA、DB 路徑、錨點常數。
2. **`_get` / `_get_first`** — 帶重試與指數退避的 HTTP GET；`_get_first` 依序嘗試多個備援 URL。
3. **fetchers** — 每個訊號一個函式，回傳原始值或 `None`（失敗時）。
4. **`_interp` + 各 `_xxx` 計分函式** — 把原始值轉成 (分數, 顯示字串) 的 tuple。
5. **interpret / _label / observation** — 把分數轉成分區、人類語意標籤、與行動建議文字。
6. **summary** — 組三段式精簡輸出。
7. **history 區** — sqlite schema、寫入、讀取列印。
8. **WEIGHTS + collect** — 抓全部訊號、加權平均、算 confidence。
9. **main** — CLI 參數分派與表格輸出。

設計原則：**任何單一 API 掛掉都不該讓整個腳本崩潰。** fetcher 失敗回 `None`，計分函式遇 `None` 回 `(None, "N/A")`，加權時跳過缺值並按剩餘權重正規化。

---

## 5. 容錯與可信度

- `collect()` 只要有 ≥3/7 訊號成功就會計分；少於 3 個直接 `return 2` 拒絕計分（避免用太少資料下結論）。
- `confidence` = 成功訊號的權重總和（0–1）。低於 0.85 時，文字判讀會附註「可信度下降」。
- bitcoin-data.com 一家撐了 4 個訊號（MVRV-Z、STH-MVRV、LTH-SOPR、NUPL），是**最大單點風險**。v2.1 已為這四個各加一個備援 URL，但備援端點是否長期有效需持續驗證（見待辦）。

---

## 6. 資料庫 schema

```sql
CREATE TABLE IF NOT EXISTS sl_score (
  d TEXT PRIMARY KEY,          -- UTC 日期 YYYY-MM-DD
  composite REAL,
  fng INTEGER, mvrv_z REAL, hash_depth REAL, price_ma REAL,
  sth_mvrv REAL, lth_sopr REAL, nupl REAL,
  confidence REAL,
  raw_json TEXT
);
```

⚠️ **v2.0 → v2.1 schema 不相容**：欄位 `hash_cap`（布林）改為 `hash_depth`（浮點），並新增 `confidence`。
升級時舊 db 會在 INSERT 時報欄位錯誤。處理方式：升級前先刪除或改名舊 db。
```bash
rm ~/.btc-sl-score/history.db   # 歷史歸零；舊欄位定義已對不上，無保留價值
```

---

## 7. 變更紀錄（最新在上）

### v2.2
- 指標正式命名 **BCI — Bottom Confidence Index（抄底信心指數）**。
- 為避免「指數名稱 confidence」與「資料完整度 confidence」撞名，輸出端顯示改：
  - `COMPOSITE` → `BCI`
  - `CONFIDENCE` → `DATA COVERAGE`
- 變數名 / db 欄位名（`confidence`）保留不動 — 純命名收斂，零行為改動，schema 相容。

### v2.1
- 計分從階梯 bucket 改為分段線性插值（`_interp`）。
- Hash Ribbon 從布林（Yes/No → 90/30）改為連續的乖離強度評分（`hash_ribbon_depth` 回傳 (ma30-ma60)/ma60）。
- `_get` 加入重試 + 指數退避；新增 `_get_first` 支援來源級備援。
- bitcoin-data.com 四訊號各加一個備援 URL；Price/MA200 加 coincap 備援。
- 新增 `confidence` 指標並寫入 db、顯示於輸出與判讀。
- selftest 擴充：驗證插值中點、單調性、各訊號方向。
- db schema 變更（見第 6 節相容性警告）。

### v2.0（前一版基準）
- 七訊號加權架構，階梯式 bucket 計分。
- sqlite 歷史紀錄，三段式 summary 輸出。
- 錨點：抄底 85 / 清倉 20。

---

## 8. 待辦 / 已知問題（給接手者）

依優先序：

1. **驗證備援端點真的有效。** v2.1 為 bitcoin-data.com 加的備援 URL（`/v1/...` 不含 `/api`）是推測格式，需實際測試確認可用，否則只是假的安全感。同理 coincap 備援需確認回傳結構未變。
2. **bitcoin-data.com 集中風險仍在。** 即使有同站備援，整站掛掉仍廢 4/7。可考慮找第二家鏈上資料供應商（Messari 免費且免金鑰，可評估）做真正的跨來源備援。
3. **斷點表是手調的，未回測。** 各計分函式的斷點數值憑經驗設定，沒有用歷史資料回測過。理想做法：拉歷史數據，檢查分數在過去幾次真實底部/頂部是否落在預期分區。
4. **MA200 用簡單算術平均**，不是指數加權，也沒處理資料缺漏日。可接受但不嚴謹。
5. **沒有時區/快取保護**：同一 UTC 日多次執行會覆寫當天紀錄（PRIMARY KEY on date），這是刻意設計，但若想保留日內變化需改 schema。

---

## 9. 重要免責

這是個人決策輔助工具，輸出不是投資建議。分數可能滯後，訊號集體投降不代表不會再跌。任何倉位決策由使用者自負。
