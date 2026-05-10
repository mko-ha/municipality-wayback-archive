# 全国自治体トップページ Wayback 週次アーカイブ

## 目的

`municipalities_archive_targets.csv` にある全国自治体トップページを、Wayback Machine の Save Page Now に定期投入します。


- Wayback側が重い場合、TIMEOUTや429が出ます。
- 429が出たら、その回は途中停止します。
- ログは `archive_log.csv` に追記されます。
- 次回開始位置は `state.json` に保存されます。
