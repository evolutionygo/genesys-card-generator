#!/usr/bin/env python3
"""Tests for the pictures publishing logic in sync_pictures.py."""

import json
from pathlib import Path
from typing import Dict, Iterable, List

import pytest

import sync_pictures


def touch_jpgs(directory: Path, codes: Iterable[str], content: bytes = b'img') -> None:
    """
    Create `<code>.jpg` files in a directory.

    Args:
        directory: Directory to write into (created if missing)
        codes: Card codes to create images for
        content: Bytes written to every file
    """
    directory.mkdir(parents=True, exist_ok=True)
    for code in codes:
        (directory / f"{code}.jpg").write_bytes(content)


def write_data(tmp_path: Path, cards: List[Dict], alias_map: Dict) -> Dict[str, Path]:
    """
    Write cards.json and alias.json fixtures.

    Args:
        tmp_path: pytest temporary directory
        cards: The cards.json content
        alias_map: The alias.json content

    Returns:
        A dict with the `cards` and `alias` paths.
    """
    cards_path = tmp_path / 'cards.json'
    alias_path = tmp_path / 'alias.json'
    cards_path.write_text(json.dumps(cards), encoding='utf-8')
    alias_path.write_text(json.dumps(alias_map), encoding='utf-8')
    return {'cards': cards_path, 'alias': alias_path}


class TestDesiredCodes:
    """Covers the pure derivation of the codes that must stay published."""

    def test_includes_card_codes_and_alias_keys_and_values(self):
        cards = [{'name': 'A', 'points': 1, 'code': 100}]
        alias_map = {'200': [201, 202], '300': [301]}

        desired = sync_pictures.desired_codes(cards, alias_map)

        assert desired == {'100', '200', '201', '202', '300', '301'}

    def test_accepts_scalar_alias_values(self):
        desired = sync_pictures.desired_codes([], {'200': 201})

        assert desired == {'200', '201'}

    def test_empty_data_yields_empty_set(self):
        assert sync_pictures.desired_codes([], {}) == set()


class TestPlanSync:
    """Covers the pure copy/delete/stale plan."""

    def test_copies_every_generated_file(self):
        plan = sync_pictures.plan_sync(['1.jpg', '2.jpg'], ['1.jpg'], {'1', '2'})

        assert plan['copy'] == ['1.jpg', '2.jpg']

    def test_deletes_only_target_jpgs_not_desired(self):
        plan = sync_pictures.plan_sync(['1.jpg'], ['1.jpg', '9.jpg'], {'1'})

        assert plan['delete'] == ['9.jpg']

    def test_desired_but_not_generated_is_kept_and_reported(self):
        plan = sync_pictures.plan_sync(['1.jpg'], ['1.jpg', '2.jpg'], {'1', '2'})

        assert plan['delete'] == []
        assert plan['stale_kept'] == ['2']

    def test_ignores_non_jpg_names(self):
        plan = sync_pictures.plan_sync(
            ['1.jpg', 'notes.txt'], ['1.jpg', 'README.md', '9.png'], {'1'}
        )

        assert plan['copy'] == ['1.jpg']
        assert plan['delete'] == []
        assert plan['stale_kept'] == []


class TestCheckSafety:
    """Covers the guard that keeps a broken run from wiping production."""

    def test_trips_on_empty_desired(self):
        plan = sync_pictures.plan_sync([], ['1.jpg'], set())

        with pytest.raises(sync_pictures.UnsafeSyncError):
            sync_pictures.check_safety(plan, ['1.jpg'], set())

    def test_trips_when_deleting_more_than_a_quarter(self):
        target = [f"{code}.jpg" for code in range(1, 5)]
        plan = sync_pictures.plan_sync([], target, {'1', '2'})

        with pytest.raises(sync_pictures.UnsafeSyncError):
            sync_pictures.check_safety(plan, target, {'1', '2'})

    def test_allows_deleting_exactly_a_quarter(self):
        target = [f"{code}.jpg" for code in range(1, 5)]
        desired = {'1', '2', '3'}
        plan = sync_pictures.plan_sync([], target, desired)

        sync_pictures.check_safety(plan, target, desired)

    def test_force_bypasses_the_guard(self):
        plan = sync_pictures.plan_sync([], ['1.jpg'], set())

        sync_pictures.check_safety(plan, ['1.jpg'], set(), force=True)

    def test_empty_target_never_trips_the_ratio(self):
        plan = sync_pictures.plan_sync(['1.jpg'], [], {'1'})

        sync_pictures.check_safety(plan, [], {'1'})


