#!/usr/bin/env python3
"""
Derive alias.json from EDOPro's own card databases.

alias.json maps a Genesys base card code to the alternate-art printings that
must receive the same points badge. It used to be hand-maintained, which meant
new alternate-art printings silently shipped with no badge at all.

The images target EDOPro only, so the rule is: an alternate art is any code
that EDOPro's card databases declare with `datas.alias` pointing to a Genesys
base card. A row `(id, alias)` means `id` is an alternate-art printing of the
base card `alias` - but only when both carry the same name (`texts.name`).
`datas.alias` also encodes "This card is always treated as X", which is a
different card with its own name (e.g. Fallen of the White Dragon is aliased to
Fallen of Albaz) and must not receive the base card's badge. Printings outside
the official scope (`datas.ot` bits other than OCG 0x1, TCG 0x2, prerelease
0x100; e.g. anime 0x4) are rejected by the Genesys server and are skipped.

EDOPro's databases come from two Project Ignis repositories:

- https://github.com/ProjectIgnis/BabelCDB     (full databases)
- https://github.com/ProjectIgnis/DeltaBagooska (updates)

Every `*.cdb` in each `--cdb-dir` is read, except files whose name contains
`rush`, `skills` or `goat` (case-insensitive): Rush Duel, skill cards and the
GOAT format can never be in a Genesys deck. Prerelease file names change over
time, so databases are discovered by globbing, never listed by hand.

Overlay order: directories are read in the order given, files within a
directory in sorted name order, and a later row for the same `id` overwrites
an earlier one. Pass BabelCDB first and DeltaBagooska second so updates win.
Names are overlaid the same way across every selected database, so a printing
and its base card may live in different files.

The derivation is authoritative: an id EDOPro does not declare is removed from
alias.json, and its committed image in `alias_images/` is deleted with it.

The Genesys list itself is read through `genesys_source`, so the upstream
`genesys.lflist.conf` can be passed to `--cards` directly instead of going
through the cards.json copy.

Usage:
    python3 sync_alias.py --cdb-dir BabelCDB --cdb-dir DeltaBagooska
    python3 sync_alias.py --cdb-dir BabelCDB --cdb-dir DeltaBagooska --check
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import genesys_source

# Database file names containing any of these belong to another game or format.
EXCLUDED_DATABASE_MARKERS = ('rush', 'skills', 'goat')

# `datas.ot` scope bits. The Genesys server only accepts OFFICIAL printings
# (variant <= OCG_TCG); anime (0x4) and illegal (0x8) printings are rejected.
OT_OCG = 0x1
OT_TCG = 0x2
OT_PRERELEASE = 0x100
OT_OFFICIAL = OT_OCG | OT_TCG | OT_PRERELEASE


def is_alternate_art(
    alias_id: int,
    base_code: int,
    names: Dict[int, str],
    scopes: Dict[int, int],
) -> bool:
    """
    Tell whether a `datas.alias` row is a playable alternate-art printing.

    "Always treated as" cards share the alias column but not the name, and
    anime/illegal printings are rejected by the server. A row whose name or
    whose base card's name is unknown cannot be verified and does not count.

    Args:
        alias_id: The printing's id.
        base_code: The base card its `datas.alias` points to.
        names: Card name (`texts.name`) per id, across all selected databases.
        scopes: `datas.ot` bitmask per id; an id absent here has no extra bits.

    Returns:
        True only for a same-name printing with no bits outside OCG|TCG|prerelease.
    """
    printing_name = names.get(alias_id)
    if printing_name is None or printing_name != names.get(base_code):
        return False

    return not scopes.get(alias_id, 0) & ~OT_OFFICIAL


def build_alias_map(
    rows: Iterable[Tuple[int, int]],
    codes: Iterable[int],
    names: Dict[int, str],
    scopes: Dict[int, int],
) -> Dict[str, List[int]]:
    """
    Build the alias map declared by the card database.

    A row is an alternate-art printing only when its name equals the name of
    the base card it points to. A different name means "always treated as",
    which is another card; a row whose name or whose base card's name is
    unknown cannot be verified and is dropped too. A printing whose `datas.ot`
    has any bit outside OCG|TCG|prerelease (anime, illegal) is dropped as well:
    the server rejects it, so it can never be played. Code distance is deliberately
    not used: far-code aliases with the same name (tokens, 511001275) are real.

    Args:
        rows: Iterable of (id, alias) integer pairs from `datas`, where `id` is
            an alternate-art printing and `alias` is the base card. Rows with
            alias 0 (base cards) never match a Genesys code and are ignored.
        codes: The Genesys base card codes from the Genesys list.
        names: Card name (`texts.name`) per id, across all selected databases.
        scopes: `datas.ot` bitmask per id; an id absent here has no extra bits.

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

        if not is_alternate_art(alias_id, base_code, names, scopes):
            continue

        grouped.setdefault(base_code, set()).add(alias_id)

    return {
        str(base_code): sorted(grouped[base_code])
        for base_code in sorted(grouped)
    }


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


