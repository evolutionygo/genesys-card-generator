#!/usr/bin/env python3
"""Tests for the alias synchronization logic in sync_alias.py."""

import json
import sqlite3
from pathlib import Path
from typing import List, Tuple

import pytest

import sync_alias


class TestBuildAliasMap:
    """Covers the pure derivation of alias.json content from database rows."""

    def test_groups_alias_ids_under_their_base_code(self):
        rows = [(1002, 1001), (1003, 1001), (2002, 2001)]
        codes = {1001, 2001}

        result = sync_alias.build_alias_map(rows, codes)

        assert result == {'1001': [1002, 1003], '2001': [2002]}

    def test_drops_rows_whose_base_code_is_not_a_genesys_card(self):
        rows = [(1002, 1001), (9002, 9001)]
        codes = {1001}

        result = sync_alias.build_alias_map(rows, codes)

        assert result == {'1001': [1002]}

    def test_drops_self_referencing_rows(self):
        rows = [(1001, 1001), (1002, 1001)]
        codes = {1001}

        result = sync_alias.build_alias_map(rows, codes)

        assert result == {'1001': [1002]}

    def test_sorts_values_ascending_and_removes_duplicates(self):
        rows = [(1005, 1001), (1002, 1001), (1005, 1001)]
        codes = {1001}

        result = sync_alias.build_alias_map(rows, codes)

        assert result['1001'] == [1002, 1005]

    def test_sorts_keys_ascending_numerically(self):
        rows = [(30000001, 30000000), (2000001, 2000000), (100000001, 100000000)]
        codes = {30000000, 2000000, 100000000}

        result = sync_alias.build_alias_map(rows, codes)

        assert list(result.keys()) == ['2000000', '30000000', '100000000']

    def test_accepts_any_iterable_of_rows(self):
        rows = iter([(1002, 1001)])
        codes = {1001}

        result = sync_alias.build_alias_map(rows, codes)

        assert result == {'1001': [1002]}


class TestDiffAliasMaps:
    """Covers the reporting used by --check and by the write summary."""

    def test_reports_added_ids(self):
        result = sync_alias.diff_alias_maps({'1001': ['1002']}, {'1001': [1002, 1003]})

        assert result['added'] == {'1001': [1003]}
        assert result['removed'] == {}
        assert result['in_sync'] is False

    def test_reports_removed_ids(self):
        result = sync_alias.diff_alias_maps({'1001': ['1002', '1003']}, {'1001': [1002]})

        assert result['removed'] == {'1001': [1003]}
        assert result['added'] == {}
        assert result['in_sync'] is False

    def test_reports_base_codes_missing_from_derived_as_removed(self):
        result = sync_alias.diff_alias_maps({'1001': ['1002']}, {})

        assert result['removed'] == {'1001': [1002]}
        assert result['in_sync'] is False

    def test_reports_new_base_codes_as_added(self):
        result = sync_alias.diff_alias_maps({}, {'1001': [1002]})

        assert result['added'] == {'1001': [1002]}
        assert result['in_sync'] is False

    def test_in_sync_when_maps_match_despite_string_ids(self):
        result = sync_alias.diff_alias_maps({'1001': ['1002']}, {'1001': [1002]})

        assert result['added'] == {}
        assert result['removed'] == {}
        assert result['in_sync'] is True

    def test_counts_totals(self):
        result = sync_alias.diff_alias_maps({'1001': ['1002']}, {'1001': [1003], '2001': [2002]})

        assert result['added_count'] == 2
        assert result['removed_count'] == 1


