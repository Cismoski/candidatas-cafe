"""MAPBIOMAS_URL: erro de configuração aparece na subida, não como "indisponível"."""

import pytest
from pydantic import ValidationError

from tests.api.conftest import make_settings


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://storage.googleapis.com/x/brazil_coverage-col11_{year}.tif",
    ],
)
def test_valid(tmp_path, url):
    assert make_settings(tmp_path, mapbiomas_url=url).mapbiomas_url == url


@pytest.mark.parametrize(
    ("url", "msg"),
    [
        ("http://storage.googleapis.com/x_{year}.tif", "https"),
        ("/vsis3/bucket/x_{year}.tif", "https"),
        ("file:///etc/passwd", "https"),
        ("https://storage.googleapis.com/x_2025.tif", "{year}"),
        ("https://storage.googleapis.com/x_{year}_{ano}.tif", "só pode ter"),
        ("https://storage.googleapis.com/x_{0}.tif", "só pode ter"),
    ],
)
def test_invalid(tmp_path, url, msg):
    with pytest.raises(ValidationError, match=msg):
        make_settings(tmp_path, mapbiomas_url=url)
