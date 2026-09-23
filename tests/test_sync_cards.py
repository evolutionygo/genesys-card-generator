#!/usr/bin/env python3
"""Tests for the cards.json generation logic in sync_cards.py."""

import json
from pathlib import Path

import genesys_source
import sync_cards

CONF_SAMPLE = """#[Genesys]
#created by the Genesys team
!Genesys
10443957 3 15 --Change of Heart
83764719 3 20 --Monster Reborn
"""


def write_conf(tmp_path: Path, content: str, name: str = 'genesys.lflist.conf') -> Path:
    """
    Write a Genesys lflist.conf fixture.

    Args:
        tmp_path: pytest temporary directory
        content: The raw file content
        name: File name to write

    Returns:
        The path of the written file.
    """
    conf_path = tmp_path / name
    conf_path.write_text(content, encoding='utf-8')
    return conf_path


class TestBuildCardsPayload:
    """Covers the pure derivation of cards.json content from Genesys entries."""

    def test_maps_entries_to_the_cards_json_shape(self):
        entries = [{'code': 1001, 'points': 5, 'name': 'Alpha'}]

        result = sync_cards.build_cards_payload(entries)

        assert result == [{'name': 'Alpha', 'points': 5, 'code': 1001}]

    def test_preserves_the_cards_json_key_order(self):
        entries = [{'code': 1001, 'points': 5, 'name': 'Alpha'}]

        result = sync_cards.build_cards_payload(entries)

        assert list(result[0].keys()) == ['name', 'points', 'code']

    def test_sorts_by_code_ascending(self):
        entries = [
            {'code': 30000001, 'points': 5, 'name': 'Gamma'},
            {'code': 2000001, 'points': 5, 'name': 'Alpha'},
            {'code': 100000001, 'points': 5, 'name': 'Beta'},
        ]

        result = sync_cards.build_cards_payload(entries)

        assert [card['code'] for card in result] == [2000001, 30000001, 100000001]

    def test_normalizes_codes_and_points_to_int(self):
        entries = [{'code': '1001', 'points': '5', 'name': 'Alpha'}]

        result = sync_cards.build_cards_payload(entries)

        assert result == [{'name': 'Alpha', 'points': 5, 'code': 1001}]

    def test_accepts_any_iterable_of_entries(self):
        entries = iter([{'code': 1001, 'points': 5, 'name': 'Alpha'}])

        result = sync_cards.build_cards_payload(entries)

        assert result == [{'name': 'Alpha', 'points': 5, 'code': 1001}]

    def test_payload_round_trips_through_genesys_source(self, tmp_path: Path):
        """What sync_cards writes must be readable by every downstream consumer."""
        conf_path = write_conf(tmp_path, CONF_SAMPLE)
        entries = genesys_source.load_card_entries(conf_path)

        payload = sync_cards.build_cards_payload(entries)

        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(json.dumps(payload), encoding='utf-8')
        reloaded = genesys_source.load_card_entries(cards_path)

        assert sync_cards.build_cards_payload(reloaded) == payload


