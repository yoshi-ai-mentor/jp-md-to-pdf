#!/usr/bin/env python3
"""
jp-md-to-pdf: 日本語 Markdown → A4 PDF 変換ツール

Usage:
    python3 convert.py --input input.md --output output.pdf
    python3 convert.py -i input.md -o output.pdf --margin "6mm 4.5mm" --font-size 8.5pt
    python3 convert.py -i input.md -o output.pdf --page-break-before "## 第2章"

依存: weasyprint, markdown, pypdf (pypdf はページ数報告のみ)
フォント: Noto Sans CJK JP (setup_fonts.sh で事前導入)
"""
import argparse
import base64
import html as html_module
import http.client
import ipaddress
import json
import re
import shutil
import socket
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.request import url2pathname

from markdown.extensions import Extension


PAGE_BREAK_PLACEHOLDER = 'JP_MD_TO_PDF_PAGE_BREAK_PLACEHOLDER'
SAFE_MARGIN_RE = re.compile(
    r'^\s*(?:0|(?:\d+(?:\.\d+)?)(?:mm|cm|in|pt|px))'
    r'(?:\s+(?:0|(?:\d+(?:\.\d+)?)(?:mm|cm|in|pt|px))){0,3}\s*$'
)
SAFE_FONT_SIZE_RE = re.compile(r'^\s*(?:[6-9](?:\.\d+)?|[1-2]\d(?:\.\d+)?)pt\s*$')
DISALLOWED_FONT_CHARS = set(';:{}[]()<>@/\\\n\r\t')
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_CUSTOM_CSS_BYTES = 256 * 1024
MAX_FETCH_COUNT = 64
# data: URL 全体の上限（表紙ロゴを 2MB まで許すと base64 で約 2.8MB になる）
MAX_DATA_URL_CHARS = 3 * 1024 * 1024
MAX_FETCHED_RESOURCE_BYTES = 5 * 1024 * 1024
MAX_HTTP_REDIRECTS = 3
MAX_COVER_LOGO_BYTES = 2 * 1024 * 1024
COVER_LOGO_ALLOWED_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.svg', '.gif'})


# フォントプリセット: --font フラグに対応する font-family CSS 文字列
FONT_FAMILIES = {
    'biz-ud': "'BIZ UDPGothic', 'BIZ UDPゴシック', 'Noto Sans CJK JP', 'Noto Sans JP', sans-serif",
    'noto': "'Noto Sans CJK JP', 'Noto Sans JP', 'BIZ UDPGothic', sans-serif",
    'noto-cjk': "'Noto Sans CJK JP', sans-serif",
    'noto-jp': "'Noto Sans JP', 'Noto Sans CJK JP', sans-serif",
}


# CLI引数のデフォルト値(プリセットもCLIも未指定のとき使われる)
DEFAULTS = {
    'margin': '6mm 4.5mm',
    'font_size': '10pt',
    'font': 'biz-ud',
    'style': 'plain',
}


# プリセット定義ファイルのパス
PRESETS_FILE = Path(__file__).parent.parent / 'assets' / 'presets.json'


# フォント選択と、実際のシステムにインストールされていてほしいファミリー名の対応
# fc-list で見つからなければ「文字化け/豆腐化」のリスクがあるので警告する
FONT_PRESET_REQUIRED = {
    'biz-ud': ['BIZ UDPGothic', 'BIZ UDPゴシック'],
    'noto': ['Noto Sans CJK JP', 'Noto Sans JP'],
    'noto-cjk': ['Noto Sans CJK JP'],
    'noto-jp': ['Noto Sans JP', 'Noto Sans CJK JP'],
}


class EscapeHtmlExtension(Extension):
    """Disable raw HTML parsing so Markdown leaves tags as escaped text."""

    def extendMarkdown(self, md):
        md.preprocessors.deregister('html_block')
        md.inlinePatterns.deregister('html')


def validate_text_option(option_name: str, value: Optional[str], *, max_length: int = 200) -> Optional[str]:
    """Allow plain text only for metadata-ish CLI values."""
    if value is None:
        return None
    if len(value) > max_length:
        raise ValueError(f'{option_name} は {max_length} 文字以内で指定してほしい')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f'{option_name} に制御文字は使えない')
    return value


def validate_margin(margin: str) -> str:
    """Accept only simple CSS margin tokens."""
    normalized = margin.strip()
    if not SAFE_MARGIN_RE.match(normalized):
        raise ValueError('--margin は 1〜4 個の長さ指定だけ使える（例: "6mm 4.5mm"）')
    return normalized


