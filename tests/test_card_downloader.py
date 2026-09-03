#!/usr/bin/env python3
"""Tests for the alias art source fallback chain in card_downloader.py."""

from pathlib import Path
from typing import Dict, List, Optional

import pytest
import requests

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


@pytest.fixture
def downloader(tmp_path: Path) -> YugiohCardDownloader:
    """A downloader wired to a temp output dir and an offline fake session."""
    instance = YugiohCardDownloader(output_dir=str(tmp_path / 'out'))
    instance.session = FakeSession()
    return instance


class TestAliasImageUrls:
    """Covers the declared source order."""

    def test_ignis_is_tried_before_momobako(self):
        assert YugiohCardDownloader.ALIAS_IMAGE_URLS == (
            'https://pics.projectignis.org:2096/pics',
            'https://cdn.233.momobako.com/ygopro/pics',
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

    def test_falls_through_to_the_second_mirror_on_a_miss(
        self, downloader: YugiohCardDownloader
    ):
        ignis, momobako = YugiohCardDownloader.ALIAS_IMAGE_URLS
        downloader.session = FakeSession(
            {f'{momobako}/1002.jpg': StubResponse(b'momobako-art')}
        )

        result = downloader.fetch_alias_image('1002')

        assert result == (b'momobako-art', momobako)
        assert downloader.session.requested_urls == [
            f'{ignis}/1002.jpg',
            f'{momobako}/1002.jpg',
        ]

    def test_returns_none_when_every_source_misses(self, downloader: YugiohCardDownloader):
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

    def test_empty_body_is_treated_as_a_miss(self, downloader: YugiohCardDownloader):
        ignis, momobako = YugiohCardDownloader.ALIAS_IMAGE_URLS
        downloader.session = FakeSession(
            {
                f'{ignis}/1002.jpg': StubResponse(b''),
                f'{momobako}/1002.jpg': StubResponse(b'momobako-art'),
            }
        )

        result = downloader.fetch_alias_image('1002')

        assert result == (b'momobako-art', momobako)

    def test_a_raising_mirror_does_not_abort_the_chain(
        self, downloader: YugiohCardDownloader
    ):
        ignis, momobako = YugiohCardDownloader.ALIAS_IMAGE_URLS

        class ExplodingSession(FakeSession):
            def get(self, url: str, timeout: int = 0) -> StubResponse:
                self.requested_urls.append(url)
                if url.startswith(ignis):
                    raise requests.exceptions.ConnectionError('dead mirror')
                return StubResponse(b'momobako-art')

        downloader.session = ExplodingSession()

        result = downloader.fetch_alias_image('1002')

        assert result == (b'momobako-art', momobako)
