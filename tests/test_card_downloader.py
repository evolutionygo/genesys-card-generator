#!/usr/bin/env python3
"""Tests for the alias art source fallback chain in card_downloader.py."""

import io
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import requests
from PIL import Image

from card_downloader import YugiohCardDownloader


class StubResponse:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, content: bytes = b'', status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        """Raise for any 4xx/5xx status, mirroring requests behaviour."""
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f'{self.status_code} error')


class FakeSession:
    """Records requested URLs and replies from a canned routing table."""

    def __init__(self, responses: Optional[Dict[str, StubResponse]] = None):
        self.responses = responses or {}
        self.requested_urls: List[str] = []

    def get(self, url: str, timeout: int = 0) -> StubResponse:
        """Return the canned response for url, or a 404 stub."""
        self.requested_urls.append(url)
        if url in self.responses:
            return self.responses[url]
        return StubResponse(b'', 404)


PRIMARY_SOURCE = 'https://primary.example/pics'
SECONDARY_SOURCE = 'https://secondary.example/pics'


@pytest.fixture
def two_sources(monkeypatch: pytest.MonkeyPatch) -> Tuple[str, str]:
    """Patch ALIAS_IMAGE_URLS with two sources to exercise fallback ordering."""
    monkeypatch.setattr(
        YugiohCardDownloader, 'ALIAS_IMAGE_URLS', (PRIMARY_SOURCE, SECONDARY_SOURCE)
    )
    return PRIMARY_SOURCE, SECONDARY_SOURCE


@pytest.fixture
def downloader(tmp_path: Path) -> YugiohCardDownloader:
    """A downloader wired to a temp output dir and an offline fake session."""
    instance = YugiohCardDownloader(output_dir=str(tmp_path / 'out'))
    instance.session = FakeSession()
    return instance


class TestAliasImageUrls:
    """Covers the declared source order."""

    def test_project_ignis_is_the_only_source(self):
        assert YugiohCardDownloader.ALIAS_IMAGE_URLS == (
            'https://pics.projectignis.org:2096/pics',
        )

    def test_base_image_url_is_unchanged(self):
        assert YugiohCardDownloader.BASE_IMAGE_URL == 'https://images.ygoprodeck.com/images/cards'


class TestFetchAliasImage:
    """Covers local cache short-circuit, mirror order, fallback and misses."""

    def test_local_file_short_circuits_the_network(
        self, downloader: YugiohCardDownloader, tmp_path: Path
    ):
        local_dir = tmp_path / 'alias_images'
        local_dir.mkdir()
        (local_dir / '1002.jpg').write_bytes(b'local-art')

        result = downloader.fetch_alias_image('1002', local_dir=local_dir)

        assert result is not None
        image_data, source = result
        assert image_data == b'local-art'
        assert source == YugiohCardDownloader.LOCAL_ALIAS_SOURCE
        assert downloader.session.requested_urls == []

    def test_first_mirror_wins(self, downloader: YugiohCardDownloader):
        ignis = YugiohCardDownloader.ALIAS_IMAGE_URLS[0]
        downloader.session = FakeSession({f'{ignis}/1002.jpg': StubResponse(b'ignis-art')})

        result = downloader.fetch_alias_image('1002')

        assert result == (b'ignis-art', ignis)
        assert downloader.session.requested_urls == [f'{ignis}/1002.jpg']

    def test_falls_through_to_the_second_source_on_a_miss(
        self, downloader: YugiohCardDownloader, two_sources: Tuple[str, str]
    ):
        primary, secondary = two_sources
        downloader.session = FakeSession(
            {f'{secondary}/1002.jpg': StubResponse(b'secondary-art')}
        )

        result = downloader.fetch_alias_image('1002')

        assert result == (b'secondary-art', secondary)
        assert downloader.session.requested_urls == [
            f'{primary}/1002.jpg',
            f'{secondary}/1002.jpg',
        ]

    def test_returns_none_when_every_source_misses(
        self, downloader: YugiohCardDownloader, two_sources: Tuple[str, str]
    ):
        assert downloader.fetch_alias_image('1002') is None
        assert len(downloader.session.requested_urls) == 2

    def test_missing_local_file_still_falls_back_to_the_network(
        self, downloader: YugiohCardDownloader, tmp_path: Path
    ):
        local_dir = tmp_path / 'alias_images'
        local_dir.mkdir()
        ignis = YugiohCardDownloader.ALIAS_IMAGE_URLS[0]
        downloader.session = FakeSession({f'{ignis}/1002.jpg': StubResponse(b'ignis-art')})

        result = downloader.fetch_alias_image('1002', local_dir=local_dir)

        assert result == (b'ignis-art', ignis)

    def test_empty_body_is_treated_as_a_miss(
        self, downloader: YugiohCardDownloader, two_sources: Tuple[str, str]
    ):
        primary, secondary = two_sources
        downloader.session = FakeSession(
            {
                f'{primary}/1002.jpg': StubResponse(b''),
                f'{secondary}/1002.jpg': StubResponse(b'secondary-art'),
            }
        )

        result = downloader.fetch_alias_image('1002')

        assert result == (b'secondary-art', secondary)

    def test_a_raising_source_does_not_abort_the_chain(
        self, downloader: YugiohCardDownloader, two_sources: Tuple[str, str]
    ):
        primary, secondary = two_sources

        class ExplodingSession(FakeSession):
            def get(self, url: str, timeout: int = 0) -> StubResponse:
                self.requested_urls.append(url)
                if url.startswith(primary):
                    raise requests.exceptions.ConnectionError('dead source')
                return StubResponse(b'secondary-art')

        downloader.session = ExplodingSession()

        result = downloader.fetch_alias_image('1002')

        assert result == (b'secondary-art', secondary)

    def test_single_source_miss_returns_none_after_one_request(
        self, downloader: YugiohCardDownloader
    ):
        assert downloader.fetch_alias_image('1002') is None
        assert downloader.session.requested_urls == [
            f'{YugiohCardDownloader.ALIAS_IMAGE_URLS[0]}/1002.jpg'
        ]


