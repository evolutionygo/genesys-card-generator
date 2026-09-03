#!/usr/bin/env python3
"""
Derive alias.json from the EDOPro card database.

alias.json maps a Genesys base card code to the alternate-art printings that
must receive the same points badge. It used to be hand-maintained, which meant
new alternate-art printings silently shipped with no badge at all.

The authoritative source is the `datas.alias` column of `base.en.cdb`: a row
`(id, alias)` means `id` is an alternate-art printing of the base card `alias`.
Only `base.en.cdb` is read - the `pre-errata.*.cdb` overlays hold Edison-format
custom codes that never appear in Genesys.

The database is not a superset of the current file: alias.json also carries OCG
and prerelease codes that came from other databases and that `base.en.cdb` does
not declare. Those entries are still backed by real, working art in
`alias_images/`, so they are preserved instead of deleted (see
`merge_preserved_aliases`).

Usage:
    python3 sync_alias.py           # rewrite alias.json
    python3 sync_alias.py --check   # report drift and exit 1 (for CI)
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

DEFAULT_CDB_PATH = '/home/diango/code/evolution/evolution-assets/cdb/base.en.cdb'


def build_alias_map(
    rows: Iterable[Tuple[int, int]], codes: Iterable[int]
) -> Dict[str, List[int]]:
    """
    Build the alias map declared by the card database.

    Args:
        rows: Iterable of (id, alias) integer pairs from `datas`, where `id` is
            an alternate-art printing and `alias` is the base card.
        codes: The Genesys base card codes from cards.json.

    Returns:
        A dict of base card code (as a string) to its alternate-art codes,
        values sorted ascending and de-duplicated, keys inserted in ascending
        numeric order.
    """
    known_codes = {int(code) for code in codes}
    grouped: Dict[int, Set[int]] = {}

    for alias_id, base_code in rows:
        alias_id = int(alias_id)
        base_code = int(base_code)

        # Only Genesys base cards matter, and a printing is never its own alias.
        if base_code not in known_codes or alias_id == base_code:
            continue

        grouped.setdefault(base_code, set()).add(alias_id)

    return {
        str(base_code): sorted(grouped[base_code])
        for base_code in sorted(grouped)
    }


def merge_preserved_aliases(
    derived: Dict[str, List[int]],
    current: Dict[str, Iterable],
    preserved_ids: Iterable[int],
) -> Dict[str, List[int]]:
    """
    Union the database-derived map with existing entries backed by local art.

    This is the most important guarantee in this module. `base.en.cdb` does NOT
    declare every alias id currently in alias.json: OCG and prerelease codes
    (511002075, 160019064, 97268404, ...) came from other databases. A naive
    rewrite would delete them and lose art that works today, re-introducing the
    exact bug this script exists to fix.

    So an existing entry is dropped only when it has no file in `alias_images/`.
    Whether an id has local art is decided by the caller and passed in, so this
    function stays pure and testable.

    Args:
        derived: Output of `build_alias_map`.
        current: The alias map currently on disk (values may be ints or strings).
        preserved_ids: Alias ids that have a committed image in `alias_images/`.

    Returns:
        The merged map, keys inserted in ascending numeric order and values
        sorted ascending.
    """
    protected = {int(alias_id) for alias_id in preserved_ids}
    merged: Dict[int, Set[int]] = {
        int(base_code): {int(alias_id) for alias_id in alias_ids}
        for base_code, alias_ids in derived.items()
    }

    for base_code, alias_ids in current.items():
        kept = {int(alias_id) for alias_id in alias_ids if int(alias_id) in protected}
        if kept:
            merged.setdefault(int(base_code), set()).update(kept)

    return {str(base_code): sorted(merged[base_code]) for base_code in sorted(merged)}


def diff_alias_maps(
    current: Dict[str, Iterable], derived: Dict[str, Iterable]
) -> Dict:
    """
    Compare the alias map on disk with the map that should be written.

    Args:
        current: The alias map currently on disk (values may be ints or strings).
        derived: The alias map that should be written.

    Returns:
        A dict with `added` and `removed` (base code -> sorted alias ids),
        `added_count`, `removed_count` and `in_sync`.
    """
    normalized_current = {
        str(base_code): {int(alias_id) for alias_id in alias_ids}
        for base_code, alias_ids in current.items()
    }
    normalized_derived = {
        str(base_code): {int(alias_id) for alias_id in alias_ids}
        for base_code, alias_ids in derived.items()
    }

    added: Dict[str, List[int]] = {}
    removed: Dict[str, List[int]] = {}

    all_codes = sorted(
        set(normalized_current) | set(normalized_derived), key=int
    )
    for base_code in all_codes:
        current_ids = normalized_current.get(base_code, set())
        derived_ids = normalized_derived.get(base_code, set())

        new_ids = sorted(derived_ids - current_ids)
        gone_ids = sorted(current_ids - derived_ids)

        if new_ids:
            added[base_code] = new_ids
        if gone_ids:
            removed[base_code] = gone_ids

    added_count = sum(len(ids) for ids in added.values())
    removed_count = sum(len(ids) for ids in removed.values())

    return {
        'added': added,
        'removed': removed,
        'added_count': added_count,
        'removed_count': removed_count,
        'in_sync': added_count == 0 and removed_count == 0,
    }


def read_alias_rows(cdb_path) -> List[Tuple[int, int]]:
    """
    Read the alternate-art rows from an EDOPro card database.

    Args:
        cdb_path: Path to a `.cdb` SQLite database (use `base.en.cdb`).

    Returns:
        A list of (id, alias) integer pairs where alias is non-zero.
    """
    connection = sqlite3.connect(str(Path(cdb_path)))
    try:
        cursor = connection.execute('SELECT id, alias FROM datas WHERE alias != 0')
        return [(int(alias_id), int(base_code)) for alias_id, base_code in cursor]
    finally:
        connection.close()


def load_card_codes(cards_path) -> Set[int]:
    """
    Load the Genesys base card codes from cards.json.

    Args:
        cards_path: Path to cards.json.

    Returns:
        A set of integer card codes.
    """
    with open(Path(cards_path), 'r', encoding='utf-8') as f:
        cards = json.load(f)

    return {int(card['code']) for card in cards if card.get('code') is not None}


class AliasSynchronizer:
    """Keeps alias.json in sync with the EDOPro card database."""

    def __init__(
        self,
        cdb_path: str,
        cards_path: str,
        alias_path: str,
        alias_images_dir: Optional[str],
    ):
        """
        Initialize the synchronizer.

        Args:
            cdb_path: Path to base.en.cdb
            cards_path: Path to cards.json
            alias_path: Path to alias.json
            alias_images_dir: Directory holding committed alias art
        """
        self.cdb_path = Path(cdb_path)
        self.cards_path = Path(cards_path)
        self.alias_path = Path(alias_path)
        self.alias_images_dir = Path(alias_images_dir) if alias_images_dir else None

    def load_current_alias_map(self) -> Dict[str, List]:
        """
        Load the alias map currently on disk.

        Returns:
            The parsed alias.json content, or an empty dict if the file is absent.
        """
        if not self.alias_path.exists():
            return {}

        with open(self.alias_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def local_alias_ids(self) -> Set[int]:
        """
        Collect the alias ids that have committed art on disk.

        Returns:
            A set of integer alias ids found as `{id}.jpg` in alias_images/.
        """
        if not self.alias_images_dir or not self.alias_images_dir.is_dir():
            return set()

        ids: Set[int] = set()
        for image_path in self.alias_images_dir.glob('*.jpg'):
            try:
                ids.add(int(image_path.stem))
            except ValueError:
                print(f"⚠️  Ignoring non-numeric alias image name: {image_path.name}")
                continue

        return ids

    def write_alias_map(self, alias_map: Dict[str, List[int]]) -> None:
        """
        Write the alias map to disk using the project's formatting convention.

        Args:
            alias_map: The alias map to serialize (2-space indent, trailing newline).
        """
        with open(self.alias_path, 'w', encoding='utf-8') as f:
            json.dump(alias_map, f, indent=2, ensure_ascii=False)
            f.write('\n')

    def sync(self, check_only: bool = False) -> Dict:
        """
        Derive the alias map and either report or write it.

        Args:
            check_only: If True, report the diff without writing anything.

        Returns:
            The diff dict produced by `diff_alias_maps`.
        """
        codes = load_card_codes(self.cards_path)
        rows = read_alias_rows(self.cdb_path)
        current = self.load_current_alias_map()
        preserved_ids = self.local_alias_ids()

        derived = build_alias_map(rows, codes)
        merged = merge_preserved_aliases(derived, current, preserved_ids)
        diff = diff_alias_maps(current, merged)

        print(f"📊 Base cards in {self.cards_path.name}: {len(codes)}")
        print(f"📊 Alias rows declared by {self.cdb_path.name}: {len(rows)}")
        print(f"📊 Alias ids with committed art: {len(preserved_ids)}")
        print(
            f"📊 Alias ids: {sum(len(v) for v in current.values())} on disk -> "
            f"{sum(len(v) for v in merged.values())} derived"
        )

        self._print_diff(diff)

        if check_only:
            if diff['in_sync']:
                print("✅ alias.json is in sync with the card database.")
            else:
                print("❌ alias.json is out of sync with the card database.")
                print("   Run: python3 sync_alias.py")
            return diff

        if diff['in_sync']:
            print("✅ alias.json is already in sync, nothing to write.")
            return diff

        self.write_alias_map(merged)
        print(f"💾 Wrote {len(merged)} base cards to {self.alias_path}")
        print("ℹ️  Remember to commit alias.json and any new alias_images/ files.")

        return diff

    def _print_diff(self, diff: Dict) -> None:
        """
        Print the per-card added/removed summary.

        Args:
            diff: The diff dict produced by `diff_alias_maps`.
        """
        print(
            f"📊 Diff: +{diff['added_count']} alias ids across "
            f"{len(diff['added'])} base cards, "
            f"-{diff['removed_count']} across {len(diff['removed'])} base cards"
        )

        for base_code, alias_ids in diff['added'].items():
            print(f"  ➕ {base_code}: {', '.join(str(i) for i in alias_ids)}")

        for base_code, alias_ids in diff['removed'].items():
            print(f"  ➖ {base_code}: {', '.join(str(i) for i in alias_ids)}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Derive alias.json from the EDOPro card database (base.en.cdb).'
    )
    parser.add_argument(
        '--cdb', default=DEFAULT_CDB_PATH,
        help=f'Path to the EDOPro card database (default: {DEFAULT_CDB_PATH})'
    )
    parser.add_argument(
        '-c', '--cards', default='cards.json',
        help='Path to the Genesys cards JSON file (default: cards.json)'
    )
    parser.add_argument(
        '-a', '--alias', default='alias.json',
        help='Path to the alias JSON file to derive (default: alias.json)'
    )
    parser.add_argument(
        '-i', '--alias-images', default='alias_images',
        help='Directory with committed alias images, whose entries are never '
             'dropped (default: alias_images)'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Report the diff and exit 1 if alias.json is out of sync, without '
             'writing anything (for CI)'
    )

    args = parser.parse_args()

    for path in (args.cdb, args.cards):
        if not Path(path).exists():
            print(f"❌ Error: Required file not found: {path}")
            sys.exit(1)

    synchronizer = AliasSynchronizer(
        cdb_path=args.cdb,
        cards_path=args.cards,
        alias_path=args.alias,
        alias_images_dir=args.alias_images,
    )

    diff = synchronizer.sync(check_only=args.check)

    # --check is meant for CI: drift must break the build, not print a warning.
    if args.check and not diff['in_sync']:
        sys.exit(1)


if __name__ == '__main__':
    main()
