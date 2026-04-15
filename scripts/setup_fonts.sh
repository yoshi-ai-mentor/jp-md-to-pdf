#!/usr/bin/env bash
#
# jp-md-to-pdf: 初回セットアップスクリプト
# - Python 依存 (weasyprint, markdown, pypdf) を pip で入れる
# - 日本語フォント3種を ~/.local/share/fonts/ に配置
#   * BIZ UDPGothic (Regular + Bold) - 推奨デフォルト。可読性特化のUDフォント
#   * Noto Sans CJK JP - フォールバック。従来から入ってる可能性高い
# - fc-cache でフォントキャッシュを更新
#
# root 権限不要。sandbox 環境でも動く設計。

set -euo pipefail

readonly BIZ_REGULAR_URL="https://raw.githubusercontent.com/googlefonts/morisawa-biz-ud-gothic/18934af56b9c003ca58c54bffbf226848cb11032/fonts/ttf/BIZUDPGothic-Regular.ttf"
readonly BIZ_BOLD_URL="https://raw.githubusercontent.com/googlefonts/morisawa-biz-ud-gothic/18934af56b9c003ca58c54bffbf226848cb11032/fonts/ttf/BIZUDPGothic-Bold.ttf"
readonly NOTO_CJK_URL="https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf"

readonly BIZ_REGULAR_SHA256="258d7156c165f2ff774b6efee637c22c3b950de0d8a10e501137061bc8085d01"
readonly BIZ_BOLD_SHA256="30eba52fc837e8b62c97d4b82e6706583149fb7294e3712dd71a655eaea80a90"
readonly NOTO_CJK_SHA256="68a3fc98800b2a27b371f2fb79991daf3633bd89309d4ffaa6946fd587f375b5"
readonly REQUIREMENTS_FILE="$(cd "$(dirname "$0")/.." && pwd)/requirements.txt"

echo "=== jp-md-to-pdf setup ==="

require_cmd() {
    local cmd="$1"
    local message="$2"

    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "エラー: $message"
        exit 1
    fi
}

# --- Python 依存 ---
echo ""
echo "[1/4] Python 依存をインストール中..."
PYTHON_BIN="${PYTHON_BIN:-python3}"
require_cmd "$PYTHON_BIN" "python3 が見つからない"
if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
    echo "エラー: Python 3.10+ が必要。現在の $PYTHON_BIN は $("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
    echo "  例: PYTHON_BIN=python3.10 bash scripts/setup_fonts.sh"
    exit 1
fi
if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    echo "エラー: $PYTHON_BIN から pip を呼び出せない"
    exit 1
fi
require_cmd shasum "shasum が見つからない。checksum 検証に必要"
if command -v curl >/dev/null 2>&1; then
    DL_CMD="curl"
elif command -v wget >/dev/null 2>&1; then
    DL_CMD="wget"
else
    echo "エラー: curl か wget のどちらかが必要"
    exit 1
fi

if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "エラー: requirements.txt が見つからない: $REQUIREMENTS_FILE"
    exit 1
fi

# --break-system-packages は Linux (Debian/Ubuntu) の PEP 668 対策
# macOS では無視されるので付けっぱなしで OK
"$PYTHON_BIN" -m pip install --user --quiet --break-system-packages -r "$REQUIREMENTS_FILE" 2>/dev/null || \
    "$PYTHON_BIN" -m pip install --user --quiet -r "$REQUIREMENTS_FILE"

echo "  -> weasyprint, markdown, pypdf OK"
echo "  -> 利用Python: $PYTHON_BIN"

# --- フォントディレクトリ準備 ---
FONT_DIR="$HOME/.local/share/fonts"
mkdir -p "$FONT_DIR"

# --- DL ヘルパー関数 ---
verify_checksum() {
    local file="$1"
    local expected_sha="$2"
    local label="$3"
    local actual_sha

    actual_sha="$(shasum -a 256 "$file" | awk '{print $1}')"
    if [ "$actual_sha" != "$expected_sha" ]; then
        echo "エラー: $label の checksum が一致しない"
        echo "  expected: $expected_sha"
        echo "  actual  : $actual_sha"
        return 1
    fi
}