def validate_font_size(font_size: str) -> str:
    """Restrict font-size to point values used by bundled presets."""
    normalized = font_size.strip()
    if not SAFE_FONT_SIZE_RE.match(normalized):
        raise ValueError('--font-size は pt 指定だけ使える（例: 10pt）')
    return normalized


def validate_font_arg(font_arg: str) -> str:
    """Allow known presets or a conservative custom font-family string."""
    normalized = font_arg.strip()
    if not normalized:
        raise ValueError('--font は空にできない')
    if normalized in FONT_FAMILIES:
        return normalized
    if len(normalized) > 120:
        raise ValueError('--font が長すぎる')
    if any(ch in DISALLOWED_FONT_CHARS for ch in normalized):
        raise ValueError('--font に危険な文字が含まれている')
    return normalized


def _mime_type_for_logo(path: Path) -> str:
    """Return MIME for embedded cover logo (validated extension only)."""
    suffix = path.suffix.lower()
    mapping = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
    }
    return mapping[suffix]


def validate_logo_path(logo_path: Optional[str]) -> Optional[str]:
    """Only allow local image files (png/jpg/jpeg/svg/gif), max 2MB. URLs are rejected."""
    if logo_path is None:
        return None
    raw = logo_path.strip()
    if not raw:
        raise ValueError('--cover-logo が空です')
    lower = raw.lower()
    if lower.startswith(('http://', 'https://', 'file://', 'data:')) or raw.startswith('//') or '://' in raw:
        raise ValueError('--cover-logo はローカルファイルパスだけ指定できる（URLは不可）')
    candidate = Path(raw).expanduser()
    if not candidate.exists():
        raise ValueError(f'--cover-logo のファイルが見つからない: {logo_path}')
    if not candidate.is_file():
        raise ValueError(f'--cover-logo は通常ファイルを指定してほしい: {logo_path}')
    suffix = candidate.suffix.lower()
    if suffix not in COVER_LOGO_ALLOWED_SUFFIXES:
        raise ValueError(
            '--cover-logo は .png / .jpg / .jpeg / .svg / .gif のいずれかにしてほしい'
        )
    size = candidate.stat().st_size
    if size > MAX_COVER_LOGO_BYTES:
        raise ValueError('--cover-logo は 2MB 以下にしてほしい')
    if size == 0:
        raise ValueError('--cover-logo が空のファイルです')
    return str(candidate.resolve())


def validate_css_path(css_path: Optional[str]) -> Optional[str]:
    """Only allow explicit local .css files."""
    if css_path is None:
        return None
    candidate = Path(css_path).expanduser()
    if candidate.suffix.lower() != '.css':
        raise ValueError('--css は .css ファイルだけ指定できる')
    if not candidate.exists():
        raise ValueError(f'--css のファイルが見つからない: {css_path}')
    if not candidate.is_file():
        raise ValueError(f'--css は通常ファイルを指定してほしい: {css_path}')
    if candidate.stat().st_size > MAX_CUSTOM_CSS_BYTES:
        raise ValueError('--css が大きすぎる。256KB 以下にしてほしい')
    return str(candidate.resolve())


