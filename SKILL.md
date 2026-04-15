---
name: jp-md-to-pdf
license: MIT
compatibility:
  - claude-code
  - copilot-cli
  - cursor
  - codex-cli
description: 日本語 Markdown を A4 PDF に変換する。履歴書・職務経歴書・提案書・note 記事・顧客向け資料・請求書・レポート・スライド/デッキなど、**日本語ドキュメントの PDF 化を頼まれたら必ずこのスキルを使う**。「この MD を PDF にして」「職務経歴書 PDF」「提案書を PDF で」「日本語の資料を PDF にしたい」「A4 で出力」「A4 横でスライドを PDF に」「16:9 スライドを PDF」「デッキを PDF 化」「表紙付きで PDF」「カバーページを付けて PDF」「表紙にロゴを載せて PDF」などの依頼が来たら発動すること。ユーザーが明示的に「PDF」と言わなくても、印刷や納品・配布を前提とした日本語ドキュメント（履歴書・提案書・スライド資料・請求書など）を整形する文脈であれば積極的に使う。weasyprint + BIZ UDPGothic / Noto Sans CJK JP で動くので sandbox でも root 権限なしで日本語 PDF が出せるのが強み。プリセット（resume/proposal/report/note-article/invoice/minimal/slide/slide-16x9）、表紙自動生成（--cover-* と --cover-logo）、スライドモード（--style slide・`--page-size` で用紙サイズ指定可）に対応。
---

# jp-md-to-pdf

日本語 Markdown を A4 PDF に変換するスキル。weasyprint + Noto Sans CJK JP を使った MD → HTML → PDF パイプライン。

## なぜこのスキルが存在するのか

日本語 PDF 生成は三大ハマりポイントがある:

1. **フォント問題**: 日本語フォントが入ってないと全部豆腐（□）になる
2. **CJK レンダリング**: pandoc + LaTeX は重い、wkhtmltopdf は CJK が弱い、reportlab は低レベルすぎる
3. **レイアウト**: ビジネス文書として体裁を整えるのに毎回 CSS を書き直すのは非効率

このスキルは weasyprint（HTML/CSS → PDF）と Noto Sans CJK JP（ユーザー権限で `~/.local/share/fonts/` に置ける）を組み合わせて、**sandbox 環境でも root なしで動く・そこそこ綺麗な日本語 PDF** を一発で出す。

## 依存

- Python 3.10+
- weasyprint==68.1 / markdown==3.10.2 / pypdf==6.10.1
- Noto Sans CJK JP フォント (初回セットアップスクリプトで導入)

## 使い方

### 初回セットアップ（環境ごとに1回）

Noto Sans CJK JP フォントが未インストールの場合、フォントとPython依存を一括でセットアップ:

```bash
bash <skill_path>/scripts/setup_fonts.sh
```

macOS の既定 `python3` が 3.9 系なら `PYTHON_BIN=python3.10 bash <skill_path>/scripts/setup_fonts.sh` を使う。

確認方法:

```bash
fc-list | grep -i "noto sans cjk jp"
```

何か出力されれば OK。空なら `setup_fonts.sh` を再実行。

### 基本変換

```bash
python3 <skill_path>/scripts/convert.py \
  --input path/to/input.md \
  --output path/to/output.pdf
```

出力の最後に「PDF生成完了: path (N ページ)」と表示される。**ユーザーへの報告ではページ数を必ず伝えること**（ページ数を気にするケースが大半なので）。

### オプション

| フラグ | デフォルト | 説明 |
|---|---|---|
| `--preset <name>` | なし | プリセット適用（下記プリセット表を参照）|
| `--list-presets` | - | 利用可能なプリセット一覧を表示して終了 |
| `--margin` | `6mm 4.5mm` | A4 ページ余白（CSS 形式、`上下 左右` または `上 右 下 左`）|
| `--font-size` | `10pt` | 本文フォントサイズ |
| `--font` | `biz-ud` | フォント選択（下記プリセット表を参照。カスタムCSS文字列も可）|
| `--style` | `plain` | デザインスタイル。`plain` / `graphical` / `slide` から選択 |
| `--page-size` | （slide 時は未指定なら `A4 landscape`） | **slide 専用**。`@page size`。例: `A4 landscape` / `338mm 190mm landscape` |
| `--page-break-before "文字列"` | なし | その文字列が出現する直前で改ページを挿入（複数指定可）|
| `--css path/to/custom.css` | 組込みCSS | カスタム CSS で見た目を完全上書き（style指定より優先）|
| `--title` | ファイル名 | PDF メタデータのタイトル |
| `--allow-http` | off | http(s) リソース取得を明示許可 |
| `--allow-local` | off | ローカルファイル参照を明示許可 |
| `--cover-title "..."` | なし | 指定すると表紙ページを先頭に追加 |
| `--cover-subtitle "..."` | なし | 表紙のサブタイトル |
| `--cover-author "..."` | なし | 表紙の著者・発行元名 |
| `--cover-date "..."` | なし | 表紙の日付。空文字列 `""` を渡すと今日の日付を自動挿入 |
| `--cover-logo path` | なし | 表紙の**最上部**（タイトルより上）にロゴ画像を載せる。**ローカルファイルパスだけ**（`.png` / `.jpg` / `.jpeg` / `.svg` / `.gif`、**2MB 以下**）。`http(s)` や `data:` などの **URL 形式は不可**。PDF には base64 の data URI で埋め込むので **`--allow-local` は不要** |