def select_edopro_databases(file_names: Iterable[str]) -> List[str]:
    """
    Select the EDOPro databases that can hold Genesys alternate arts.

    Args:
        file_names: File names found in a database directory.

    Returns:
        The `*.cdb` names whose name does not contain `rush`, `skills` or
        `goat` (case-insensitive), sorted ascending.
    """
    selected = []
    for name in file_names:
        lowered = name.lower()
        if not lowered.endswith('.cdb'):
            continue
        if any(marker in lowered for marker in EXCLUDED_DATABASE_MARKERS):
            continue
        selected.append(name)

    return sorted(selected)


def read_alias_rows(cdb_path) -> List[Tuple[int, int]]:
    """
    Read every (id, alias) row from an EDOPro card database.

    Base cards are returned too, with alias 0, so an overlay can clear an
    alias declared by an earlier database.

    Args:
        cdb_path: Path to a `.cdb` SQLite database.

    Returns:
        A list of (id, alias) integer pairs.
    """
    connection = sqlite3.connect(str(Path(cdb_path)))
    try:
        cursor = connection.execute('SELECT id, alias FROM datas')
        return [(int(card_id), int(alias or 0)) for card_id, alias in cursor]
    finally:
        connection.close()


def read_alias_rows_from_dirs(cdb_dirs: Iterable) -> List[Tuple[int, int]]:
    """
    Read the overlay of every EDOPro database across directories.

    Directories are read in the order given and files within a directory in
    sorted name order (see `select_edopro_databases`); a later row for the same
    `id` overwrites an earlier one.

    Args:
        cdb_dirs: Database directories, e.g. BabelCDB then DeltaBagooska.

    Returns:
        The final (id, alias) pair per id, sorted by id, including ids whose
        final alias is 0.
    """
    final_alias: Dict[int, int] = {}

    for cdb_dir in cdb_dirs:
        directory = Path(cdb_dir)
        names = [path.name for path in directory.iterdir() if path.is_file()]
        for name in select_edopro_databases(names):
            for card_id, alias in read_alias_rows(directory / name):
                final_alias[card_id] = alias

    return sorted(final_alias.items())


def read_names(cdb_path) -> Dict[int, str]:
    """
    Read every (id, name) pair from an EDOPro card database.

    Args:
        cdb_path: Path to a `.cdb` SQLite database.

    Returns:
        A dict of card id to `texts.name`; rows without a name are skipped.
    """
    connection = sqlite3.connect(str(Path(cdb_path)))
    try:
        cursor = connection.execute('SELECT id, name FROM texts')
        return {int(card_id): name for card_id, name in cursor if name}
    finally:
        connection.close()


def read_names_from_dirs(cdb_dirs: Iterable) -> Dict[int, str]:
    """
    Read the name overlay of every EDOPro database across directories.

    Uses the same database selection and overlay order as
    `read_alias_rows_from_dirs`, so a printing can be compared with a base card
    that lives in a different database or directory.

    Args:
        cdb_dirs: Database directories, e.g. BabelCDB then DeltaBagooska.

    Returns:
        The final name per card id.
    """
    final_names: Dict[int, str] = {}

    for cdb_dir in cdb_dirs:
        directory = Path(cdb_dir)
        names = [path.name for path in directory.iterdir() if path.is_file()]
        for name in select_edopro_databases(names):
            final_names.update(read_names(directory / name))

    return final_names


def read_scopes(cdb_path) -> Dict[int, int]:
    """
    Read every (id, ot) pair from an EDOPro card database.

    Args:
        cdb_path: Path to a `.cdb` SQLite database.

    Returns:
        A dict of card id to its `datas.ot` scope bitmask (NULL reads as 0).
    """
    connection = sqlite3.connect(str(Path(cdb_path)))
    try:
        cursor = connection.execute('SELECT id, ot FROM datas')
        return {int(card_id): int(ot or 0) for card_id, ot in cursor}
    finally:
        connection.close()


def read_scopes_from_dirs(cdb_dirs: Iterable) -> Dict[int, int]:
    """
    Read the `datas.ot` overlay of every EDOPro database across directories.

    Uses the same database selection and overlay order as
    `read_alias_rows_from_dirs`.

    Args:
        cdb_dirs: Database directories, e.g. BabelCDB then DeltaBagooska.

    Returns:
        The final scope bitmask per card id.
    """
    final_scopes: Dict[int, int] = {}

    for cdb_dir in cdb_dirs:
        directory = Path(cdb_dir)
        names = [path.name for path in directory.iterdir() if path.is_file()]
        for name in select_edopro_databases(names):
            final_scopes.update(read_scopes(directory / name))

    return final_scopes


