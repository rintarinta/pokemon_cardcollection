# ポケかんり（ポケカ コレクション管理ツール）

個人のポケモンカードを、セット単位で「持ってる／持ってない」を塗り分けて管理する図鑑コンプ型ツール。

- カードデータ：[TCGdex API](https://tcgdex.dev/)（日本語・無料・APIキー不要）を都度参照
- 所有データ：ブラウザ内に保存（localStorage）。ログイン不要・費用ゼロ
- バックアップ／端末移動：JSONの書き出し・読み込み

## フォルダ構成

```
pokecard-manager/
├── index.html        アプリ本体（アプリのロジックはこれ1ファイル）
├── README.md         このファイル
├── data/
│   ├── index.json        補完データのあるセット一覧（セットID → 枚数）
│   ├── rarities.json     レア度インデックス（セットID → レア度 → 番号一覧）。セット一覧のレア度フィルタと集計が参照
│   ├── extra_sets.json   TCGdexのセット一覧に未登場の発売直後セット。アプリが一覧に追加表示する
│   └── sets/<セットID>.json  カード／画像／レア度の補完データ（80セット・7,608枚）
├── tools/
│   ├── fetch_cardrush.py 上記データの生成スクリプト（cardrush.media由来）
│   ├── fetch_official.py 発売直後セットの生成スクリプト（公式サイト＋pokecahack＋Bulbapedia由来）
│   └── fetch_images.py   画像だけ欠けているセットの画像補完スクリプト（pokecahack由来）
└── docs/
    └── 要件定義書_ポケモンカード管理ツール.html   要件定義書（Ver.0.2）
```

## カードデータの補完（data/）

TCGdexは日本語の旧弾（SM期・剣盾S期・XY期など）でカードが1枚も登録されていないセットが多く、
そのままでは図鑑ビューが空になる。そこで [cardrush.media](https://cardrush.media/) の公開APIから
番号・カード名・レア度・画像を取得し、`data/sets/<セットID>.json` として同梱している。
アプリは開いたセットの分だけ遅延ロードし、TCGdexのカードに継ぎ足して表示する。

- 対象は基本「TCGdexにカードが0枚のセット」。例外的に、カードはあるがレア度が未整備のセット（SV7 ステラミラクル等）もレア度補完用に同梱している。TCGdexにデータがあるカードは一切上書きしない
- 同じ番号にTCGdex・手動登録・同梱データが揃った場合の優先度は **TCGdex > 手動登録 > 同梱**
- 画像は `files.cardrush.media` への直リンク。先方のURL構成が変わると画像だけ表示されなくなる
- cardrushのAPIはCORSを許可していないため、ブラウザから直接は叩けない（事前生成が必要）

再生成・セット追加:

```bash
python tools/fetch_cardrush.py            # 補完できる/できないセットを一覧表示
python tools/fetch_cardrush.py SM8b       # 指定セットだけ生成
python tools/fetch_cardrush.py --all      # TCGdexが空のセットを全部生成
python tools/fetch_cardrush.py --rarities # data/rarities.json だけ再生成
```

`rarities.json` は同梱データのレア度と、TCGdexにあるレア度（メガ弾・SV11B等）を統合した事前集計。
セット生成時に自動更新されるが、TCGdex側にレア度が追記されたときは `--rarities` で単独更新できる。

### 発売直後の新弾（TCGdexにもcardrushにも無いセット）

TCGdexのセット一覧に未登場の新弾は、公式カード検索（名前・レア度）＋pokecahack（画像・シークレット枠）＋
Bulbapedia（シークレットの同名対応）＋tcgpro（残った穴の穴埋め・任意）から生成し、
`data/extra_sets.json` に登録して一覧に追加表示する。

```bash
# 例: M6 ストームエメラルダ（955は公式カード検索の商品絞り込みID）
python tools/fetch_official.py M6 955 m6 ストームエメラルダ "https://bulbapedia.bulbagarden.net/wiki/Storm_Emeralda_(TCG)"

# 例: M6a 30th CELEBRATION
#   - 1つの弾が複数の商品に分かれている場合はpgをカンマ区切り
#   - 第6引数にtcgproの収録カードリストURLを渡すと、他の3ソースで埋まらなかった穴だけを補う
python tools/fetch_official.py M6a 961,962 m6a "30th CELEBRATION" \
  "https://bulbapedia.bulbagarden.net/wiki/30th_Celebration_(TCG)" \
  "https://tcgpro.co.jp/media/pokeka-30th-atari/30th-card-list/"
```

公式カード検索はC/U/Rにレア度アイコンを出さない弾があり（M6aはexのRRのみ）、通常枠のレア度は
TCGdexにセットが入ってから `--rarities` で埋まる。ただしアプリのレア度フィルタが見るのは
AR/SR/SAR/UR/MUR/CHRだけなので、C/U/Rが空でも実害は無い。

tcgproは公式サイト未掲載のカードも番号・名前・レア度・画像を載せているので、
公式の公開が追いついていない枠を埋められる（M6aでは名前1件・レア度6件・画像4件。
AR 20枠とSAR 10枠がこれで揃った）。**既存の値は上書きせず、空のところだけ**を埋める。

画像URLはホストが混ざるため、このスクリプトが書き出すJSONの `img` は `https://{id}` 固定で、
各行にはホスト付きのパス（`pokecahack.com/...` / `tcgpro.co.jp/...`）を入れる。

TCGdexにセットが入ったらアプリは自動でそちらを優先する。`extra_sets.json` から該当行を消せば一覧の重複も防げる
（消し忘れてもTCGdex側にあるセットは追加表示しない）。

cardrushにも無いため補完できないセットが23件ある（XY期の大半、ADV期、L期）。

### 画像だけが無いセット（メガ弾など）

TCGdexにはカード・名前・レア度が入っているのに画像が1枚も無いセットがある（メガ弾のM1S〜M5、
旧弾のneo期・PCG期・PMCG期、SV11B/SV11Wなど42セット）。これは pokecahack.com の
収録リストから **画像だけ** を取って `data/sets/<セットID>.json` に入れる。

```bash
python tools/fetch_images.py          # 画像が無いセットと補完可否を一覧表示
python tools/fetch_images.py M2a      # 指定セット（スラッグは既定でセットIDの小文字）
python tools/fetch_images.py M2a m2a  # pokecahackのスラッグを明示指定
python tools/fetch_images.py --all    # スクリプト内の SLUGS 対応表を全部生成
```

レア度列は空で書き出す（表示レア度はTCGdex由来の `rarities.json` が使われるため、
ここで推測を混ぜると精度が落ちる）。名前はファイル単体で中身が読めるようにTCGdexから入れているが、
アプリはTCGdexの名前を優先するので表示には影響しない。

対応済み: **メガ弾7セット（M1S・M1L・M2・M2a・M3・M4・M5／905枚中904枚）**。
未対応セットは `SLUGS` にpokecahackのスラッグを追記すれば同じ手順で足せる
（M-P メガプロモ・MC スタートデッキ100は先方に収録リストが無く不可）。

## 使い方

### すぐ試す（ローカル）
`index.html` をブラウザにドラッグ＆ドロップ、またはダブルクリックで開く。
ただし `file://` で開くと `data/` の補完データを読めない（fetchがブロックされる）ため、
旧弾のカードを確認したい場合は簡易サーバー経由で開く: `python -m http.server` → http://localhost:8000/

### 人に配布して実運用する（推奨：URL公開）
無料の静的ホスティングに `index.html` を置き、URLを渡すだけ。相手はリンクを開くだけで使える（スマホ可）。

- GitHub Pages / Netlify / Cloudflare Pages などにアップロード
- 使う人ごとにデータは各自のブラウザに独立保存される（他者と混ざらない）

## 操作

| 操作 | 動作 |
|---|---|
| セットを選ぶ | 図鑑ビュー（カード一覧）を開く |
| カードをタップ／クリック | 所有↔未所有をトグル（所有＝カラー＋✓、未所有＝グレー） |
| カードを長押し／右クリック | カード詳細（レアリティ等）を表示 |
| 絞り込みチップ | すべて／所有のみ／未所有のみ を切替 |
| ヘッダー「書出」 | 所有データをJSONでバックアップ |
| ヘッダー「読込」 | JSONを読み込み（統合 or 上書きを選択） |

## 現在の実装状況（Phase 1）

- [x] セット一覧＋セット別コンプ率
- [x] 図鑑ビュー（画像・番号・所有トグル）
- [x] 所有データのローカル保存
- [x] 絞り込み（すべて／所有／未所有）
- [x] カード詳細モーダル（レアリティ表示）
- [x] JSONエクスポート／インポート
- [ ] カード名の横断検索（Phase 2）
- [ ] コレクション全体の集計・レアリティ別内訳（Phase 2）

詳細は `docs/要件定義書_ポケモンカード管理ツール.html` を参照。
