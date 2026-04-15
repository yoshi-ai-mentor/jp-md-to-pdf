import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'convert.py'
SPEC = importlib.util.spec_from_file_location('jp_md_to_pdf_convert', MODULE_PATH)
convert = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(convert)


def test_build_html_escapes_raw_html_by_default():
    rendered = convert.build_html(
        '# 見出し\n\n<script>alert(1)</script>',
        'body {}',
    )

    assert '<script>alert(1)</script>' not in rendered
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in rendered


def test_build_html_keeps_page_break_placeholder_working():
    rendered = convert.build_html(
        '## 第2キャリア',
        'body {}',
        page_breaks=['## 第2キャリア'],
    )

    assert '<div class="page-break"></div>' in rendered
    assert convert.PAGE_BREAK_PLACEHOLDER not in rendered


def test_build_html_escapes_title_metadata():
    rendered = convert.build_html('本文', 'body {}', title='<unsafe>')

    assert '<title>&lt;unsafe&gt;</title>' in rendered


def test_validate_margin_rejects_css_injection():
    with pytest.raises(ValueError, match='--margin'):
        convert.validate_margin('6mm; background:url(https://example.com)')


def test_validate_font_size_accepts_point_values_only():
    assert convert.validate_font_size('10pt') == '10pt'

    with pytest.raises(ValueError, match='--font-size'):
        convert.validate_font_size('10px')


def test_validate_font_arg_allows_safe_custom_family():
    font = "'Hiragino Sans', sans-serif"

    assert convert.validate_font_arg(font) == font


def test_validate_font_arg_rejects_css_injection():
    with pytest.raises(ValueError, match='--font'):
        convert.validate_font_arg("evil; background:url('https://example.com')")


def test_validate_css_path_requires_local_css_file(tmp_path):
    css_file = tmp_path / 'custom.css'
    css_file.write_text('body {}', encoding='utf-8')

    assert convert.validate_css_path(str(css_file)) == str(css_file.resolve())

    with pytest.raises(ValueError, match='--css'):
        convert.validate_css_path(str(tmp_path / 'custom.txt'))


def test_validate_logo_path_none():
    assert convert.validate_logo_path(None) is None


def test_validate_logo_path_accepts_png_jpg_svg_gif(tmp_path):
    for name in ('a.png', 'b.jpg', 'c.jpeg', 'd.svg', 'e.gif'):
        p = tmp_path / name
        p.write_bytes(b'x')
        assert convert.validate_logo_path(str(p)) == str(p.resolve())


def test_validate_logo_path_rejects_missing_file(tmp_path):
    missing = tmp_path / 'nope.png'

    with pytest.raises(ValueError, match='見つからない'):
        convert.validate_logo_path(str(missing))


def test_validate_logo_path_rejects_bad_extension(tmp_path):
    p = tmp_path / 'logo.webp'
    p.write_bytes(b'x')

    with pytest.raises(ValueError, match='png'):
        convert.validate_logo_path(str(p))


def test_validate_logo_path_rejects_oversized_file(tmp_path):
    p = tmp_path / 'big.png'
    p.write_bytes(b'x' * (convert.MAX_COVER_LOGO_BYTES + 1))

    with pytest.raises(ValueError, match='2MB'):
        convert.validate_logo_path(str(p))


@pytest.mark.parametrize(
    'bad',
    ['https://example.com/x.png', 'http://a/x.png', 'file:///tmp/x.png', 'data:image/png;base64,QQ==', '//evil/x.png'],
)
def test_validate_logo_path_rejects_urls(bad):
    with pytest.raises(ValueError, match='ローカルファイル'):
        convert.validate_logo_path(bad)


def test_build_cover_html_inserts_base64_logo(tmp_path):
    svg = tmp_path / 'logo.svg'
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>',
        encoding='utf-8',
    )
    resolved = convert.validate_logo_path(str(svg))
    html = convert.build_cover_html(cover_title='T', cover_logo=resolved)

    assert 'class="cover-logo"' in html
    assert 'data:image/svg+xml;base64,' in html
    assert html.index('cover-logo') < html.index('cover-title')


def test_validate_css_path_rejects_oversized_file(tmp_path):
    css_file = tmp_path / 'huge.css'
    css_file.write_text('a' * (convert.MAX_CUSTOM_CSS_BYTES + 1), encoding='utf-8')

    with pytest.raises(ValueError, match='256KB'):
        convert.validate_css_path(str(css_file))


@pytest.mark.parametrize('host', ['100.64.0.1', '198.18.0.1'])
def test_resolve_public_http_address_rejects_special_use_ranges(host):
    with pytest.raises(ValueError, match='private / localhost'):
        convert.resolve_public_http_address(host)