### プリセット (--preset)

複数のオプションをまとめて適用するメタ設定。`--list-presets` で最新一覧を確認できる。

| プリセット | margin | font-size | style | 用途 |
|---|---|---|---|---|
| `resume` | 12mm 10mm | 9.5pt | plain | 履歴書・職務経歴書（1-2枚に収める。余白は読みやすさ重視に調整済み）|
| `proposal` | 18mm 16mm | 10.5pt | graphical | 顧客向け提案書（カラーアクセント）|
| `report` | 18mm 16mm | 10.5pt | graphical | 分析レポート・調査資料 |
| `note-article` | 20mm 20mm | 11pt | plain | note記事のプリント版（ゆったり読み物）|
| `invoice` | 15mm 15mm | 10pt | plain | 請求書・見積書 |
| `minimal` | 25mm 20mm | 11pt | plain | 小説・エッセイ（最小装飾）|
| `slide` | 15mm 20mm | 16pt | slide | A4横スライド（`---` で改ページ・既定 `A4 landscape`）|
| `slide-16x9` | 12mm 18mm | 16pt | slide | 16:9 相当（338×190mm 横向き・投影向け）|

**優先順位**: DEFAULTS < preset < CLI明示指定。`--preset report --margin 10mm` のように部分上書き可能。

### スライドモード (--style slide / --preset slide)

A4横向きで、Markdown の `---` (水平線) を改ページとして扱う。1セクション = 1スライド。

```markdown
# スライドタイトル

本文1

---

## 次のスライド

本文2
```

### 表紙生成 (--cover-*)

`--cover-title` または `--cover-logo` のどちらかを指定すると、本文の前に表紙ページを1枚挿入する（**ロゴだけ**の表紙も可）。style によって装飾が変わる（plain: シンプル / graphical: 深紺グラデ / slide: 横向きグラデ）。

**`--cover-logo` の使い方**

- 会社ロゴ・製品アイコンなど、**信頼できるローカル画像**へのパスを渡す。表紙ブロック内ではタイトル文言より**上**・中央寄せ（CSS: `.cover-logo`、最大高さおおむね 80px / 最大幅 200px 目安）
- 拡張子とサイズは `validate_logo_path` で検証される。本文 Markdown 内の `![](logo.png)` とは別。**本文から画像を読むときは従来どおり `--allow-local` が必要**な場合がある

例（提案書プリセット + 表紙テキスト + ロゴ）:

```bash
python3 <skill_path>/scripts/convert.py \
  -i proposal.md -o proposal.pdf \
  --preset proposal \
  --cover-logo /path/to/logo.png \
  --cover-title "業務フロー改善提案書" \
  --cover-subtitle "経費精算フローの再設計" \
  --cover-author "株式会社〇〇" \
  --cover-date ""
```

### スタイルプリセット (--style)

| プリセット名 | CSS | 用途の目安 |
|---|---|---|
| `plain` (デフォルト) | `assets/default.css` | モノトーン・シンプル。履歴書・職務経歴書・請求書など硬めの書類 |
| `graphical` | `assets/graphical.css` | 深紺+琥珀茶のカラーアクセント。h2背景バー・blockquoteカード・テーブル装飾・フッターページ番号。提案書・レポート・顧客向け分析資料で"見た目の強度"が欲しいとき |

**判断軸**:
- 提出先が形式重視のフォーマルな場面（行政提出・採用書類など）→ `plain`
- 顧客に「読ませる」「印象を残す」資料 → `graphical`
- 内部メモ・ドラフト → `plain`（速度優先）

### フォントプリセット

| プリセット名 | 構成 | 用途の目安 |
|---|---|---|
| `biz-ud` (推奨デフォルト) | BIZ UDPGothic → Noto Sans CJK JP → Noto Sans JP | 履歴書・職務経歴書・顧客向け資料など可読性重視の全般 |
| `noto` | Noto Sans CJK JP → Noto Sans JP → BIZ UDPGothic | Noto系を優先したいとき（汎用・技術文書向け）|
| `noto-cjk` | Noto Sans CJK JP のみ | Notoに固定したい場合 |
| `noto-jp` | Noto Sans JP → Noto Sans CJK JP | Google系の新JP特化フォントを優先 |
| カスタム文字列 | そのまま CSS の font-family に流す | 例: `--font "'Hiragino Sans', sans-serif"`（フォントが環境にあれば使える）|

**推奨**: 既定値は可読性重視で `biz-ud`（BIZ UDPGothic）。Noto 系を優先したい文書だけ切り替える運用が扱いやすい。カスタム指定は環境依存なので注意。

### ユースケース別のプリセット目安