class TestDiffCards:
    """Covers the comparison between the cards.json on disk and the new payload."""

    def test_reports_added_cards(self):
        current = [{'name': 'Alpha', 'points': 5, 'code': 1001}]
        generated = [
            {'name': 'Alpha', 'points': 5, 'code': 1001},
            {'name': 'Beta', 'points': 7, 'code': 1002},
        ]

        diff = sync_cards.diff_cards(current, generated)

        assert diff['added'] == {1002: 'Beta'}
        assert diff['removed'] == {}
        assert diff['changed'] == {}
        assert diff['in_sync'] is False

    def test_reports_removed_cards(self):
        current = [
            {'name': 'Alpha', 'points': 5, 'code': 1001},
            {'name': 'Beta', 'points': 7, 'code': 1002},
        ]
        generated = [{'name': 'Alpha', 'points': 5, 'code': 1001}]

        diff = sync_cards.diff_cards(current, generated)

        assert diff['added'] == {}
        assert diff['removed'] == {1002: 'Beta'}
        assert diff['changed'] == {}

    def test_reports_a_point_change(self):
        current = [{'name': 'Alpha', 'points': 5, 'code': 1001}]
        generated = [{'name': 'Alpha', 'points': 40, 'code': 1001}]

        diff = sync_cards.diff_cards(current, generated)

        assert diff['changed'] == {1001: (5, 40)}
        assert diff['added'] == {}
        assert diff['removed'] == {}
        assert diff['in_sync'] is False

    def test_identical_input_reports_in_sync(self):
        cards = [
            {'name': 'Alpha', 'points': 5, 'code': 1001},
            {'name': 'Beta', 'points': 7, 'code': 1002},
        ]

        diff = sync_cards.diff_cards(cards, list(cards))

        assert diff['in_sync'] is True
        assert diff['added_count'] == 0
        assert diff['removed_count'] == 0
        assert diff['changed_count'] == 0

    def test_normalizes_codes_to_int_on_both_sides(self):
        current = [{'name': 'Alpha', 'points': '5', 'code': '1001'}]
        generated = [{'name': 'Alpha', 'points': 5, 'code': 1001}]

        diff = sync_cards.diff_cards(current, generated)

        assert diff['in_sync'] is True

    def test_counts_every_category(self):
        current = [
            {'name': 'Alpha', 'points': 5, 'code': 1001},
            {'name': 'Beta', 'points': 7, 'code': 1002},
        ]
        generated = [
            {'name': 'Alpha', 'points': 9, 'code': 1001},
            {'name': 'Gamma', 'points': 3, 'code': 1003},
        ]

        diff = sync_cards.diff_cards(current, generated)

        assert diff['added_count'] == 1
        assert diff['removed_count'] == 1
        assert diff['changed_count'] == 1


class TestCardSynchronizer:
    """Covers the end-to-end synchronizer against temporary files."""

    def _build_fixture(self, tmp_path: Path) -> sync_cards.CardSynchronizer:
        source_path = write_conf(tmp_path, CONF_SAMPLE)

        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(
            json.dumps([{'name': 'Change of Heart', 'points': 1, 'code': 10443957}]),
            encoding='utf-8',
        )

        return sync_cards.CardSynchronizer(
            source_path=source_path,
            cards_path=cards_path,
        )

    def test_check_only_does_not_write(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)
        before = (tmp_path / 'cards.json').read_text(encoding='utf-8')

        diff = synchronizer.sync(check_only=True)

        assert diff['in_sync'] is False
        assert (tmp_path / 'cards.json').read_text(encoding='utf-8') == before

    def test_sync_writes_the_generated_payload(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)

        diff = synchronizer.sync(check_only=False)

        written = json.loads((tmp_path / 'cards.json').read_text(encoding='utf-8'))
        assert written == [
            {'name': 'Change of Heart', 'points': 15, 'code': 10443957},
            {'name': 'Monster Reborn', 'points': 20, 'code': 83764719},
        ]
        assert diff['added'] == {83764719: 'Monster Reborn'}
        assert diff['changed'] == {10443957: (1, 15)}

    def test_written_file_uses_two_space_indent_and_trailing_newline(
        self, tmp_path: Path
    ):
        synchronizer = self._build_fixture(tmp_path)

        synchronizer.sync(check_only=False)

        content = (tmp_path / 'cards.json').read_text(encoding='utf-8')
        assert content.endswith('\n')
        assert '\t' not in content
        assert content.startswith('[\n  {\n    "name": ')

    def test_a_second_sync_reports_in_sync(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)
        synchronizer.sync(check_only=False)

        diff = synchronizer.sync(check_only=True)

        assert diff['in_sync'] is True

    def test_sync_treats_a_missing_cards_file_as_empty(self, tmp_path: Path):
        source_path = write_conf(tmp_path, CONF_SAMPLE)
        synchronizer = sync_cards.CardSynchronizer(
            source_path=source_path,
            cards_path=tmp_path / 'cards.json',
        )

        diff = synchronizer.sync(check_only=False)

        assert diff['added_count'] == 2
        assert (tmp_path / 'cards.json').exists()