def is_path_within_roots(candidate: Path, allowed_roots) -> bool:
    """Check containment without relying on Path.is_relative_to (py3.8 compatibility)."""
    resolved = candidate.resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def resolve_public_http_address(hostname: str, port: Optional[int] = None) -> str:
    """Resolve a hostname and return a pinned public IP address."""
    normalized = hostname.strip().lower()
    if not normalized or normalized == 'localhost':
        raise ValueError(f'private / localhost 宛てのURLは許可していない: {hostname}')

    try:
        candidates = [ipaddress.ip_address(normalized)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(normalized, port, type=socket.SOCK_STREAM)
        except socket.gaierror as e:
            raise ValueError(f'ホスト名を解決できない: {hostname}') from e
        candidates = []
        for info in infos:
            address = info[4][0]
            try:
                candidates.append(ipaddress.ip_address(address))
            except ValueError:
                continue

    for candidate in candidates:
        if candidate.is_global:
            return str(candidate)
    raise ValueError(f'private / localhost 宛てのURLは許可していない: {hostname}')


class PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that skips DNS after the validation step."""

    def __init__(self, host: str, pinned_ip: str, port: int, timeout: int):
        self._pinned_ip = pinned_ip
        super().__init__(host, port=port, timeout=timeout)

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that pins the validated IP but preserves hostname verification."""

    def __init__(self, host: str, pinned_ip: str, port: int, timeout: int, context):
        self._pinned_ip = pinned_ip
        super().__init__(host, port=port, timeout=timeout, context=context)

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            sock = self.sock
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


def fetch_http_resource(url: str, timeout: int = 10, ssl_context=None, http_headers=None, redirect_budget: int = MAX_HTTP_REDIRECTS):
    """Fetch remote resources without re-resolving after validation."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError(f'未対応のHTTP URL: {url}')

    hostname = parsed.hostname
    port = parsed.port or (443 if scheme == 'https' else 80)
    pinned_ip = resolve_public_http_address(hostname, port=port)
    path = parsed.path or '/'
    if parsed.query:
        path = f'{path}?{parsed.query}'
    headers = {'User-Agent': 'jp-md-to-pdf/1.1.0'}
    if http_headers:
        headers.update(http_headers)

    if scheme == 'https':
        context = ssl_context or ssl.create_default_context()
        connection = PinnedHTTPSConnection(hostname, pinned_ip, port, timeout, context=context)
    else:
        connection = PinnedHTTPConnection(hostname, pinned_ip, port, timeout)

    try:
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()

        if response.status in (301, 302, 303, 307, 308):
            location = response.getheader('Location')
            response.read()
            if not location:
                raise ValueError(f'HTTP redirect に Location がない: {url}')
            if redirect_budget <= 0:
                raise ValueError(f'HTTP redirect が多すぎる: {url}')
            redirected_url = urljoin(url, location)
            return fetch_http_resource(
                redirected_url,
                timeout=timeout,
                ssl_context=ssl_context,
                http_headers=http_headers,
                redirect_budget=redirect_budget - 1,
            )

        if response.status >= 400:
            raise ValueError(f'HTTP fetch 失敗: {response.status} {response.reason}')

        content_length = response.getheader('Content-Length')
        if content_length and int(content_length) > MAX_FETCHED_RESOURCE_BYTES:
            raise ValueError('取得リソースが大きすぎる')

        payload = response.read(MAX_FETCHED_RESOURCE_BYTES + 1)
        if len(payload) > MAX_FETCHED_RESOURCE_BYTES:
            raise ValueError('取得リソースが大きすぎる')

        return {
            'string': payload,
            'mime_type': response.headers.get_content_type(),
            'encoding': response.headers.get_content_charset(),
            'redirected_url': url,
        }
    except OSError as e:
        raise ValueError(f'HTTP fetch 失敗: {e}') from e
    finally:
        connection.close()


def build_safe_url_fetcher(allow_http: bool, allow_local: bool, allowed_local_roots=None, url_fetcher=None, http_fetcher=None):
    """Deny external and local fetches by default unless explicitly opted in."""
    if url_fetcher is None:
        from weasyprint import default_url_fetcher
        url_fetcher = default_url_fetcher
    if http_fetcher is None:
        http_fetcher = fetch_http_resource
    allowed_local_roots = [Path(root).resolve() for root in (allowed_local_roots or [])]
    state = {'count': 0}

    def safe_url_fetcher(url, timeout=10, ssl_context=None, http_headers=None):
        state['count'] += 1
        if state['count'] > MAX_FETCH_COUNT:
            raise ValueError(f'参照リソース数が上限を超えた: {MAX_FETCH_COUNT}')

        if url.startswith('data:') and len(url) > MAX_DATA_URL_CHARS:
            raise ValueError('data URL が大きすぎる')

        parsed = urlparse(url)
        scheme = (parsed.scheme or '').lower()

        if scheme in ('http', 'https'):
            if not allow_http:
                raise ValueError(f'外部URLフェッチは --allow-http で明示許可が必要: {url}')
            result = http_fetcher(
                url,
                timeout=timeout,
                ssl_context=ssl_context,
                http_headers=http_headers,
            )
        elif scheme in ('', 'file'):
            if not allow_local:
                raise ValueError(f'ローカルファイル参照は --allow-local で明示許可が必要: {url}')
            local_path = Path(url2pathname(parsed.path)).resolve()
            if not is_path_within_roots(local_path, allowed_local_roots):
                raise ValueError(f'許可されていないローカルパスを参照しようとした: {url}')
            result = url_fetcher(
                url,
                timeout=timeout,
                ssl_context=ssl_context,
                http_headers=http_headers,
            )
        elif scheme in ('data', 'about'):
            # data: URI は MAX_DATA_URL_CHARS で入口制限済み。
            # WeasyPrint 68+ は URLFetcherResponse を返すため、
            # dict 前提のサイズチェックは通さずそのまま返す。
            return url_fetcher(
                url,
                timeout=timeout,
                ssl_context=ssl_context,
                http_headers=http_headers,
            )
        else:
            raise ValueError(f'未対応のURLスキームを検出: {scheme or "(relative)"}')

        # WeasyPrint 68+ の URLFetcherResponse 対応:
        # dict ではなくオブジェクトなので getattr で安全にアクセス
        resp_string = getattr(result, 'string', None) if not isinstance(result, dict) else result.get('string')
        resp_file_obj = getattr(result, 'file_obj', None) if not isinstance(result, dict) else result.get('file_obj')

        if resp_string is not None and len(resp_string) > MAX_FETCHED_RESOURCE_BYTES:
            raise ValueError('取得リソースが大きすぎる')
        if resp_file_obj is not None:
            data = resp_file_obj.read(MAX_FETCHED_RESOURCE_BYTES + 1)
            resp_file_obj.close()
            if len(data) > MAX_FETCHED_RESOURCE_BYTES:
                raise ValueError('取得リソースが大きすぎる')
            if isinstance(result, dict):
                result.pop('file_obj', None)
                result['string'] = data
        return result

    return safe_url_fetcher


def check_fonts(font_arg: str) -> None:
    """fc-list でフォントの導入状況を確認して、未導入なら stderr に警告を出す。

    fc-list が無い環境（fontconfig 未導入の minimal Linux など）ではスキップ。
    カスタム CSS 文字列（プリセット名以外）もスキップする。
    """
    # プリセット名でなければ判定しない
    if font_arg not in FONT_PRESET_REQUIRED:
        return
    # fc-list が使えなければ判定しない（エラーにはしない）
    if shutil.which('fc-list') is None:
        return

    required_any = FONT_PRESET_REQUIRED[font_arg]
    try:
        result = subprocess.run(
            ['fc-list', ':lang=ja'],
            capture_output=True, text=True, timeout=5, check=False,
        )
        installed_output = (result.stdout or '') + (result.stderr or '')
    except (subprocess.SubprocessError, OSError):
        return  # 検知失敗は無視（quality check であってブロッカーではない）

    found = any(name in installed_output for name in required_any)
    if found:
        return

    setup_script = Path(__file__).parent / 'setup_fonts.sh'
    print(
        '\n警告: 指定フォント（--font {}）がシステムに見つからない。\n'
        '  候補: {}\n'
        '  PDF は生成されるが、日本語が豆腐（□）で描画される恐れがある。\n'
        '  対策: {} を実行してフォントを導入する\n'
        '       または --font noto / --font noto-jp など、導入済みのフォントを選ぶ。'.format(
            font_arg, ' / '.join(required_any), setup_script,
        ),
        file=sys.stderr,
    )


def load_presets() -> dict:
    """presets.json を読み込む。メタデータ(_meta等)は除外する。"""
    if not PRESETS_FILE.exists():
        return {}
    data = json.loads(PRESETS_FILE.read_text(encoding='utf-8'))
    return {k: v for k, v in data.items() if not k.startswith('_')}


def apply_preset(preset_name: str, args: argparse.Namespace) -> None:
    """プリセット値を args に適用する。ただしCLIで明示指定された(Noneでない)値は上書きしない。

    override順序: DEFAULTS < preset < CLI明示指定
    """
    presets = load_presets()
    if preset_name not in presets:
        available = ', '.join(sorted(presets.keys()))
        raise ValueError(
            f"プリセット '{preset_name}' が見つからない。\n利用可能: {available}"
        )
    preset = presets[preset_name]
    # プリセット内のキー(description以外)を args に反映。ただしCLIで既に指定があれば維持
    for key, value in preset.items():
        if key == 'description':
            continue
        # argparseのattr名は '-' が '_' に変換される(例: font-size → font_size)
        attr = key.replace('-', '_')
        if hasattr(args, attr) and getattr(args, attr) is None:
            setattr(args, attr, value)


def fill_defaults(args: argparse.Namespace) -> None:
    """args に残ったNoneをハードコードデフォルトで埋める。"""
    for attr, default in DEFAULTS.items():
        if getattr(args, attr, None) is None:
            setattr(args, attr, default)


def print_presets_list() -> None:
    """--list-presets 時の出力。"""
    presets = load_presets()
    if not presets:
        print("プリセット定義が見つからない(presets.json)")
        return
    print("利用可能なプリセット一覧:")
    print()
    max_name_len = max(len(name) for name in presets.keys())
    for name in sorted(presets.keys()):
        config = presets[name]
        desc = config.get('description', '')
        print(f"  {name:<{max_name_len}}  {desc}")
    print()
    print("使い方: python3 convert.py -i doc.md -o doc.pdf --preset <name>")


def resolve_font_family(font_arg: str) -> str:
    """--font 引数を font-family CSS 値に解決する。

    プリセット名なら辞書から引く。それ以外は直接 CSS 文字列として扱う（カスタム指定）。
    """
    if font_arg in FONT_FAMILIES:
        return FONT_FAMILIES[font_arg]
    # カスタム指定: 'My Font, serif' みたいなのをそのまま使える
    return font_arg


def build_cover_html(cover_title: str, cover_subtitle: str = None,
                     cover_author: str = None, cover_date: str = None,
                     style: str = 'plain', cover_logo: Optional[str] = None) -> str:
    """表紙ブロックのHTMLを生成する。style=slide の場合は横向き用クラスを付与。

    cover_logo: validate_logo_path 済みのローカルパス。base64 data URI で表紙先頭に埋め込む。
    """
    import datetime

    # cover_date が空文字列なら今日の日付を自動挿入（None のときは非表示）
    if cover_date == '':
        cover_date = datetime.date.today().strftime('%Y年%m月%d日')

    cls = 'cover-page cover-slide' if style == 'slide' else 'cover-page'
    parts = [f'<div class="{cls}">']
    parts.append('<div class="cover-inner">')
    if cover_logo:
        logo_path = Path(cover_logo)
        payload = logo_path.read_bytes()
        mime = _mime_type_for_logo(logo_path)
        b64 = base64.b64encode(payload).decode('ascii')
        data_uri = f'data:{mime};base64,{b64}'
        parts.append(
            f'<img class="cover-logo" src="{data_uri}" alt="" />'
        )
    if cover_title:
        parts.append(f'<h1 class="cover-title">{html_module.escape(cover_title)}</h1>')
    if cover_subtitle:
        parts.append(f'<p class="cover-subtitle">{html_module.escape(cover_subtitle)}</p>')
    parts.append('<div class="cover-spacer"></div>')
    if cover_author:
        parts.append(f'<p class="cover-author">{html_module.escape(cover_author)}</p>')
    if cover_date:
        parts.append(f'<p class="cover-date">{html_module.escape(cover_date)}</p>')
    parts.append('</div>')
    parts.append('</div>')
    return '\n'.join(parts)


def build_html(md_content: str, css_content: str, page_breaks=None, title: str = "",
               style: str = 'plain',
               cover_title: str = None, cover_subtitle: str = None,
               cover_author: str = None, cover_date: str = None,
               cover_logo: Optional[str] = None) -> str:
    """Markdown 本文と CSS を組み合わせて HTML 文書を作る。

    style='slide' の場合:
      - Markdown の `---`(hr) を「次スライドへ改ページ」として扱う
      - body に slide-mode クラスを付与
    raw HTML は既定でエスケープする。
    """
    import markdown

    # ページブレーク挿入（MD → HTML 変換前にプレースホルダを仕込む）
    if page_breaks:
        for marker in page_breaks:
            md_content = md_content.replace(
                marker,
                f'{PAGE_BREAK_PLACEHOLDER}\n\n{marker}'
            )

    md_html = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', EscapeHtmlExtension()]
    )
    md_html = md_html.replace(
        f'<p>{PAGE_BREAK_PLACEHOLDER}</p>',
        '<div class="page-break"></div>',
    )

    # 表紙ブロック（タイトルまたはロゴのどちらかがあれば生成）
    cover_html = ''
    if cover_title or cover_logo:
        cover_html = build_cover_html(
            cover_title=cover_title or '',
            cover_subtitle=cover_subtitle,
            cover_author=cover_author,
            cover_date=cover_date,
            style=style,
            cover_logo=cover_logo,
        )

    body_class = 'slide-mode' if style == 'slide' else 'doc-mode'
    safe_title = html_module.escape(title or 'Document')

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>{safe_title}</title>
<style>
{css_content}
</style>
</head>
<body class="{body_class}">
{cover_html}
{md_html}
</body>
</html>"""


def build_default_css(margin: str = '6mm 4.5mm', font_size: str = '10pt',
                      font_family: str = None) -> str:
    """組込みデフォルトCSSを組み立てる。assets/default.css が見つからない場合のフォールバック。"""
    if font_family is None:
        font_family = FONT_FAMILIES['biz-ud']
    return f"""
@page {{
  size: A4;
  margin: {margin};
}}

* {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}

body {{
  font-family: {font_family};
  font-size: {font_size};
  line-height: 1.6;
  color: #111;
  background: #fff;
}}

.page-break {{
  page-break-before: always;
}}

h1 {{
  font-size: 17pt;
  font-weight: bold;
  text-align: center;
  letter-spacing: 4pt;
  margin-bottom: 1mm;
  padding-bottom: 2mm;
  border-bottom: 2px solid #222;
}}

h1 + p {{
  text-align: right;
  font-size: 8.5pt;
  margin-bottom: 4mm;
  color: #333;
  border-bottom: 1px solid #ccc;
  padding-bottom: 2mm;
}}

h2 {{
  font-size: 10pt;
  font-weight: bold;
  background: #e8e8e8;
  border-left: 4px solid #333;
  padding: 1.5mm 3mm;
  margin-top: 4mm;
  margin-bottom: 1.5mm;
  page-break-after: avoid;
}}

h3 {{
  font-size: 9pt;
  font-weight: bold;
  border-bottom: 1px solid #999;
  padding: 1mm 0;
  margin-top: 3mm;
  margin-bottom: 1mm;
  page-break-after: avoid;
}}

p {{
  margin-bottom: 1.5mm;
  text-align: left;
  color: #111;
}}

ul, ol {{
  margin-left: 4mm;
  padding-left: 3mm;
  margin-bottom: 1.5mm;
}}

li {{
  margin-bottom: 0.5mm;
  text-align: left;
  color: #111;
}}

li > ul, li > ol {{
  margin-top: 0.3mm;
  margin-bottom: 0.3mm;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 2mm;
  font-size: {float(font_size.rstrip('pt')) - 0.5}pt;
}}

table th, table td {{
  border: 1px solid #bbb;
  padding: 1.5mm 2.5mm;
  text-align: left;
  vertical-align: top;
  color: #111;
}}

table th {{
  background: #f0f0f0;
  font-weight: bold;
  white-space: nowrap;
}}

strong {{
  font-weight: bold;
}}

hr {{
  border: none;
  border-top: 1px solid #ddd;
  margin: 2mm 0;
}}

code {{
  font-family: 'Menlo', 'Consolas', monospace;
  background: #f4f4f4;
  padding: 0.3mm 1mm;
  border-radius: 1mm;
  font-size: 0.9em;
}}

pre {{
  background: #f4f4f4;
  padding: 2mm 3mm;
  border-radius: 1mm;
  margin-bottom: 2mm;
  overflow-x: auto;
  font-size: 0.85em;
}}

pre code {{
  background: transparent;
  padding: 0;
}}
"""


def load_css(custom_css_path: str, margin: str, font_size: str, font_family: str,
             style: str = 'plain') -> str:
    """カスタムCSSが指定されていればそれを、なければアセットのCSSを、それも無ければ組込みデフォルトを返す。

    style パラメータで選ぶアセット:
      - 'plain'     → assets/default.css
      - 'graphical' → assets/graphical.css (カラーアクセント・カード・ボックス強調)

    アセットのCSS内の `{{MARGIN}}` `{{FONT_SIZE}}` `{{FONT_FAMILY}}` プレースホルダは置換する。
    """
    if custom_css_path:
        return Path(custom_css_path).read_text(encoding='utf-8')

    # style に応じて読むアセットを選ぶ
    asset_map = {
        'plain': 'default.css',
        'graphical': 'graphical.css',
        'slide': 'slide.css',
    }
    asset_name = asset_map.get(style, 'default.css')
    asset_path = Path(__file__).parent.parent / 'assets' / asset_name

    if asset_path.exists():
        template = asset_path.read_text(encoding='utf-8')
        # テンプレート変数の置換
        return (template
                .replace('{{MARGIN}}', margin)
                .replace('{{FONT_SIZE}}', font_size)
                .replace('{{FONT_FAMILY}}', font_family))

    # フォールバック: 組込みCSSを使う（plain相当）
    return build_default_css(margin=margin, font_size=font_size, font_family=font_family)


def generate_pdf(
    input_md: str,
    output_pdf: str,
    margin: str = '6mm 4.5mm',
    font_size: str = '10pt',
    font: str = 'biz-ud',
    style: str = 'plain',
    page_breaks=None,
    custom_css: str = None,
    title: str = "",
    cover_title: str = None,
    cover_subtitle: str = None,
    cover_author: str = None,
    cover_date: str = None,
    cover_logo: str = None,
    allow_http: bool = False,
    allow_local: bool = False,
) -> int:
    """MD → PDF 変換の本体。生成された PDF のページ数を返す。"""
    from weasyprint import CSS
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration

    input_path = Path(input_md).resolve()
    if input_path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f'入力Markdownが大きすぎる。{MAX_INPUT_BYTES // (1024 * 1024)}MB 以下にしてほしい')

    md_content = input_path.read_text(encoding='utf-8')
    font_family = resolve_font_family(font)
    custom_stylesheets = None
    if custom_css:
        css_content = ''
        custom_stylesheets = [CSS(filename=custom_css)]
    else:
        css_content = load_css(custom_css, margin, font_size, font_family, style=style)
    html = build_html(
        md_content, css_content,
        page_breaks=page_breaks, title=title, style=style,
        cover_title=cover_title, cover_subtitle=cover_subtitle,
        cover_author=cover_author, cover_date=cover_date,
        cover_logo=cover_logo,
    )

    font_config = FontConfiguration()
    allowed_local_roots = [input_path.parent]
    if custom_css:
        allowed_local_roots.append(Path(custom_css).resolve().parent)
    safe_fetcher = build_safe_url_fetcher(allow_http, allow_local, allowed_local_roots=allowed_local_roots)
    if custom_css:
        custom_stylesheets = [CSS(filename=custom_css, font_config=font_config, url_fetcher=safe_fetcher)]
    base_url = input_path.parent.as_uri() + '/'
    HTML(
        string=html,
        base_url=base_url,
        url_fetcher=safe_fetcher,
    ).write_pdf(
        output_pdf,
        font_config=font_config,
        presentational_hints=True,
        stylesheets=custom_stylesheets,
    )

    # ページ数確認
    try:
        from pypdf import PdfReader
        return len(PdfReader(output_pdf).pages)
    except ImportError:
        return -1