def make_jpeg(color: Tuple[int, int, int]) -> bytes:
    """
    Build a tiny valid JPEG so image validation has real art to accept.

    Args:
        color: RGB fill colour, varied so two images differ byte-wise

    Returns:
        JPEG-encoded image bytes.
    """
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), color).save(buffer, format='JPEG')
    return buffer.getvalue()


JPEG = make_jpeg((10, 20, 30))
OTHER_JPEG = make_jpeg((200, 100, 50))
IGNIS_PRERELEASE = 'https://pics.projectignis.org:2096/pics/101402090.jpg'
YGOPRODECK_PRERELEASE = 'https://images.ygoprodeck.com/images/cards/101402090.jpg'


class TestBaseImageUrls:
    """Base art sources: YGOPRODeck, with Project Ignis first for prerelease codes."""

    def test_official_code_uses_only_ygoprodeck(self, downloader: YugiohCardDownloader):
        assert downloader.base_image_urls('50284408') == [
            'https://images.ygoprodeck.com/images/cards/50284408.jpg'
        ]

    def test_prerelease_code_tries_project_ignis_then_ygoprodeck(
        self, downloader: YugiohCardDownloader
    ):
        assert downloader.base_image_urls(101402090) == [
            IGNIS_PRERELEASE,
            YGOPRODECK_PRERELEASE,
        ]

    def test_threshold_is_the_first_nine_digit_code(self, downloader: YugiohCardDownloader):
        assert len(downloader.base_image_urls('99999999')) == 1
        assert len(downloader.base_image_urls('100000000')) == 2

    def test_non_numeric_code_does_not_raise(self, downloader: YugiohCardDownloader):
        assert downloader.base_image_urls('abc') == [
            'https://images.ygoprodeck.com/images/cards/abc.jpg'
        ]


class TestFetchBaseImage:
    """Base art fetch walks the ordered sources and survives a dead mirror."""

    def test_prerelease_prefers_project_ignis(self, downloader: YugiohCardDownloader):
        downloader.session = FakeSession({IGNIS_PRERELEASE: StubResponse(JPEG)})
        assert downloader.fetch_base_image(101402090) == JPEG
        assert downloader.session.requested_urls == [IGNIS_PRERELEASE]

    def test_prerelease_falls_back_to_ygoprodeck_on_a_miss(
        self, downloader: YugiohCardDownloader
    ):
        downloader.session = FakeSession(
            {YGOPRODECK_PRERELEASE: StubResponse(OTHER_JPEG)}
        )
        assert downloader.fetch_base_image(101402090) == OTHER_JPEG
        assert downloader.session.requested_urls == [IGNIS_PRERELEASE, YGOPRODECK_PRERELEASE]

    def test_a_raising_source_falls_through(self, downloader: YugiohCardDownloader):
        class ExplodingIgnis(FakeSession):
            def get(self, url: str, timeout: int = 0) -> StubResponse:
                if url == IGNIS_PRERELEASE:
                    self.requested_urls.append(url)
                    raise requests.exceptions.ConnectionError('port 2096 blocked')
                return super().get(url, timeout)

        downloader.session = ExplodingIgnis({YGOPRODECK_PRERELEASE: StubResponse(JPEG)})
        assert downloader.fetch_base_image(101402090) == JPEG

    def test_empty_body_is_treated_as_a_miss(self, downloader: YugiohCardDownloader):
        downloader.session = FakeSession(
            {IGNIS_PRERELEASE: StubResponse(b''), YGOPRODECK_PRERELEASE: StubResponse(JPEG)}
        )
        assert downloader.fetch_base_image(101402090) == JPEG

    def test_non_image_body_falls_back_to_ygoprodeck(self, downloader: YugiohCardDownloader):
        downloader.session = FakeSession(
            {
                IGNIS_PRERELEASE: StubResponse(b'<html>placeholder</html>'),
                YGOPRODECK_PRERELEASE: StubResponse(JPEG),
            }
        )
        assert downloader.fetch_base_image(101402090) == JPEG
        assert downloader.session.requested_urls == [IGNIS_PRERELEASE, YGOPRODECK_PRERELEASE]

    def test_returns_none_when_every_source_misses(self, downloader: YugiohCardDownloader):
        assert downloader.fetch_base_image(101402090) is None

    def test_download_card_image_uses_the_fallback(
        self, downloader: YugiohCardDownloader, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(downloader, 'add_points_overlay', lambda data, points: data)
        downloader.session = FakeSession({YGOPRODECK_PRERELEASE: StubResponse(JPEG)})
        assert downloader.download_card_image({'code': 101402090, 'points': 20})
        assert (downloader.output_dir / '101402090.jpg').read_bytes() == JPEG

    def test_download_card_image_reports_a_total_miss(self, downloader: YugiohCardDownloader):
        assert not downloader.download_card_image({'code': 101402090, 'points': 20})