download_font() {
    local url="$1"
    local out="$2"
    local expected_sha="$3"
    local label="$4"
    local tmp="${out}.download"

    if [ -s "$out" ]; then
        if verify_checksum "$out" "$expected_sha" "$label"; then
            echo "  -> $label: 既に配置済み ($(basename "$out"))"
            return 0
        fi
        echo "  -> $label: 既存ファイルの checksum が不一致。再取得する"
        rm -f "$out"
    fi

    echo "  -> $label: DL中..."
    rm -f "$tmp"
    if [ "$DL_CMD" = "curl" ]; then
        curl -fsSL -o "$tmp" "$url"
    else
        wget -q -O "$tmp" "$url"
    fi

    if [ ! -s "$tmp" ]; then
        echo "  -> $label: DL失敗"
        return 1
    fi

    if ! verify_checksum "$tmp" "$expected_sha" "$label"; then
        rm -f "$tmp"
        return 1
    fi

    mv "$tmp" "$out"
    echo "  -> $label: 配置完了 ($(basename "$out"))"
}

# --- BIZ UDPGothic (推奨デフォルト) ---
echo ""
echo "[2/4] BIZ UDPGothic をDL中 (推奨・可読性特化UDフォント)..."
download_font \
    "$BIZ_REGULAR_URL" \
    "$FONT_DIR/BIZUDPGothic-Regular.ttf" \
    "$BIZ_REGULAR_SHA256" \
    "BIZ UDPGothic Regular"
download_font \
    "$BIZ_BOLD_URL" \
    "$FONT_DIR/BIZUDPGothic-Bold.ttf" \
    "$BIZ_BOLD_SHA256" \
    "BIZ UDPGothic Bold"

# --- Noto Sans CJK JP (フォールバック) ---
echo ""
echo "[3/4] Noto Sans CJK JP をDL中 (フォールバック)..."
download_font \
    "$NOTO_CJK_URL" \
    "$FONT_DIR/NotoSansCJKjp-Regular.otf" \
    "$NOTO_CJK_SHA256" \
    "Noto Sans CJK JP Regular (フォールバック)"

# --- フォントキャッシュ更新 ---
echo ""
echo "[4/4] フォントキャッシュを更新中..."
if command -v fc-cache >/dev/null 2>&1; then
    fc-cache -f "$HOME/.local/share/fonts" 2>/dev/null || fc-cache -f
    echo "  -> fc-cache 完了"
else
    echo "  -> 警告: fc-cache なし。weasyprint が自前で見つけられる可能性もあるので続行"
fi

echo ""
echo "[4.5/4] WeasyPrint ランタイムを確認中..."
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jp-md-to-pdf-runtime-check.XXXXXX")"
TMP_PDF="$TMP_DIR/runtime-check.pdf"
cleanup_runtime_check() {
    rm -rf "$TMP_DIR"
}
trap cleanup_runtime_check EXIT
if ! "$PYTHON_BIN" - <<PY >/dev/null 2>&1
from weasyprint import HTML
HTML(string='<p>runtime-check</p>').write_pdf('$TMP_PDF')
PY
then
    echo "エラー: WeasyPrint のネイティブ依存を解決できていない可能性がある"
    echo "  対策: $PYTHON_BIN -c \"from weasyprint import HTML; HTML(string='<p>ok</p>').write_pdf('/tmp/jp-md-to-pdf-test.pdf')\" を確認してほしい"
    echo "  macOS では cairo / pango / fontconfig 周辺の不足を疑ってほしい"
    exit 1
fi
echo "  -> WeasyPrint runtime OK"

# --- 最終確認 ---
echo ""
echo "=== セットアップ完了 ==="
echo ""
echo "インストール済み日本語フォント:"
fc-list 2>/dev/null | grep -iE "(biz udp|noto sans cjk jp|noto sans jp)" | sed 's/^/  /' | head -10 || echo "  (fc-list 実行不可)"

echo ""
echo "使い方:"
echo "  $PYTHON_BIN $(dirname "$0")/convert.py --input example.md --output example.pdf --font biz-ud"
echo "  $PYTHON_BIN $(dirname "$0")/convert.py --input example.md --output example.pdf --font noto-jp"
echo "  $PYTHON_BIN $(dirname "$0")/convert.py --input example.md --output example.pdf --font noto-cjk"
