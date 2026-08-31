# CRC Market Monitor 公開部署驗證

## 2026-08-31

- GitHub Pages 已由 `main/docs` 成功建置，公開網址為 `https://matt-manus.github.io/crc-market-monitor/`。
- 網頁能正確載入 Massive 的首次真實輸出：截至 2026-08-28、分析股票 2,459 隻、MLI 成員 499 隻。
- 摘要卡和每日監察表已反映 `latest.json` 真實值。
- 已從第一次 Bootstrap 抓取的日線重建 73 個真實交易日摘要；每日表展示最近 20 天，4% 脈搏柱狀圖和領導股趨勢圖已繪製真實歷史序列。
- 趨勢圖在較早區段呈現 0% 是資料窗口限制的真實結果：63-session 動量條件尚未有足夠前期日線，並非以示範點位填補。

## 2026-08-31 — 資料口徑與圖表修正

價格與成交量讀數由 Massive 日線彙總提供。初版誤以「非 ETF」黑名單處理 reference ticker types，因而保留了 ETV／ETS 等交易所買賣產品；改為只允許 Massive 類型 `CS`（普通股）及 `ADRC`（ADR 普通股）後，2026-08-28 的股票池由 2,459 修正為 2,386，Up 4%／Down 4% 修正為 47／350，與使用者提供的同日期參考讀數一致。

公開頁的 4% 脈搏圖已改為綠柱由零線向上、紅柱由零線向下，並顯示 800、+300、0、−300、800 縱軸與 ±300 虛線。行業表現已從單一 Unclassified 改為 17 個真實分類；分類來源是 Nasdaq screener 的 `industry` 和 `sector` 欄位，經明示的 CRC 顯示映射，而非宣稱為 SEC SIC 完整分類。

官方資料參考：Massive Ticker Overview 說明 `type`、`sic_code` 與 `sic_description` 欄位：https://massive.com/docs/rest/stocks/tickers/ticker-overview 。SEC SIC Code List：https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list 。

## 最終比對（2026-08-28）

改用 Massive `CS` + `ADRC` 類型後，股票總數 2,386、Up 4% 47、Down 4% 350、20 日線 44.2%、SPY ATR +2.70、QQQ ATR +0.81 已和使用者提供的同日期表一致。50 日線為 52.1%（參考 52.2%），屬 0.1 個百分點的四捨五入／分母差異。

動力股仍有可觀測的差別：目前 489 隻、−0.62%、44.6%，而參考為 492 隻、−0.53%、44.9%。這不是以示範數據取代；目前版本按 Massive 調整後日線、63 個實際交易日距離和可用成交額欄位計算。要作逐隻精確對賬，仍須確定參考頁對成交額（VWAP 或收市價 × 成交量）、ADR 的公司行動調整及歷史回補日界的具體版本。
- 行業資料仍未接入 SIC 對照表，真實輸出暫列為 `Unclassified`。
