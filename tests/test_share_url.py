"""Share-link URL construction (no database)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes.share import share_url  # noqa: E402
from app.core.config import Settings  # noqa: E402


def _settings(**over) -> Settings:
    # _env_file=None: the developer's local .env must not leak into the test.
    return Settings(_env_file=None, **over)


def test_share_base_url_wins_and_keeps_path_prefix():
    s = _settings(
        cors_origins="https://www.admitverse.com,http://localhost:3000",
        share_base_url="https://www.admitverse.com/mock/",
    )
    assert share_url(s, "tok") == "https://www.admitverse.com/mock/share/tok"


def test_falls_back_to_first_cors_origin():
    s = _settings(cors_origins="https://mock.admitverse.com/, http://localhost:3000")
    assert share_url(s, "tok") == "https://mock.admitverse.com/share/tok"


def test_falls_back_to_localhost_without_origins():
    s = _settings(cors_origins="")
    assert share_url(s, "tok") == "http://localhost:3000/share/tok"