def main():
    parser = argparse.ArgumentParser(
        description='日本語 Markdown を A4 PDF に変換する',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # プリセット一覧を見る
  python3 convert.py --list-presets

  # 履歴書プリセット（1枚に詰める）
  python3 convert.py -i 職務経歴書.md -o 職務経歴書.pdf --preset resume

  # 提案書プリセット + 表紙生成
  python3 convert.py -i 提案書.md -o 提案書.pdf --preset proposal \\
    --cover-title "業務フロー改善提案書" --cover-subtitle "経費精算フローの再設計" \\
    --cover-author "株式会社〇〇" --cover-date ""

  # A4横スライド（--- で改ページ）
  python3 convert.py -i deck.md -o deck.pdf --preset slide \\
    --cover-title "AIコーディングツール導入ガイド"

  # プリセットを使わず手動指定
  python3 convert.py -i doc.md -o doc.pdf --margin "15mm 12mm" --font-size 10.5pt

  # 特定の見出しの前で改ページ
  python3 convert.py -i doc.md -o doc.pdf --page-break-before "## 第2章"

優先順位: DEFAULTS < preset < CLI明示指定
        """
    )
    parser.add_argument('--input', '-i', help='入力 MD ファイル')
    parser.add_argument('--output', '-o', help='出力 PDF ファイル')
    parser.add_argument('--preset', default=None,
                        help='プリセット名。--list-presets で一覧確認（例: resume/proposal/report/slide）')
    parser.add_argument('--list-presets', action='store_true',
                        help='利用可能なプリセット一覧を表示して終了')
    parser.add_argument('--margin', default=None,
                        help='ページ余白（CSS 形式。プリセット未指定時のデフォルト: 6mm 4.5mm）')
    parser.add_argument('--font-size', default=None,
                        help='本文フォントサイズ（プリセット未指定時のデフォルト: 10pt）')
    parser.add_argument('--font', default=None,
                        help=('フォント選択。biz-ud (推奨・可読性重視) / noto (Noto系) / '
                              'noto-cjk / noto-jp / カスタムCSS文字列も可'))
    parser.add_argument('--style', default=None, choices=['plain', 'graphical', 'slide'],
                        help=('デザインスタイル。plain (モノトーン) / '
                              'graphical (カラーアクセント・カード) / slide (A4横スライド)'))
    parser.add_argument('--page-break-before', action='append', default=[],
                        help='この文字列の直前で改ページ（複数指定可）')
    parser.add_argument('--css', help='カスタム CSS ファイルで見た目を完全上書き')
    parser.add_argument('--title', default='', help='PDF メタデータのタイトル')
    parser.add_argument('--allow-http', action='store_true',
                        help='Markdown/CSS からの http(s) リソース取得を明示許可する')
    parser.add_argument('--allow-local', action='store_true',
                        help='Markdown/CSS からのローカルファイル参照を明示許可する')
    # 表紙生成オプション
    parser.add_argument('--cover-title', default=None, help='表紙のタイトル（指定すると表紙を生成）')
    parser.add_argument('--cover-subtitle', default=None, help='表紙のサブタイトル')
    parser.add_argument('--cover-author', default=None, help='表紙の著者名')
    parser.add_argument('--cover-date', default=None, help='表紙の日付（空文字なら今日の日付を自動挿入）')
    parser.add_argument('--cover-logo', default=None,
                        help='表紙先頭に載せるロゴ画像（ローカルパスのみ。png/jpg/jpeg/svg/gif、2MB以下。URL不可）')
    args = parser.parse_args()

    # --list-presets は最優先で処理して終了
    if args.list_presets:
        print_presets_list()
        sys.exit(0)

    # --list-presets 以外では --input / --output が必須
    if not args.input or not args.output:
        parser.error('--input と --output は必須（--list-presets を除く）')

    # プリセット適用 → ハードコードデフォルト埋め
    # 優先順位: DEFAULTS < preset < CLI明示指定
    if args.preset:
        try:
            apply_preset(args.preset, args)
        except ValueError as e:
            print(f"エラー: {e}", file=sys.stderr)
            sys.exit(1)
    fill_defaults(args)
    try:
        args.margin = validate_margin(args.margin)
        args.font_size = validate_font_size(args.font_size)
        args.font = validate_font_arg(args.font)
        args.css = validate_css_path(args.css)
        args.title = validate_text_option('--title', args.title)
        args.cover_title = validate_text_option('--cover-title', args.cover_title)
        args.cover_subtitle = validate_text_option('--cover-subtitle', args.cover_subtitle)
        args.cover_author = validate_text_option('--cover-author', args.cover_author)
        args.cover_date = validate_text_option('--cover-date', args.cover_date)
        args.cover_logo = validate_logo_path(args.cover_logo)
    except ValueError as e:
        print(f'エラー: {e}', file=sys.stderr)
        sys.exit(1)

    # 入力ファイル存在チェック
    if not Path(args.input).exists():
        print(f"エラー: 入力ファイルが見つからない: {args.input}", file=sys.stderr)
        sys.exit(1)

    # 出力ディレクトリ作成
    try:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"エラー: 出力先ディレクトリを作成できない: {args.output} ({e})", file=sys.stderr)
        sys.exit(1)

    # フォント導入チェック（quality warning。プロセスは続行する）
    check_fonts(args.font)

    try:
        pages = generate_pdf(
            input_md=args.input,
            output_pdf=args.output,
            margin=args.margin,
            font_size=args.font_size,
            font=args.font,
            style=args.style,
            page_breaks=args.page_break_before,
            custom_css=args.css,
            title=args.title,
            cover_title=args.cover_title,
            cover_subtitle=args.cover_subtitle,
            cover_author=args.cover_author,
            cover_date=args.cover_date,
            cover_logo=args.cover_logo,
            allow_http=args.allow_http,
            allow_local=args.allow_local,
        )
    except ImportError as e:
        print(
            f"エラー: 必要なライブラリが未導入: {e}\n"
            f"  対策: pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(2)
    except FileNotFoundError as e:
        print(f"エラー: ファイルが見つからない: {e}", file=sys.stderr)
        sys.exit(2)
    except PermissionError as e:
        print(f"エラー: 書き込み権限なし: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        # weasyprint の内部エラーはメッセージが長くなりがちなので、type も付けて診断しやすくする
        print(
            f"エラー: PDF 生成失敗 ({type(e).__name__}): {e}\n"
            f"  入力: {args.input}\n"
            f"  スタイル: {args.style} / プリセット: {args.preset or '(なし)'}",
            file=sys.stderr,
        )
        sys.exit(2)

    if pages > 0:
        print(f"PDF生成完了: {args.output} ({pages}ページ)")
    else:
        print(f"PDF生成完了: {args.output}")


if __name__ == '__main__':
    main()