def test_safe_url_fetcher_blocks_http_without_opt_in():
    fetcher = convert.build_safe_url_fetcher(False, False, url_fetcher=lambda *args, **kwargs: {})

    with pytest.raises(ValueError, match='--allow-http'):
        fetcher('https://example.com/logo.png')


def test_safe_url_fetcher_blocks_local_without_opt_in():
    fetcher = convert.build_safe_url_fetcher(False, False, url_fetcher=lambda *args, **kwargs: {})

    with pytest.raises(ValueError, match='--allow-local'):
        fetcher('file:///tmp/logo.png')


def test_safe_url_fetcher_blocks_localhost_even_when_http_enabled():
    fetcher = convert.build_safe_url_fetcher(True, False, url_fetcher=lambda *args, **kwargs: {})

    with pytest.raises(ValueError, match='private / localhost'):
        fetcher('http://localhost/logo.png')


def test_safe_url_fetcher_blocks_local_path_outside_allowed_roots(tmp_path):
    allowed_dir = tmp_path / 'allowed'
    outside_dir = tmp_path / 'outside'
    allowed_dir.mkdir()
    outside_dir.mkdir()
    target = outside_dir / 'secret.txt'
    target.write_text('secret', encoding='utf-8')
    fetcher = convert.build_safe_url_fetcher(
        False,
        True,
        allowed_local_roots=[allowed_dir],
        url_fetcher=lambda *args, **kwargs: {},
    )

    with pytest.raises(ValueError, match='許可されていないローカルパス'):
        fetcher(target.resolve().as_uri())


def test_safe_url_fetcher_allows_local_path_within_allowed_roots(tmp_path):
    allowed_dir = tmp_path / 'allowed'
    allowed_dir.mkdir()
    target = allowed_dir / 'asset.txt'
    target.write_text('asset', encoding='utf-8')
    captured = {}

    def fake_fetcher(url, **kwargs):
        captured['url'] = url
        return {'url': url}

    fetcher = convert.build_safe_url_fetcher(
        False,
        True,
        allowed_local_roots=[allowed_dir],
        url_fetcher=fake_fetcher,
    )
    result = fetcher(target.resolve().as_uri())

    assert captured['url'] == target.resolve().as_uri()
    assert result == {'url': target.resolve().as_uri()}


def test_safe_url_fetcher_uses_wrapped_fetcher_for_allowed_protocol():
    captured = {}
    local_calls = {'count': 0}

    def fake_fetcher(url, **kwargs):
        local_calls['count'] += 1
        return {'url': url}

    def fake_http_fetcher(url, **kwargs):
        captured['url'] = url
        captured['kwargs'] = kwargs
        return {'url': url}

    fetcher = convert.build_safe_url_fetcher(
        True,
        False,
        url_fetcher=fake_fetcher,
        http_fetcher=fake_http_fetcher,
    )
    result = fetcher('https://example.com/logo.png', timeout=3)

    assert captured['url'] == 'https://example.com/logo.png'
    assert captured['kwargs']['timeout'] == 3
    assert local_calls['count'] == 0
    assert result == {'url': 'https://example.com/logo.png'}


def test_safe_url_fetcher_rejects_oversized_http_payload():
    def fake_http_fetcher(*args, **kwargs):
        return {'string': b'a' * (convert.MAX_FETCHED_RESOURCE_BYTES + 1)}

    fetcher = convert.build_safe_url_fetcher(
        True,
        False,
        url_fetcher=lambda *args, **kwargs: {},
        http_fetcher=fake_http_fetcher,
    )

    with pytest.raises(ValueError, match='取得リソースが大きすぎる'):
        fetcher('https://example.com/logo.png')


def test_fetch_http_resource_revalidates_redirect_targets(monkeypatch):
    connection_attempts = []

    class FakeResponse:
        status = 302
        reason = 'Found'
        headers = None

        def getheader(self, name, default=None):
            if name.lower() == 'location':
                return 'http://localhost/admin'
            return default

        def read(self, *args, **kwargs):
            return b''

    class FakeConnection:
        def __init__(self, host, pinned_ip, port, timeout):
            connection_attempts.append((host, pinned_ip, port, timeout))

        def request(self, method, path, headers=None):
            return None

        def getresponse(self):
            return FakeResponse()

        def close(self):
            return None

    def fake_resolve(hostname, port=None):
        if hostname == 'example.com':
            return '93.184.216.34'
        raise ValueError(f'private / localhost 宛てのURLは許可していない: {hostname}')

    monkeypatch.setattr(convert, 'resolve_public_http_address', fake_resolve)
    monkeypatch.setattr(convert, 'PinnedHTTPConnection', FakeConnection)

    with pytest.raises(ValueError, match='private / localhost'):
        convert.fetch_http_resource('http://example.com/logo.png')

    assert connection_attempts == [('example.com', '93.184.216.34', 80, 10)]
