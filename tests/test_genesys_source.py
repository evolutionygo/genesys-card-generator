#!/usr/bin/env python3
"""Tests for the shared Genesys source reader in genesys_source.py."""

import json
from pathlib import Path

import genesys_source

CONF_SAMPLE = """#[Genesys]
#created by the Genesys team
!Genesys
83764719 3 20 --Monster Reborn
10443957 3 15 --Change of Heart
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


class TestLoadCardEntries:
    """Covers reading both the upstream .conf and the legacy .json source."""

    def test_reads_code_points_and_name_from_a_conf(self, tmp_path: Path):
        conf_path = write_conf(tmp_path, CONF_SAMPLE)

        entries = genesys_source.load_card_entries(conf_path)

        assert entries == [
            {'code': 83764719, 'points': 20, 'name': 'Monster Reborn'},
            {'code': 10443957, 'points': 15, 'name': 'Change of Heart'},
        ]

    def test_ignores_lines_outside_the_genesys_section(self, tmp_path: Path):
        conf_path = write_conf(
            tmp_path,
            '!Forbidden\n'
            '99999999 3 10 --Not Genesys\n'
            '!Genesys\n'
            '10443957 3 15 --Change of Heart\n',
        )

        entries = genesys_source.load_card_entries(conf_path)

        assert [entry['code'] for entry in entries] == [10443957]

    def test_ignores_comment_lines(self, tmp_path: Path):
        conf_path = write_conf(
            tmp_path,
            '!Genesys\n'
            '#10443957 3 15 --Commented out\n'
            '83764719 3 20 --Monster Reborn\n',
        )

        entries = genesys_source.load_card_entries(conf_path)

        assert [entry['code'] for entry in entries] == [83764719]

    def test_skips_a_line_whose_left_side_is_not_three_parts(self, tmp_path: Path):
        conf_path = write_conf(
            tmp_path,
            '!Genesys\n'
            '10443957 3 --Missing the points column\n'
            '10443957 3 15 20 --Too many columns\n'
            '83764719 3 20 --Monster Reborn\n',
        )

        entries = genesys_source.load_card_entries(conf_path)

        assert [entry['code'] for entry in entries] == [83764719]

    def test_skips_a_line_without_a_name_separator(self, tmp_path: Path):
        conf_path = write_conf(tmp_path, '!Genesys\n10443957 3 15\n83764719 3 20 --Monster Reborn\n')

        entries = genesys_source.load_card_entries(conf_path)

        assert [entry['code'] for entry in entries] == [83764719]

    def test_reads_a_json_source(self, tmp_path: Path):
        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(
            json.dumps([{'name': 'Change of Heart', 'points': 15, 'code': 10443957}]),
            encoding='utf-8',
        )

        entries = genesys_source.load_card_entries(cards_path)

        assert entries == [{'code': 10443957, 'points': 15, 'name': 'Change of Heart'}]

    def test_matches_the_conf_suffix_case_insensitively(self, tmp_path: Path):
        conf_path = write_conf(tmp_path, CONF_SAMPLE, name='genesys.lflist.CONF')

        entries = genesys_source.load_card_entries(conf_path)

        assert [entry['code'] for entry in entries] == [83764719, 10443957]