class TestPictureSynchronizer:
    """Covers applying the plan on disk."""

    def build(self, tmp_path: Path, cards: List[Dict], alias_map: Dict) -> sync_pictures.PictureSynchronizer:
        """
        Build a synchronizer over tmp_path fixtures.

        Args:
            tmp_path: pytest temporary directory
            cards: The cards.json content
            alias_map: The alias.json content

        Returns:
            The configured synchronizer.
        """
        paths = write_data(tmp_path, cards, alias_map)
        return sync_pictures.PictureSynchronizer(
            generated_dir=str(tmp_path / 'generated'),
            target_dir=str(tmp_path / 'pics'),
            cards_path=str(paths['cards']),
            alias_path=str(paths['alias']),
        )

    def test_copies_and_deletes(self, tmp_path):
        cards = [{'name': c, 'points': 1, 'code': int(c)} for c in '12345']
        touch_jpgs(tmp_path / 'generated', ['1', '2', '3', '4'], b'new')
        touch_jpgs(tmp_path / 'pics', ['1', '2', '3', '4', '5', '9'], b'old')
        (tmp_path / 'pics' / 'README.md').write_text('keep', encoding='utf-8')

        result = self.build(tmp_path, cards, {}).sync()

        pics = tmp_path / 'pics'
        assert (pics / '1.jpg').read_bytes() == b'new'
        assert not (pics / '9.jpg').exists()
        assert (pics / '5.jpg').read_bytes() == b'old'
        assert (pics / 'README.md').exists()
        assert result['copied'] == 4
        assert result['deleted'] == 1
        assert result['stale_kept'] == 1
        assert result['stale_kept_codes'] == ['5']
        assert result['deleted_codes'] == ['9']

    def test_dry_run_changes_nothing(self, tmp_path):
        cards = [{'name': c, 'points': 1, 'code': int(c)} for c in '1234']
        touch_jpgs(tmp_path / 'generated', ['1'], b'new')
        touch_jpgs(tmp_path / 'pics', ['1', '2', '3', '4', '9'], b'old')

        result = self.build(tmp_path, cards, {}).sync(dry_run=True)

        assert (tmp_path / 'pics' / '1.jpg').read_bytes() == b'old'
        assert (tmp_path / 'pics' / '9.jpg').exists()
        assert result['copied'] == 1
        assert result['deleted'] == 1

    def test_guard_trip_changes_nothing(self, tmp_path):
        touch_jpgs(tmp_path / 'generated', ['1'], b'new')
        touch_jpgs(tmp_path / 'pics', ['1', '2'], b'old')

        with pytest.raises(sync_pictures.UnsafeSyncError):
            self.build(tmp_path, [], {}).sync()

        assert (tmp_path / 'pics' / '1.jpg').read_bytes() == b'old'
        assert (tmp_path / 'pics' / '2.jpg').exists()

    def test_force_applies_a_large_deletion(self, tmp_path):
        cards = [{'name': 'A', 'points': 1, 'code': 1}]
        touch_jpgs(tmp_path / 'generated', ['1'], b'new')
        touch_jpgs(tmp_path / 'pics', ['1', '2', '3'], b'old')

        result = self.build(tmp_path, cards, {}).sync(force=True)

        assert result['deleted'] == 2
        assert sorted(p.name for p in (tmp_path / 'pics').iterdir()) == ['1.jpg']

    def test_creates_missing_target_dir(self, tmp_path):
        cards = [{'name': 'A', 'points': 1, 'code': 1}]
        touch_jpgs(tmp_path / 'generated', ['1'], b'new')

        self.build(tmp_path, cards, {}).sync()

        assert (tmp_path / 'pics' / '1.jpg').read_bytes() == b'new'
