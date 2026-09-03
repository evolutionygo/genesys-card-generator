#!/usr/bin/env python3
"""Tests for the alias synchronization logic in sync_alias.py."""

import json
import sqlite3
from pathlib import Path

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


class TestMergePreservedAliases:
    """The single most important guarantee: never delete working local art."""

    def test_preserves_existing_alias_ids_that_have_local_art(self):
        derived = {'1001': [1002]}
        current = {'1001': ['511002075']}
        preserved_ids = {511002075}

        result = sync_alias.merge_preserved_aliases(derived, current, preserved_ids)

        assert result == {'1001': [1002, 511002075]}

    def test_preserves_whole_base_codes_absent_from_the_database(self):
        derived = {}
        current = {'1001': ['160019064']}
        preserved_ids = {160019064}

        result = sync_alias.merge_preserved_aliases(derived, current, preserved_ids)

        assert result == {'1001': [160019064]}

    def test_drops_existing_alias_ids_without_local_art(self):
        derived = {'1001': [1002]}
        current = {'1001': ['97268404']}
        preserved_ids = set()

        result = sync_alias.merge_preserved_aliases(derived, current, preserved_ids)

        assert result == {'1001': [1002]}

    def test_normalizes_integer_and_string_ids_to_integers(self):
        derived = {'1001': [1002]}
        current = {'1001': [1002, '1003']}
        preserved_ids = {1003}

        result = sync_alias.merge_preserved_aliases(derived, current, preserved_ids)

        assert result == {'1001': [1002, 1003]}

    def test_result_keys_are_sorted_numerically(self):
        derived = {'30000000': [30000001]}
        current = {'2000000': ['2000001']}
        preserved_ids = {2000001}

        result = sync_alias.merge_preserved_aliases(derived, current, preserved_ids)

        assert list(result.keys()) == ['2000000', '30000000']

    def test_does_not_mutate_its_inputs(self):
        derived = {'1001': [1002]}
        current = {'1001': ['1003']}

        sync_alias.merge_preserved_aliases(derived, current, {1003})

        assert derived == {'1001': [1002]}
        assert current == {'1001': ['1003']}


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


class TestReadAliasRows:
    """Covers the sqlite read against a throwaway database."""

    def test_reads_only_rows_with_a_non_zero_alias(self, tmp_path: Path):
        cdb_path = tmp_path / 'base.en.cdb'
        connection = sqlite3.connect(cdb_path)
        connection.execute('CREATE TABLE datas (id INTEGER, alias INTEGER)')
        connection.executemany(
            'INSERT INTO datas (id, alias) VALUES (?, ?)',
            [(1001, 0), (1002, 1001), (1003, 1001)],
        )
        connection.commit()
        connection.close()

        rows = sync_alias.read_alias_rows(cdb_path)

        assert sorted(rows) == [(1002, 1001), (1003, 1001)]


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


class TestAliasSynchronizer:
    """Covers the end-to-end synchronizer against temporary files."""

    def _build_fixture(self, tmp_path: Path) -> sync_alias.AliasSynchronizer:
        cdb_path = tmp_path / 'base.en.cdb'
        connection = sqlite3.connect(cdb_path)
        connection.execute('CREATE TABLE datas (id INTEGER, alias INTEGER)')
        connection.executemany(
            'INSERT INTO datas (id, alias) VALUES (?, ?)',
            [(1001, 0), (1002, 1001)],
        )
        connection.commit()
        connection.close()

        cards_path = tmp_path / 'cards.json'
        cards_path.write_text(json.dumps([{'code': 1001, 'points': 5}]), encoding='utf-8')

        alias_path = tmp_path / 'alias.json'
        alias_path.write_text(json.dumps({'1001': ['511002075']}), encoding='utf-8')

        images_dir = tmp_path / 'alias_images'
        images_dir.mkdir()
        (images_dir / '511002075.jpg').write_bytes(b'art')

        return sync_alias.AliasSynchronizer(
            cdb_path=cdb_path,
            cards_path=cards_path,
            alias_path=alias_path,
            alias_images_dir=images_dir,
        )

    def test_check_only_does_not_write(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)
        before = (tmp_path / 'alias.json').read_text(encoding='utf-8')

        diff = synchronizer.sync(check_only=True)

        assert diff['in_sync'] is False
        assert (tmp_path / 'alias.json').read_text(encoding='utf-8') == before

    def test_sync_writes_union_of_derived_and_preserved(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)

        diff = synchronizer.sync(check_only=False)

        written = json.loads((tmp_path / 'alias.json').read_text(encoding='utf-8'))
        assert written == {'1001': [1002, 511002075]}
        assert diff['added'] == {'1001': [1002]}
        assert diff['removed'] == {}

    def test_written_file_uses_two_space_indent_and_trailing_newline(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)

        synchronizer.sync(check_only=False)

        content = (tmp_path / 'alias.json').read_text(encoding='utf-8')
        assert content.endswith('\n')
        assert '\t' not in content
        assert '\n  "1001": [\n' in content

    def test_local_alias_ids_reads_the_image_directory(self, tmp_path: Path):
        synchronizer = self._build_fixture(tmp_path)

        assert synchronizer.local_alias_ids() == {511002075}