def make_cdb(path: Path, rows: List[Tuple[int, int]]) -> Path:
    """Create a minimal EDOPro-style card database holding only `datas`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.execute('CREATE TABLE datas (id INTEGER PRIMARY KEY, alias INTEGER)')
    connection.executemany('INSERT INTO datas (id, alias) VALUES (?, ?)', rows)
    connection.commit()
    connection.close()
    return path


class TestSelectEdoproDatabases:
    """Covers which database files of the Project Ignis repos are read."""

    def test_keeps_only_cdb_files(self):
        names = ['cards.cdb', 'README.md', 'mappings.json', 'strings.conf']

        assert sync_alias.select_edopro_databases(names) == ['cards.cdb']

    def test_drops_rush_skills_and_goat_databases(self):
        names = [
            'cards.cdb', 'cards-rush.cdb', 'cards-skills.cdb',
            'cards-skills-unofficial.cdb', 'goat-entries.cdb',
            'prerelease-cards-rush.cdb', 'cards-unofficial.cdb',
        ]

        assert sync_alias.select_edopro_databases(names) == [
            'cards-unofficial.cdb', 'cards.cdb',
        ]

    def test_exclusion_is_case_insensitive(self):
        names = ['Cards-RUSH.cdb', 'GOAT-entries.delta.cdb', 'cards-Skills.cdb', 'x.CDB']

        assert sync_alias.select_edopro_databases(names) == ['x.CDB']

    def test_keeps_prerelease_release_and_delta_databases(self):
        names = [
            'release-betb.cdb', 'prerelease-yac1.cdb', 'cards.delta.cdb',
            'cards-unofficial.delta.cdb', 'prerelease-others.cdb',
        ]

        assert sync_alias.select_edopro_databases(names) == sorted(names)

    def test_returns_names_sorted(self):
        names = ['release-betb.cdb', 'cards.cdb', 'prerelease-dbgv.cdb']

        assert sync_alias.select_edopro_databases(names) == [
            'cards.cdb', 'prerelease-dbgv.cdb', 'release-betb.cdb',
        ]


class TestReadAliasRows:
    """Covers the sqlite read against throwaway databases."""

    def test_reads_every_row_including_base_cards(self, tmp_path: Path):
        cdb_path = make_cdb(tmp_path / 'cards.cdb', [(1001, 0), (1002, 1001), (1003, 1001)])

        rows = sync_alias.read_alias_rows(cdb_path)

        assert sorted(rows) == [(1001, 0), (1002, 1001), (1003, 1001)]


class TestReadAliasRowsFromDirs:
    """Covers the overlay of every EDOPro database across directories."""

    def test_reads_every_selected_database_in_a_directory(self, tmp_path: Path):
        babel = tmp_path / 'BabelCDB'
        make_cdb(babel / 'cards.cdb', [(1001, 0), (1002, 1001)])
        make_cdb(babel / 'prerelease-new.cdb', [(1003, 1001)])

        rows = sync_alias.read_alias_rows_from_dirs([babel])

        assert sorted(rows) == [(1001, 0), (1002, 1001), (1003, 1001)]

    def test_ignores_rush_skills_and_goat_databases(self, tmp_path: Path):
        babel = tmp_path / 'BabelCDB'
        make_cdb(babel / 'cards.cdb', [(53129443, 0)])
        make_cdb(babel / 'cards-rush.cdb', [(160205069, 53129443)])
        make_cdb(babel / 'cards-skills.cdb', [(300000001, 53129443)])
        make_cdb(babel / 'goat-entries.cdb', [(53129444, 53129443)])

        rows = sync_alias.read_alias_rows_from_dirs([babel])

        assert rows == [(53129443, 0)]

    def test_a_later_directory_overwrites_an_earlier_one(self, tmp_path: Path):
        babel = tmp_path / 'BabelCDB'
        delta = tmp_path / 'DeltaBagooska'
        make_cdb(babel / 'cards.cdb', [(1002, 1001), (1003, 1001)])
        make_cdb(delta / 'cards.delta.cdb', [(1002, 2001)])

        rows = sync_alias.read_alias_rows_from_dirs([babel, delta])

        assert sorted(rows) == [(1002, 2001), (1003, 1001)]

    def test_a_later_file_in_sorted_order_overwrites_an_earlier_one(
        self, tmp_path: Path
    ):
        babel = tmp_path / 'BabelCDB'
        make_cdb(babel / 'b.cdb', [(1002, 2001)])
        make_cdb(babel / 'a.cdb', [(1002, 1001)])

        rows = sync_alias.read_alias_rows_from_dirs([babel])

        assert rows == [(1002, 2001)]

    def test_keeps_a_row_whose_final_alias_is_zero(self, tmp_path: Path):
        babel = tmp_path / 'BabelCDB'
        delta = tmp_path / 'DeltaBagooska'
        make_cdb(babel / 'cards.cdb', [(1002, 1001)])
        make_cdb(delta / 'cards.delta.cdb', [(1002, 0)])

        rows = sync_alias.read_alias_rows_from_dirs([babel, delta])

        assert rows == [(1002, 0)]

    def test_directory_order_matters_more_than_file_names(self, tmp_path: Path):
        first = tmp_path / 'first'
        second = tmp_path / 'second'
        make_cdb(first / 'z.cdb', [(1002, 1001)])
        make_cdb(second / 'a.cdb', [(1002, 2001)])

        rows = sync_alias.read_alias_rows_from_dirs([first, second])

        assert rows == [(1002, 2001)]


class TestFindOrphanAliasImages:
    """Covers which committed alias images no longer belong to alias.json."""

    def test_returns_images_whose_code_is_not_in_the_alias_map(self, tmp_path: Path):
        (tmp_path / '1002.jpg').write_bytes(b'art')
        (tmp_path / '511002075.jpg').write_bytes(b'art')

        orphans = sync_alias.find_orphan_alias_images(tmp_path, {'1001': [1002]})

        assert orphans == [tmp_path / '511002075.jpg']

    def test_accepts_string_alias_ids(self, tmp_path: Path):
        (tmp_path / '1002.jpg').write_bytes(b'art')

        assert sync_alias.find_orphan_alias_images(tmp_path, {'1001': ['1002']}) == []

    def test_keeps_images_named_after_a_family_base_code(self, tmp_path: Path):
        """generate.py caches the base art of a family listed under an alias."""
        (tmp_path / '1001.jpg').write_bytes(b'art')
        (tmp_path / '1002.jpg').write_bytes(b'art')

        assert sync_alias.find_orphan_alias_images(tmp_path, {'1001': [1002]}) == []

    def test_ignores_non_jpg_and_non_numeric_files(self, tmp_path: Path):
        (tmp_path / 'README.md').write_text('notes', encoding='utf-8')
        (tmp_path / 'cover.jpg').write_bytes(b'art')

        assert sync_alias.find_orphan_alias_images(tmp_path, {}) == []

    def test_returns_orphans_sorted_numerically(self, tmp_path: Path):
        for code in ('30000001', '2000001', '100000001'):
            (tmp_path / f'{code}.jpg').write_bytes(b'art')

        orphans = sync_alias.find_orphan_alias_images(tmp_path, {})

        assert [path.stem for path in orphans] == ['2000001', '30000001', '100000001']

    def test_missing_directory_has_no_orphans(self, tmp_path: Path):
        assert sync_alias.find_orphan_alias_images(tmp_path / 'absent', {}) == []

    def test_does_not_delete_anything(self, tmp_path: Path):
        (tmp_path / '511002075.jpg').write_bytes(b'art')

        sync_alias.find_orphan_alias_images(tmp_path, {})

        assert (tmp_path / '511002075.jpg').exists()


class TestLoadCardCodes:
    """Covers reading the Genesys base card codes."""

    def test_returns_integer_codes(self, tmp_path: Path):
        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(
            json.dumps([{'code': 1001, 'points': 5}, {'code': '2001', 'points': 3}]),
            encoding='utf-8',
        )

        codes = sync_alias.load_card_codes(cards_path)

        assert codes == {1001, 2001}

    def test_skips_json_entries_without_a_code(self, tmp_path: Path):
        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(
            json.dumps([{'code': 1001, 'points': 5}, {'name': 'No code', 'points': 3}]),
            encoding='utf-8',
        )

        codes = sync_alias.load_card_codes(cards_path)

        assert codes == {1001}

    def test_reads_the_upstream_lflist_conf(self, tmp_path: Path):
        conf_path = tmp_path / 'genesys.lflist.conf'
        conf_path.write_text(
            '#[Genesys]\n'
            '!Genesys\n'
            '83764719 3 20 --Monster Reborn\n'
            '10443957 3 15 --Change of Heart\n',
            encoding='utf-8',
        )

        codes = sync_alias.load_card_codes(conf_path)

        assert codes == {83764719, 10443957}

    def test_ignores_conf_lines_outside_the_genesys_section(self, tmp_path: Path):
        conf_path = tmp_path / 'genesys.lflist.conf'
        conf_path.write_text(
            '!Forbidden\n'
            '99999999 3 10 --Not Genesys\n'
            '!Genesys\n'
            '10443957 3 15 --Change of Heart\n',
            encoding='utf-8',
        )

        codes = sync_alias.load_card_codes(conf_path)

        assert codes == {10443957}

    def test_ignores_conf_comment_lines(self, tmp_path: Path):
        conf_path = tmp_path / 'genesys.lflist.conf'
        conf_path.write_text(
            '!Genesys\n'
            '#10443957 3 15 --Commented out\n'
            '83764719 3 20 --Monster Reborn\n',
            encoding='utf-8',
        )

        codes = sync_alias.load_card_codes(conf_path)

        assert codes == {83764719}

    def test_skips_a_malformed_conf_line(self, tmp_path: Path):
        conf_path = tmp_path / 'genesys.lflist.conf'
        conf_path.write_text(
            '!Genesys\n'
            '10443957 3 --Missing the points column\n'
            '83764719 3 20 --Monster Reborn\n',
            encoding='utf-8',
        )

        codes = sync_alias.load_card_codes(conf_path)

        assert codes == {83764719}

    def test_matches_the_conf_suffix_case_insensitively(self, tmp_path: Path):
        conf_path = tmp_path / 'genesys.lflist.CONF'
        conf_path.write_text(
            '!Genesys\n83764719 3 20 --Monster Reborn\n', encoding='utf-8'
        )

        codes = sync_alias.load_card_codes(conf_path)

        assert codes == {83764719}


class TestNormalizeListedCodes:
    """Covers folding a listed alias passcode back onto its base card."""

    def test_a_listed_alias_code_pulls_in_its_base_card(self):
        result = sync_alias.normalize_listed_codes({1002}, [(1002, 1001)])

        assert result == {1001, 1002}

    def test_a_listed_base_code_is_unchanged(self):
        result = sync_alias.normalize_listed_codes({1001}, [(1002, 1001)])

        assert result == {1001}

    def test_a_code_absent_from_the_rows_passes_through(self):
        result = sync_alias.normalize_listed_codes({7777}, [(1002, 1001)])

        assert result == {7777}

    def test_is_idempotent(self):
        rows = [(1002, 1001)]

        once = sync_alias.normalize_listed_codes({1002}, rows)
        twice = sync_alias.normalize_listed_codes(once, rows)

        assert once == twice == {1001, 1002}

    def test_accepts_any_iterable_of_rows_and_codes(self):
        result = sync_alias.normalize_listed_codes(iter([1002]), iter([(1002, 1001)]))

        assert result == {1001, 1002}

    def test_a_base_card_row_with_alias_zero_adds_nothing(self):
        result = sync_alias.normalize_listed_codes({1001}, [(1001, 0), (1002, 1001)])

        assert result == {1001}

    def test_monster_reborn_listed_by_its_alias_passcode(self):
        """
        Konami's list is name-based and resolves through ygoprodeck, so a listed
        code may be any printing's passcode: on 2026-09-23 Monster Reborn moved
        from 83764718 (the base) to 83764719 (one of its alternate arts).
        """
        result = sync_alias.normalize_listed_codes(
            {83764719}, [(83764719, 83764718), (83764720, 83764718)]
        )

        assert result == {83764718, 83764719}


class TestAliasSynchronizer:
    """Covers the end-to-end synchronizer against temporary files."""

    def _build_fixture(self, tmp_path: Path) -> sync_alias.AliasSynchronizer:
        babel = tmp_path / 'BabelCDB'
        delta = tmp_path / 'DeltaBagooska'
        make_cdb(babel / 'cards.cdb', [(1001, 0), (1002, 1001), (1004, 1001)])
        make_cdb(babel / 'cards-rush.cdb', [(160001001, 1001)])
        # The delta repo is read last, so it wins: 1004 is no longer an alias.
        make_cdb(delta / 'cards.delta.cdb', [(1004, 0)])

        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(json.dumps([{'code': 1001, 'points': 5}]), encoding='utf-8')

        alias_path = tmp_path / 'alias.json'
        alias_path.write_text(json.dumps({'1001': ['511002075']}), encoding='utf-8')

        images_dir = tmp_path / 'alias_images'
        images_dir.mkdir()
        (images_dir / '511002075.jpg').write_bytes(b'art')
        (images_dir / '1002.jpg').write_bytes(b'art')

        return sync_alias.AliasSynchronizer(
            cdb_dirs=[babel, delta],
            cards_path=cards_path,
            alias_path=alias_path,
            alias_images_dir=images_dir,
        )

    def test_check_only_does_not_write_or_delete(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)
        before = (tmp_path / 'alias.json').read_text(encoding='utf-8')

        diff = synchronizer.sync(check_only=True)

        assert diff['in_sync'] is False
        assert (tmp_path / 'alias.json').read_text(encoding='utf-8') == before
        assert (tmp_path / 'alias_images' / '511002075.jpg').exists()

    def test_sync_writes_only_what_edopro_declares(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)

        diff = synchronizer.sync(check_only=False)

        written = json.loads((tmp_path / 'alias.json').read_text(encoding='utf-8'))
        assert written == {'1001': [1002]}
        assert diff['added'] == {'1001': [1002]}
        assert diff['removed'] == {'1001': [511002075]}

    def test_sync_deletes_orphan_alias_images(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)

        diff = synchronizer.sync(check_only=False)

        images_dir = tmp_path / 'alias_images'
        assert not (images_dir / '511002075.jpg').exists()
        assert (images_dir / '1002.jpg').exists()
        assert diff['orphan_images'] == [images_dir / '511002075.jpg']

    def test_check_reports_orphan_images_as_drift(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)
        (tmp_path / 'alias.json').write_text(
            json.dumps({'1001': [1002]}), encoding='utf-8'
        )

        diff = synchronizer.sync(check_only=True)

        assert diff['added_count'] == 0
        assert diff['removed_count'] == 0
        assert diff['orphan_images'] == [tmp_path / 'alias_images' / '511002075.jpg']
        assert diff['in_sync'] is False

    def test_check_is_in_sync_without_drift_or_orphans(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)
        (tmp_path / 'alias.json').write_text(
            json.dumps({'1001': [1002]}), encoding='utf-8'
        )
        (tmp_path / 'alias_images' / '511002075.jpg').unlink()

        diff = synchronizer.sync(check_only=True)

        assert diff['in_sync'] is True
        assert diff['orphan_images'] == []

    def test_written_file_uses_two_space_indent_and_trailing_newline(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)

        synchronizer.sync(check_only=False)

        content = (tmp_path / 'alias.json').read_text(encoding='utf-8')
        assert content.endswith('\n')
        assert '\t' not in content
        assert '\n  "1001": [\n' in content

    def test_sync_derives_the_family_of_a_listed_alias_passcode(self, tmp_path: Path):
        """A Genesys list naming only 83764719 must still derive 83764718's family."""
        babel = tmp_path / 'BabelCDB'
        make_cdb(
            babel / 'cards.cdb',
            [(83764718, 0), (83764719, 83764718), (83764720, 83764718)],
        )

        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(
            json.dumps([{'code': 83764719, 'points': 20}]), encoding='utf-8'
        )

        synchronizer = sync_alias.AliasSynchronizer(
            cdb_dirs=[babel],
            cards_path=cards_path,
            alias_path=tmp_path / 'alias.json',
            alias_images_dir=tmp_path / 'alias_images',
        )
        synchronizer.sync(check_only=False)

        written = json.loads((tmp_path / 'alias.json').read_text(encoding='utf-8'))
        assert written == {'83764718': [83764719, 83764720]}


