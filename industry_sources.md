# CRC 行業組成資料來源與界線

價格、成交量、均線、ATR 和動力股計算使用 Massive 的日線資料。行業組成則需要公司分類資料，並不是日線彙總端點的一部分。

本版本使用 Nasdaq 公開 screener 的 `industry` 與 `sector` 欄位，將其映射到 CRC 的精簡展示分類。這讓每個分類都有實際供應商回傳的公司行業標籤作來源，但它不是 SEC SIC 的逐碼重分類，也不應標示為 SEC SIC。

Massive 的逐代號 Ticker Overview 官方文件列出 `sic_code` 與 `sic_description` 欄位；日後如帳戶限額和更新時間允許，可將映射升級為其逐代號 SIC 資料或 SEC EDGAR 的公司申報資料。[Massive Ticker Overview](https://massive.com/docs/rest/stocks/tickers/ticker-overview)；[SEC SIC Code List](https://www.sec.gov/search-filings/standard-industrial-classification-sic-code-list)。

## 2026-08-31 SIC 資料可用性核對

SEC 的官方逐公司 submissions 端點已實測返回 `sic` 和 `sicDescription`；例如 Apple 的 CIK `0000320193` 返回 SIC `3571`、`Electronic Computers`。目前 Massive 批次 ticker reference 回應未包含 SIC 欄位，而 Massive Ticker Overview 的 SIC 欄位需逐代號取得。由於 SEC 對自動化擷取有公平存取要求，批次分類程序必須使用清楚的聯絡識別與受限速率，並作本地快取；在完成前，公開頁面不顯示未校驗的行業排行。

## CRC SIC taxonomy v1

CRC SIC taxonomy v1 是固定、可版本控制的研究用對照表，檔案位置為 `config/crc-sic-taxonomy-v1.json`。本輪使用 SEC `company_tickers.json` 對照 2,272 隻合資格分析股票，其中 2,271 隻配對到 CIK；SEC submissions 快取成功取得 2,251 隻的 SIC。缺少 CIK、缺少 SIC 或不落入已列範圍者顯示為 `Unclassified`，不使用名稱關鍵字猜測。