def find_orphan_alias_images(images_dir, alias_map: Dict[str, Iterable]) -> List[Path]:
    """
    Find committed alias images whose code is no longer in the alias map.

    A code is known when it is either a family key or one of its aliases.

    Only `{code}.jpg` files with a numeric stem are considered. Nothing is
    deleted here; the caller decides what to do with the result.

    Args:
        images_dir: Directory holding committed alias art.
        alias_map: The alias map that is (or will be) on disk.

    Returns:
        The orphan image paths, sorted by numeric code.
    """
    directory = Path(images_dir)
    if not directory.is_dir():
        return []

    known_ids = {
        int(alias_id) for alias_ids in alias_map.values() for alias_id in alias_ids
    }
    # Keys count too: generate.py caches a family's base art here when the
    # Genesys list names that family by an alternate passcode.
    known_ids.update(int(base_code) for base_code in alias_map)

    orphans: List[Tuple[int, Path]] = []
    for image_path in directory.glob('*.jpg'):
        if not image_path.stem.isdigit():
            continue
        code = int(image_path.stem)
        if code not in known_ids:
            orphans.append((code, image_path))

    return [path for _, path in sorted(orphans)]


def normalize_listed_codes(
    codes: Iterable[int],
    rows: Iterable[Tuple[int, int]],
    names: Dict[int, str],
    scopes: Dict[int, int],
) -> Set[int]:
    """
    Add the base card of every listed code that is itself an alternate art.

    Only rows that pass `is_alternate_art` fold. Fallen of the White Dragon
    (73819701) has `datas.alias` 68468459 because it is always treated as
    Fallen of Albaz, but it is another card: folding it kept Albaz in
    alias.json, so Albaz's stale badge was never unpublished.

    Konami publishes the Genesys list by card name, and evolution-assets
    resolves those names to passcodes through the ygoprodeck API, which may
    return ANY printing's passcode. On 2026-09-23 Monster Reborn moved from
    83764718 (the base card) to 83764719 (one of its alternate arts). Without
    this normalization the whole family disappears: 83764718 is no longer in
    the listed set, so no alias group is derived for it at all.

    The listed code is always kept - it still needs its own image generated.
    The function is pure and idempotent, and a code absent from `rows` simply
    passes through.

    Args:
        codes: The card codes read from the Genesys source.
        rows: Iterable of (id, alias) integer pairs from `datas`, where `id` is
            an alternate-art printing and `alias` is its base card (0 for a
            base card, which is ignored).
        names: Card name (`texts.name`) per id, across all selected databases.
        scopes: `datas.ot` bitmask per id; an id absent here has no extra bits.

    Returns:
        A set with every input code plus the base card of any input code that
        is an alternate-art printing.
    """
    listed = {int(code) for code in codes}
    normalized = set(listed)

    for alias_id, base_code in rows:
        alias_id = int(alias_id)
        base_code = int(base_code)

        # Alias 0 marks a base card, which has no family to fold onto.
        if base_code == 0 or alias_id not in listed:
            continue

        if is_alternate_art(alias_id, base_code, names, scopes):
            normalized.add(base_code)

    return normalized


def load_card_codes(cards_path) -> Set[int]:
    """
    Load the Genesys base card codes from the Genesys list.

    Args:
        cards_path: Path to the Genesys source, either the upstream
            `genesys.lflist.conf` or the legacy local `cards.json`.

    Returns:
        A set of integer card codes.
    """
    return {entry['code'] for entry in genesys_source.load_card_entries(cards_path)}