class TestMain:
    """Covers the command-line contract."""

    def test_cdb_dir_is_required(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr('sys.argv', ['sync_alias.py', '--cards', str(tmp_path / 'c.json')])

        with pytest.raises(SystemExit) as excinfo:
            sync_alias.main()

        assert excinfo.value.code == 2

    def test_cdb_dir_is_repeatable(self, monkeypatch, tmp_path: Path):
        babel = tmp_path / 'BabelCDB'
        delta = tmp_path / 'DeltaBagooska'
        make_cdb(babel / 'cards.cdb', [(1001, 0), (1002, 1001)])
        make_cdb(delta / 'cards.delta.cdb', [(1003, 1001)])
        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(json.dumps([{'code': 1001, 'points': 5}]), encoding='utf-8')
        alias_path = tmp_path / 'alias.json'

        monkeypatch.setattr('sys.argv', [
            'sync_alias.py', '-d', str(babel), '--cdb-dir', str(delta),
            '--cards', str(cards_path), '--alias', str(alias_path),
            '--alias-images', str(tmp_path / 'alias_images'),
        ])
        sync_alias.main()

        written = json.loads(alias_path.read_text(encoding='utf-8'))
        assert written == {'1001': [1002, 1003]}

    def test_missing_cdb_dir_is_fatal(self, monkeypatch, tmp_path: Path):
        cards_path = tmp_path / 'cards.json'
        cards_path.write_text('[]', encoding='utf-8')
        monkeypatch.setattr('sys.argv', [
            'sync_alias.py', '--cdb-dir', str(tmp_path / 'absent'),
            '--cards', str(cards_path),
        ])

        with pytest.raises(SystemExit) as excinfo:
            sync_alias.main()

        assert excinfo.value.code == 1
