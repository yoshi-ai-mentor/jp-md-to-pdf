# Changelog

All notable changes to **jp-md-to-pdf** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/ja/).

## [1.1.0] - 2026-04-15

公開前のセキュリティ hardening。

### Changed

- remote fetch を single-resolution pinned fetcher 経由に変更
- custom CSS も safe fetcher 配下で処理
- input / CSS / fetched resource の上限を追加
- Python 依存を `requirements-lock.txt` へ固定し、`setup_fonts.sh` もそこから install する形に変更
- Python 要件を 3.10+ に更新し、README / SKILL / CHANGELOG の依存表記を exact pins に揃えた
- `setup_fonts.sh` に runtime preflight を追加

## [1.0.0] - 2026-04-14

初回リリース。日本語 Markdown から A4 PDF への変換を、Claude Code / GitHub Copilot CLI などの AI コーディングツールから呼び出せる形で提供。

### Added

#### コア機能
- Markdown → A4 PDF 変換（weasyprint ベース）
- 日本語フォント自動セットアップ（BIZ UDPGothic 推奨 + Noto Sans CJK JP フォールバック）
- `scripts/setup_fonts.sh` で sandbox 環境でも root 権限なしで日本語PDFが出せる

#### セキュリティ境界
- raw HTML を既定でエスケープ
- http(s) / local file fetch を opt-in フラグ（`--allow-http` / `--allow-local`）に制限
- `--margin` / `--font-size` / `--font` / `--css` / `--title` に allowlist バリデーションを追加

#### プリセット機能（`--preset`）
- 7つのビルトインプリセットで margin / font-size / style / font を一括切替
  - `resume` — 履歴書・職務経歴書（5mm余白・9pt・詰め込み型）
  - `proposal` — 顧客向け提案書（18mm・10.5pt・カラーアクセント graphical）
  - `report` — 分析レポート・調査資料（proposal と同系統で見出し強調）
  - `note-article` — note 記事プリントアウト（20mm・11pt・ゆったり）
  - `invoice` — 請求書・見積書（15mm・10pt・シンプル plain）
  - `minimal` — 小説・エッセイ読み物（25mm・11pt・最小装飾）
  - `slide` — A4横スライド（15mm・16pt・`---` 区切り）
- `--list-presets` でプリセット一覧を表示
- 優先順位: `DEFAULTS < preset < CLI明示指定`

#### 表紙ページ生成
- `--cover-title` / `--cover-subtitle` / `--cover-author` / `--cover-date` で1ページ目に表紙を差し込み
- `--cover-date ""` で今日の日付を `YYYY年MM月DD日` 形式で自動挿入
- style に応じた3種のデザイン:
  - plain: 白背景・26pt タイトル・13pt グレー副題（シンプル）
  - graphical: ネイビーグラデ背景・30pt 白タイトル・14pt ゴールド副題（フォーマル）
  - slide: A4横・グラデ背景・40pt 大タイトル（プレゼン表紙）

#### A4横スライドモード（`--style slide` / `--preset slide`）
- A4横向きレイアウト
- Markdown の `---`（hr）を改ページに変換（`page-break-after: always`）
- ページ番号を右下に自動表示
- h1=28pt / h2=22pt / h3=18pt の大型見出しで可読性確保

#### サンプル
- `samples/01_resume_sample.md` — 職務経歴書の最小サンプル
- `samples/02_proposal_sample.md` — 業務フロー改善提案書の架空サンプル
- `samples/03_slide_sample.md` — AIコーディングツール導入ガイドのサンプルスライド

### Dependencies
- Python 3.10+
- weasyprint 68.1
- markdown 3.10.2
- pypdf 6.10.1

### Known Issues
- pypdf が ARC4 暗号化まわりの `DeprecationWarning` を stderr に出力（PDF出力には影響なし。pypdf の将来バージョンで解消予定）

### Notes
- ライセンス: MIT
- Maintainer: yoshi_ai_mentor
