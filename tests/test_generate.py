#!/usr/bin/env python3
"""Tests for the alias phase of generate.py: fail-fast and art caching."""

import io
import json
from pathlib import Path
from typing import Dict, Optional

import pytest
from PIL import Image

from card_downloader import YugiohCardDownloader
from generate import CardRegenerator

from test_card_downloader import FakeSession, StubResponse


def make_jpeg_bytes(width: int = 177, height: int = 254) -> bytes:
    """
    Build a valid in-memory JPEG so the overlay code has real art to work on.

    Args:
        width: Image width in pixels
        height: Image height in pixels

    Returns:
        JPEG-encoded image bytes.
    """
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (10, 20, 30)).save(buffer, format='JPEG')
    return buffer.getvalue()


def build_regenerator(
    tmp_path: Path,
    alias_map: Dict,
    local_alias_codes: Optional[list] = None,
    cache_alias_images: bool = True,
    strict: bool = False,
) -> CardRegenerator:
    """
    Build a CardRegenerator over temporary fixture files.

    Args:
        tmp_path: pytest temporary directory
        alias_map: Content for alias.json
        local_alias_codes: Alias codes to pre-seed into alias_images/
        cache_alias_images: Whether fetched art should be persisted
        strict: Whether an unresolvable alias should fail the build

    Returns:
        A configured CardRegenerator with an offline fake session.
    """
    cards_path = tmp_path / 'cards.json'
    cards_path.write_text(
        json.dumps([{'code': 1001, 'name': 'Test Card', 'points': 5}]),
        encoding='utf-8',
    )

    alias_path = tmp_path / 'alias.json'
    alias_path.write_text(json.dumps(alias_map), encoding='utf-8')

    images_dir = tmp_path / 'alias_images'
    images_dir.mkdir()
    for code in local_alias_codes or []:
        (images_dir / f'{code}.jpg').write_bytes(make_jpeg_bytes())

    regenerator = CardRegenerator(
        cards_path=str(cards_path),
        alias_path=str(alias_path),
        alias_images_dir=str(images_dir),
        output_dir=str(tmp_path / 'generated_cards'),
        delay=0.0,
        generation='alias',
        cache_alias_images=cache_alias_images,
        strict=strict,
    )
    regenerator.downloader.session = FakeSession()
    return regenerator


class TestProcessAliasCards:
    """Covers remote fallback, caching and the new build-failure behaviour."""

    def test_uses_committed_art_without_touching_the_network(self, tmp_path: Path):
        regenerator = build_regenerator(tmp_path, {'1001': ['1002']}, local_alias_codes=['1002'])

        regenerator.process_alias_cards()

        assert (tmp_path / 'generated_cards' / '1002.jpg').exists()
        assert regenerator.downloader.session.requested_urls == []

    def test_downloads_missing_art_and_caches_it_locally(self, tmp_path: Path):
        regenerator = build_regenerator(tmp_path, {'1001': ['1002']})
        ignis = YugiohCardDownloader.ALIAS_IMAGE_URLS[0]
        art = make_jpeg_bytes()
        regenerator.downloader.session = FakeSession({f'{ignis}/1002.jpg': StubResponse(art)})

        regenerator.process_alias_cards()

        assert (tmp_path / 'generated_cards' / '1002.jpg').exists()
        assert (tmp_path / 'alias_images' / '1002.jpg').read_bytes() == art

    def test_no_cache_flag_skips_persisting_fetched_art(self, tmp_path: Path):
        regenerator = build_regenerator(tmp_path, {'1001': ['1002']}, cache_alias_images=False)
        ignis = YugiohCardDownloader.ALIAS_IMAGE_URLS[0]
        regenerator.downloader.session = FakeSession(
            {f'{ignis}/1002.jpg': StubResponse(make_jpeg_bytes())}
        )

        regenerator.process_alias_cards()

        assert (tmp_path / 'generated_cards' / '1002.jpg').exists()
        assert not (tmp_path / 'alias_images' / '1002.jpg').exists()

    def test_unresolvable_alias_is_recorded_without_failing_the_build(self, tmp_path: Path):
        """
        A pack is 954 independent files, not one atomic archive: a card whose
        art no source carries degrades on its own (EDOPro falls back to the
        unbadged art it downloads itself) and must not withhold every other
        card. So the default run reports the miss and still exits cleanly.
        """
        regenerator = build_regenerator(tmp_path, {'1001': ['1002']})

        regenerator.process_alias_cards()

        assert regenerator.failed_alias_codes == ['1002']

    def test_strict_mode_fails_the_build_on_an_unresolvable_alias(self, tmp_path: Path):
        regenerator = build_regenerator(tmp_path, {'1001': ['1002']}, strict=True)

        with pytest.raises(SystemExit) as excinfo:
            regenerator.process_alias_cards()

        assert excinfo.value.code == 1

    def test_every_reachable_alias_is_generated_despite_a_miss(self, tmp_path: Path):
        regenerator = build_regenerator(
            tmp_path, {'1001': ['1002', '1003']}, local_alias_codes=['1002']
        )

        regenerator.process_alias_cards()

        assert (tmp_path / 'generated_cards' / '1002.jpg').exists()
        assert not (tmp_path / 'generated_cards' / '1003.jpg').exists()
        assert regenerator.failed_alias_codes == ['1003']

    def test_run_regeneration_reports_misses_last(self, tmp_path: Path, capsys):
        """The warning must be the final thing printed, not buried above the banner."""
        regenerator = build_regenerator(tmp_path, {'1001': ['1002']})

        regenerator.run_regeneration()

        tail = capsys.readouterr().out.strip().splitlines()[-1]
        assert '1002' in tail or 'alias' in tail.lower()