class AliasSynchronizer:
    """Keeps alias.json and alias_images/ in sync with EDOPro's databases."""

    def __init__(
        self,
        cdb_dirs: List,
        cards_path: str,
        alias_path: str,
        alias_images_dir: str,
    ):
        """
        Initialize the synchronizer.

        Args:
            cdb_dirs: EDOPro database directories, in overlay order
            cards_path: Path to the Genesys list (cards.json or lflist.conf)
            alias_path: Path to alias.json
            alias_images_dir: Directory holding committed alias art
        """
        self.cdb_dirs = [Path(cdb_dir) for cdb_dir in cdb_dirs]
        self.cards_path = Path(cards_path)
        self.alias_path = Path(alias_path)
        self.alias_images_dir = Path(alias_images_dir)

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

        When writing, committed alias images whose code is not in the derived
        map are deleted. In check mode they are reported and count as drift.

        Args:
            check_only: If True, report the drift without writing or deleting.

        Returns:
            The diff dict produced by `diff_alias_maps`, plus `orphan_images`
            (the orphan image paths); `in_sync` is False when either alias.json
            drifted or orphan images exist.
        """
        listed_codes = load_card_codes(self.cards_path)
        rows = read_alias_rows_from_dirs(self.cdb_dirs)
        current = self.load_current_alias_map()

        names = read_names_from_dirs(self.cdb_dirs)
        scopes = read_scopes_from_dirs(self.cdb_dirs)

        # A listed code may be an alternate art rather than the base card, so
        # fold each one back onto its family before grouping.
        codes = normalize_listed_codes(listed_codes, rows, names, scopes)

        derived = build_alias_map(rows, codes, names, scopes)
        diff = diff_alias_maps(current, derived)
        orphans = find_orphan_alias_images(self.alias_images_dir, derived)
        alias_json_in_sync = diff['in_sync']
        diff['orphan_images'] = orphans
        diff['in_sync'] = alias_json_in_sync and not orphans

        alias_row_count = sum(1 for _, alias in rows if alias != 0)
        print(f"📊 Base cards in {self.cards_path.name}: {len(codes)}")
        print(
            f"📊 Alias rows declared by {len(self.cdb_dirs)} database "
            f"directories: {alias_row_count}"
        )
        print(
            f"📊 Alias ids: {sum(len(v) for v in current.values())} on disk -> "
            f"{sum(len(v) for v in derived.values())} derived"
        )

        self._print_diff(diff)
        self._print_orphans(orphans, check_only)

        if check_only:
            if diff['in_sync']:
                print("✅ alias.json and alias_images/ are in sync with EDOPro's databases.")
            else:
                print("❌ alias.json or alias_images/ is out of sync with EDOPro's databases.")
                print("   Run: python3 sync_alias.py --cdb-dir <BabelCDB> --cdb-dir <DeltaBagooska>")
            return diff

        if alias_json_in_sync:
            print("✅ alias.json is already in sync, nothing to write.")
        else:
            self.write_alias_map(derived)
            print(f"💾 Wrote {len(derived)} base cards to {self.alias_path}")

        for image_path in orphans:
            try:
                image_path.unlink()
            except (OSError, IOError) as e:
                print(f"  ⚠️  Could not delete {image_path}: {e}")

        if orphans:
            print(f"🧹 Deleted {len(orphans)} orphan images from {self.alias_images_dir}")

        if not diff['in_sync']:
            print("ℹ️  Remember to commit alias.json and alias_images/.")

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

    def _print_orphans(self, orphans: List[Path], check_only: bool) -> None:
        """
        Print the alias images that are no longer in the alias map.

        Args:
            orphans: Output of `find_orphan_alias_images`.
            check_only: Whether the images will be kept (check) or deleted.
        """
        action = 'would be deleted' if check_only else 'to delete'
        print(f"📊 Orphan alias images ({action}): {len(orphans)}")
        for image_path in orphans:
            print(f"  🧹 {image_path.name}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Derive alias.json from EDOPro's card databases "
                    '(ProjectIgnis/BabelCDB and ProjectIgnis/DeltaBagooska).'
    )
    parser.add_argument(
        '-d', '--cdb-dir', action='append', required=True, dest='cdb_dirs',
        help='Directory of EDOPro .cdb files; repeat it, later directories win '
             '(e.g. --cdb-dir BabelCDB --cdb-dir DeltaBagooska)'
    )
    parser.add_argument(
        '-c', '--cards', default='cards.json',
        help='Path to the Genesys card list, either the upstream '
             'genesys.lflist.conf or cards.json (default: cards.json)'
    )
    parser.add_argument(
        '-a', '--alias', default='alias.json',
        help='Path to the alias JSON file to derive (default: alias.json)'
    )
    parser.add_argument(
        '-i', '--alias-images', default='alias_images',
        help='Directory with committed alias images; images whose code is not '
             'in the derived alias.json are deleted (default: alias_images)'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Report the drift and exit 1 if alias.json or alias_images/ is out '
             'of sync, without writing or deleting anything (for CI)'
    )

    args = parser.parse_args()

    if not Path(args.cards).exists():
        print(f"❌ Error: Required file not found: {args.cards}")
        sys.exit(1)

    for cdb_dir in args.cdb_dirs:
        if not Path(cdb_dir).is_dir():
            print(f"❌ Error: Database directory not found: {cdb_dir}")
            sys.exit(1)

    synchronizer = AliasSynchronizer(
        cdb_dirs=args.cdb_dirs,
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
