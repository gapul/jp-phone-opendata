# jp-phone-opendata

日本のオープンデータ（総務省「電気通信番号指定状況」）から電話番号の照会APIを作り、
FOSSのAndroid迷惑電話対策アプリ **[SpamBlocker](https://github.com/aj3423/SpamBlocker)**
に着信時の発信者情報として表示させるプロジェクト。電話帳ナビのような「かかってきた
番号が誰か」の体験を、外部の評判DBに依存せず、自前のオープンデータと自分のインフラ
だけで再現することを狙う。

## 仕組み

```
GitHub Actions (月次)
  └ scripts/generate.py  総務省Excelを取得 → prefix→事業者に整形
        → data/prefixes.json / data/import.sql
  └ wrangler             D1にデータ投入 + Worker をデプロイ

Cloudflare Worker  GET /lookup?number=...  → JSON
  { number, type, verdict, carrier, region, name, label }

Android: SpamBlocker  着信 → Worker を Query API で照会 → キャリア/事業者名を表示
```

- **verdict**: 割当が判明する番号は `legit`、不明は `unknown`。`spam` は将来の
  クラウドソース迷惑リスト用に予約。
- **carrier**: 総務省の割当事業者（例: 090/080/070 携帯、050 IP電話）。
- 番号帯からの種別判定（フリーダイヤル/ナビダイヤル/国際/固定）はデータ不要でWorker側が実施。

## できること / できないこと

| 項目 | 状況 |
| --- | --- |
| 種別判定（携帯/IP/固定/フリーダイヤル/ナビ/国際） | ✅ Worker側で判定 |
| キャリア判定（携帯・IP） | ✅ 総務省データ |
| 固定電話の地域（市外局番→地域） | ⬜ TODO（固定局番ファイルの取り込み） |
| 事業者名（会社名） | ⬜ TODO（推奨データセット/Wikidata） |
| 迷惑・詐欺判定 | ⬜ TODO（公開情報には無い。自前通報が必要） |

MNP（番号ポータビリティ）により、割当事業者と実際の契約キャリアは一致しないことがある。

## セットアップ

### データ生成（ローカル確認）

```bash
pip install openpyxl
python scripts/generate.py        # data/ に prefixes.json / import.sql を出力
```

### Cloudflare（初回のみ手動）

```bash
cd worker
npm install
npx wrangler d1 create jp-phone           # 出力の database_id を wrangler.toml に貼る
npx wrangler d1 execute jp-phone --remote --file=schema.sql
npx wrangler d1 execute jp-phone --remote --file=../data/import.sql
npx wrangler deploy                       # https://jp-phone-opendata.<sub>.workers.dev
```

動作確認:

```bash
curl "https://jp-phone-opendata.<sub>.workers.dev/lookup?number=09012345678"
# {"number":"09012345678","type":"mobile","verdict":"legit","carrier":"...","label":"携帯 / ..."}
```

### Android（SpamBlocker）

1. `spamblocker/query_api.json` の URL を自分の Worker に書き換える。
2. SpamBlocker → Query API → New → Import で読み込む。
3. 着信時に Worker へ照会され、キャリア/事業者名が表示される。

### 自動更新（GitHub Actions）

リポジトリ Secrets に `CLOUDFLARE_API_TOKEN` と `CLOUDFLARE_ACCOUNT_ID` を設定すると、
`.github/workflows/update.yml` が月次で総務省データを再生成し、D1投入とWorkerデプロイまで自動化する。

## データ出典

総務省「電気通信番号指定状況」
<https://www.soumu.go.jp/main_sosiki/joho_tsusin/top/tel_number/number_shitei.html>

## License

MIT（コード）。データは総務省オープンデータ由来（出典表示のこと）。
