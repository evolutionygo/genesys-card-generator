#!/usr/bin/env python3
"""
Publish generated card images into the genesys-pictures `pics/` folder.

EDOPro reads the `pics/` folder of `evolutionygo/genesys-pictures`. Publishing
used to be a plain copy of `generated_cards/*.jpg` into it, which only adds and
overwrites: a card that leaves the Genesys list, or an alias art that is no
longer derived, kept its badged image forever.

`rsync --delete generated_cards/ pics/` is NOT the fix. generate.py continues
past a failed download, so a transient 404 would drop a still-valid card from
this run's output and rsync would then delete it from production. The set of
images to keep is therefore derived from the DATA (cards.json + alias.json),
never from what happened to be generated in this run:

- every generated image is copied (overwriting is how point updates propagate);
- a target image is deleted only when its code is not in the data;
- a desired image that was not generated this run is kept and reported.

Usage:
    python3 sync_pictures.py --target path/to/genesys-pictures/pics
    python3 sync_pictures.py --target path/to/genesys-pictures/pics --dry-run
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set

# Refuse to delete more than this fraction of the published images without
# --force. A normal Genesys list update removes a handful of cards; losing a
# quarter of production in one run means the input data is broken.
MAX_DELETE_RATIO = 0.25

IMAGE_SUFFIX = '.jpg'


class UnsafeSyncError(Exception):
    """Raised when a sync plan would remove too much of production."""


def _code_sort_key(code: str) -> tuple:
    """
    Sort card codes numerically, falling back to text for odd names.

    Args:
        code: A card code (file stem)

    Returns:
        A sort key placing numeric codes first in numeric order.
    """
    return (0, int(code), '') if code.isdigit() else (1, 0, code)


def _jpg_names(names: Iterable[str]) -> List[str]:
    """
    Keep only `*.jpg` file names, sorted by code.

    Args:
        names: File names

    Returns:
        The `.jpg` names sorted by their code.
    """
    jpgs = [name for name in names if Path(name).suffix == IMAGE_SUFFIX]
    return sorted(jpgs, key=lambda name: _code_sort_key(Path(name).stem))


def desired_codes(cards: Iterable[Dict], alias_map: Dict) -> Set[str]:
    """
    Derive every card code whose image must stay published.

    Alias KEYS are included too: when Konami lists a family by an alternate
    passcode, generate.py also generates the family's base key.

    Args:
        cards: The cards.json content (dicts with a `code`)
        alias_map: The alias.json content (code -> list of alias codes)

    Returns:
        The set of codes, as strings.
    """
    desired = {str(card['code']) for card in cards}

    for key, value in alias_map.items():
        desired.add(str(key))
        values = value if isinstance(value, list) else [value]
        desired.update(str(alias_code) for alias_code in values)

    return desired


def plan_sync(
    generated_files: Iterable[str],
    target_files: Iterable[str],
    desired: Set[str],
) -> Dict:
    """
    Plan which images to copy, delete and keep. Only `*.jpg` names count.

    Args:
        generated_files: File names in the generated output directory
        target_files: File names currently in the target `pics/` directory
        desired: Codes that must stay published (see `desired_codes`)

    Returns:
        A dict with `copy` (generated file names), `delete` (target file names
        whose code is not desired) and `stale_kept` (desired codes present in
        the target but not generated this run).
    """
    generated = _jpg_names(generated_files)
    target = _jpg_names(target_files)
    generated_codes = {Path(name).stem for name in generated}

    delete = [name for name in target if Path(name).stem not in desired]
    stale_kept = [
        Path(name).stem for name in target
        if Path(name).stem in desired and Path(name).stem not in generated_codes
    ]

    return {'copy': generated, 'delete': delete, 'stale_kept': stale_kept}


def check_safety(
    plan: Dict,
    target_files: Iterable[str],
    desired: Set[str],
    force: bool = False,
) -> None:
    """
    Refuse a plan that looks like broken input rather than a real update.

    A broken cards.json/alias.json or an empty generation run must not wipe
    production: an empty desired set would delete every published image, and
    a deletion larger than MAX_DELETE_RATIO of the target is far beyond any
    real Genesys list change. `force` is the explicit override.

    Args:
        plan: The plan returned by `plan_sync`
        target_files: File names currently in the target directory
        desired: The desired code set
        force: Skip the guard

    Raises:
        UnsafeSyncError: If the plan is unsafe and `force` is False.
    """
    if force:
        return

    if not desired:
        raise UnsafeSyncError(
            'The desired code set is empty (broken cards.json/alias.json?); '
            'refusing to delete every published image.'
        )

    target_count = len(_jpg_names(target_files))
    delete_count = len(plan['delete'])
    if target_count and delete_count / target_count > MAX_DELETE_RATIO:
        raise UnsafeSyncError(
            f'Refusing to delete {delete_count} of {target_count} published '
            f'images (more than {int(MAX_DELETE_RATIO * 100)}%). '
            'Re-run with --force if this is intended.'
        )


class PictureSynchronizer:
    """Mirrors generated images into the published pics/ folder safely."""

    def __init__(self, generated_dir: str, target_dir: str, cards_path: str, alias_path: str):
        """
        Initialize the synchronizer.

        Args:
            generated_dir: Directory holding this run's generated images
            target_dir: The published `pics/` directory
            cards_path: Path to cards.json
            alias_path: Path to alias.json
        """
        self.generated_dir = Path(generated_dir)
        self.target_dir = Path(target_dir)
        self.cards_path = Path(cards_path)
        self.alias_path = Path(alias_path)

    def _load_json(self, path: Path, default):
        """
        Load a JSON file, or return a default when it is absent.

        Args:
            path: File to read
            default: Value returned when the file does not exist

        Returns:
            The parsed content or `default`.
        """
        if not path.exists():
            return default

        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def _list_names(directory: Path) -> List[str]:
        """
        List the file names in a directory.

        Args:
            directory: Directory to list

        Returns:
            File names, or an empty list if the directory is absent.
        """
        if not directory.is_dir():
            return []
        return [path.name for path in directory.iterdir() if path.is_file()]

    def sync(self, dry_run: bool = False, force: bool = False) -> Dict:
        """
        Copy every generated image, then delete images no longer in the data.

        Args:
            dry_run: Compute and report the plan without touching the target
            force: Bypass the safety guard

        Returns:
            A dict with `copied`, `deleted` and `stale_kept` counts plus the
            `deleted_codes` and `stale_kept_codes` lists.

        Raises:
            UnsafeSyncError: If the safety guard trips (nothing is changed).
        """
        cards = self._load_json(self.cards_path, [])
        alias_map = self._load_json(self.alias_path, {})
        desired = desired_codes(cards, alias_map)

        target_files = self._list_names(self.target_dir)
        plan = plan_sync(self._list_names(self.generated_dir), target_files, desired)
        check_safety(plan, target_files, desired, force=force)

        if not dry_run:
            self.target_dir.mkdir(parents=True, exist_ok=True)
            for name in plan['copy']:
                shutil.copy2(self.generated_dir / name, self.target_dir / name)
            for name in plan['delete']:
                (self.target_dir / name).unlink()

        return {
            'copied': len(plan['copy']),
            'deleted': len(plan['delete']),
            'stale_kept': len(plan['stale_kept']),
            'deleted_codes': [Path(name).stem for name in plan['delete']],
            'stale_kept_codes': list(plan['stale_kept']),
        }


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Publish generated card images into the genesys-pictures '
                    'pics/ folder, deleting only images no longer in the data.'
    )
    parser.add_argument(
        '-t', '--target', required=True,
        help='The genesys-pictures pics/ directory to publish into (required)'
    )
    parser.add_argument(
        '-g', '--generated', default='generated_cards',
        help='Directory with the generated images (default: generated_cards)'
    )
    parser.add_argument(
        '-c', '--cards', default='cards.json',
        help='Path to cards.json (default: cards.json)'
    )
    parser.add_argument(
        '-a', '--alias', default='alias.json',
        help='Path to alias.json (default: alias.json)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Report what would change without touching the target'
    )
    parser.add_argument(
        '--force', action='store_true',
        help=f'Bypass the safety guard (empty data or deleting more than '
             f'{int(MAX_DELETE_RATIO * 100)}%% of the published images)'
    )

    args = parser.parse_args()

    synchronizer = PictureSynchronizer(
        generated_dir=args.generated,
        target_dir=args.target,
        cards_path=args.cards,
        alias_path=args.alias,
    )

    try:
        result = synchronizer.sync(dry_run=args.dry_run, force=args.force)
    except UnsafeSyncError as e:
        print(f"❌ {e}")
        sys.exit(1)

    prefix = "🔍 Dry run - " if args.dry_run else ""
    print(
        f"📊 {prefix}copied: {result['copied']}, deleted: {result['deleted']}, "
        f"stale_kept: {result['stale_kept']}"
    )
    for code in result['deleted_codes']:
        print(f"  🗑️  delete {code}.jpg")
    for code in result['stale_kept_codes']:
        print(f"  ⚠️  kept (not generated this run) {code}.jpg")

    print("✅ Dry run complete, nothing changed." if args.dry_run else "✅ Pictures synced.")


if __name__ == '__main__':
    main()