| 用途 | margin | font-size | 備考 |
|---|---|---|---|
| 履歴書（1ページ厳守） | `12mm 10mm`（`--preset resume`） | `9.5pt` | さらに詰めるなら `--margin` / `--font-size` で上書き |
| 職務経歴書 | `6mm 4.5mm` | `8.5pt` | 3〜4 ページ前提 |
| 提案書・レポート | `15mm 12mm` | `10.5pt` | 読みやすさ優先 |
| note 記事・ブログ | `18mm 15mm` | `11pt` | 長文用。行間ゆったり |
| 請求書・見積書 | `15mm 15mm` | `10pt` | 表が多いので余白広め |

### ページブレーク指定の例

職務経歴書で「第2キャリア」の前で改ページ:

```bash
python3 convert.py \
  -i 職務経歴書.md \
  -o 職務経歴書.pdf \
  --page-break-before "### 第2キャリア"
```

複数指定もできる:

```bash
python3 convert.py -i doc.md -o doc.pdf \
  --page-break-before "## 第2章" \
  --page-break-before "## 第3章"
```

## 組込みCSS の設計思想

`assets/default.css` は「ビジネス文書としてそのまま出せる」ことを目指した設計:

- **h1**: センター配置、letter-spacing 4pt、下線。表紙タイトル向け
- **h2**: 薄グレー背景 + 左側濃色ライン。セクションヘッダ向け
- **h3**: 下線付き。サブセクション向け
- **tables**: 罫線 + ヘッダ薄グレー。スキル表・資格表・経歴表に最適
- **ページブレーク回避**: h2/h3 直後の改ページを `page-break-after: avoid` で抑制

気に入らなければ `assets/default.css` をコピーして編集 → `--css` で読み込ませる。

## セキュリティ前提

このスキルは **trusted local** 前提で使う。

- raw HTML は既定でエスケープされる
- 外部 URL フェッチは既定で無効。必要時のみ `--allow-http`（localhost / private network 宛ては許可しない）
- ローカルファイル参照は既定で無効。必要時のみ `--allow-local`（入力 Markdown と custom CSS のディレクトリ配下だけ許可）
- `--cover-logo` は表紙用ロゴ専用のパス検証で読み込み、上記 `--allow-local` とは別（ローカル画像パスを直接渡す想定）
- `--css` はローカルの `.css` ファイルだけ許可
- 信頼できない Markdown / HTML / CSS を変換する用途は推奨しない

## 作業フロー（ユーザー依頼時）

1. **フォント確認**: `fc-list | grep -i "noto sans cjk jp"` が空ならセットアップ
2. **用途ヒアリング**: 初回は margin / font-size を用途に合わせて提案。2 回目以降はユーザーの前回設定を踏襲
3. **変換実行**: `convert.py` を叩く
4. **ページ数報告**: 「N ページで生成完了！」とぱっと見でわかる形で
5. **computer:// リンク提示**: `[PDFを開く](computer:///path/to/output.pdf)` の形で

## よくある調整パターン

### 「ページに収めたい」と言われたら

優先順位:
1. `--margin` を詰める（例: `6mm 4.5mm` → `5mm 4mm`）
2. `--font-size` を下げる（`10pt` → `9pt` → `8.5pt`。これ以下は可読性に注意）
3. MD の内容を削る提案（これがベスト。エージェントとして内容の冗長さを指摘する）

### 「ゆったり読ませたい」と言われたら

1. `--margin` を広げる（`15mm 12mm` とか）
2. `--font-size` を上げる（`10pt` → `11pt`）
3. CSS の `line-height` を `1.8` に上げる（カスタム CSS で）

### 「改ページを調整したい」と言われたら

`--page-break-before` で任意の見出し直前を指定。raw HTML は既定でエスケープされるので、改ページは CLI フラグで制御する前提で考える。

## トラブルシューティング

### 「警告: 指定フォント（--font xxx）がシステムに見つからない」が出た

convert.py が `fc-list` でフォント導入状況を事前チェックしていて、未導入だとこの警告を出す（PDF 生成自体は続行するが日本語が豆腐になる恐れあり）。対策:

- `bash scripts/setup_fonts.sh` を実行してフォントを導入する
- または警告が示した候補フォントのうち、すでに導入済みのものを `--font` で指定する

### 日本語が豆腐（□）になる

- `fc-list | grep -i "noto sans cjk jp\|biz udp"` で確認
- 空なら `setup_fonts.sh` を実行
- 入ってるのに豆腐なら `fc-cache -f` を再実行

### 思ったより多く/少ないページになる

- 余白とフォントサイズを確認（上のプリセット表を参照）
- `--page-break-before` で変な場所に改ページが入ってないか確認

### 改行が反映されない

- Markdown の仕様。空行を挟むか `<br>` を使う
- `nl2br` 拡張は使ってない（勝手な改行を防ぐため）

### 表が崩れる

- Markdown table のパイプ `|` とハイフン `-` の整合性を確認
- セル内の改行が必要なら `<br>` を使う

## 出自

日本語の職務経歴書・提案書・記事を PDF 化する用途から整理したスキル。2026-04-14 に初版作成。提出資料、顧客提案、配布用記事 PDF などに使う想定。
