# 全国自治体トップページ Wayback 週次アーカイブ

## 目的

`municipalities_archive_targets.csv` にある全国自治体トップページを、Wayback Machine の Save Page Now に定期投入します。

## 構成

```text
municipalities_archive_targets.csv
archive_wayback.py
state.json
.github/workflows/archive.yml
```

## 動き

GitHub Actions が毎時17分に起動します。

1回あたり12件を処理します。

```text
12件 × 24回 × 7日 = 2,016件/週
```

自治体数1,741件を週1以上で回せる設計です。

## GitHubでの作り方

1. GitHubで新規リポジトリを作成
2. Publicで作成
3. このZIPの中身を全部アップロード
4. `Actions` タブを開く
5. `Archive municipalities to Wayback` を選ぶ
6. `Run workflow` で手動テスト
7. 成功すれば、以後は毎時自動実行

## 注意

- GitHub Actions の cron はUTCです。
- 日本時間では毎時26分ではなく、UTC基準の毎時17分です。ただし毎時なので実質問題ありません。
- Wayback側が重い場合、TIMEOUTや429が出ます。
- 429が出たら、その回は途中停止します。
- ログは `archive_log.csv` に追記されます。
- 次回開始位置は `state.json` に保存されます。
