# favorite-songs-api

好きな曲・好きな理由・JOYSOUNDカラオケ採点記録を公開するJSON API。

専用サーバーは使わず、GitHubリポジトリに保存したJSONを
`raw.githubusercontent.com` 経由でそのまま配信する構成。

```text
ローカル環境 → JSON編集(edit_songs.py) → git commit → git push
  → GitHub → raw.githubusercontent.com → API利用者
```

## 公開URL

```text
https://raw.githubusercontent.com/USERNAME/favorite-songs-api/main/songs.json
```

※ `raw.githubusercontent.com` はCDNキャッシュがかかるため、
pushしてから反映まで数分のタイムラグが生じる場合があります。

## リポジトリ構成

```text
favorite-songs-api/
├── README.md
├── songs.json              # 公開データ本体
├── schema/
│   └── songs.schema.json   # JSON Schema (Draft 2020-12)
└── scripts/
    └── edit_songs.py       # 対話型編集CLI
```

## データ構造

```json
{
  "schema_version": "2.0.0",
  "updated_at": "2026-09-06T12:00:00+09:00",
  "songs": [
    {
      "id": "song-001",
      "title": "曲名",
      "artist": "アーティスト名",
      "reason": "好きな理由",
      "karaoke": [
        {
          "engine": "分析採点AI",
          "highest": {
            "score": 95.123,
            "details": {
              "pitch": 96.0,
              "stability": 88.5,
              "expression": 90.2,
              "long_tone": 85.0,
              "technique": 92.1
            }
          }
        }
      ]
    }
  ]
}
```

- `karaoke` は**使用した採点エンジンごとの記録の配列**。
  一度も採点していない曲は `karaoke: []`。
- 同一曲で複数エンジンを使った場合は、配列に複数件入る。
- `highest` は「最高点（総合点）を出した回」の記録。
  - `score`: その回の総合点（必須）
  - `details`: その回の詳細内訳（任意）。存在する場合は
    `pitch`（音程）/ `stability`（安定感）/ `expression`（抑揚）/
    `long_tone`（ロングトーン）/ `technique`（テクニック）の
    5項目すべてをキーとして持ち、値は数値または `null`（不明・未入力）。
- v1.0.0 にあった `lowest`（最低点）は廃止した。

詳細は `schema/songs.schema.json` を参照。

## 使い方（データ編集）

Raspberry Pi OS等のLinux環境を想定。

```bash
pip install jsonschema --break-system-packages
python3 scripts/edit_songs.py
```

メニューから「追加」「編集」「削除」を選択し、対話形式で入力する。
保存時に自動でJSON Schemaによるバリデーションを行い、
不正なデータ（範囲外の点数、未定義の採点エンジン名など）は保存されない。

保存が成功すると、続けて `git add` / `git commit` / `git push` を
実行するか確認される（任意）。git のリモート・認証設定は
このツールの範囲外なので、事前に `git push` が手動で通る状態に
しておく必要がある。add対象は `songs.json` のみに限定している。

## バージョニング

`schema_version` (semver) で管理する。

- パッチ: enumへのエンジン名追加など後方互換な調整
- マイナー: `history` フィールド追加など非破壊的な拡張
- メジャー: `karaoke` の構造自体を変える破壊的変更

## 今後の予定

- GUIからの直接編集（フォーム入力 → JSON Schema検証 → 保存）
- エンジンごとの採点履歴（複数回の`score`/`details`の時系列記録）の追加
