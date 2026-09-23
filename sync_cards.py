#!/usr/bin/env python3
"""
Regenerate cards.json from the upstream Genesys point list.

The single source of truth for the Genesys point list is
`lflist/genesys.lflist.conf` in the evolution-assets repository, which a
GitHub Action there regenerates every 6 hours. `cards.json` in this repo used
to be a hand-maintained copy of that list, and a hand-maintained copy always
drifts: it was 29 cards stale when this script was written, which is exactly
the bug class this project already fixed once for alias.json.

So cards.json is now a GENERATED artifact. Do not edit it by hand - change the
upstream list and re-run this script.

The Genesys list is read through `genesys_source`, so `--source` accepts either
the upstream `genesys.lflist.conf` or another `cards.json`. `--source` is
deliberately required: the lflist lives in a different repository and any
default path would be machine-specific.

Usage:
    python3 sync_cards.py --source path/to/genesys.lflist.conf
    python3 sync_cards.py --source path/to/genesys.lflist.conf --check
"""

import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import genesys_source


def build_cards_payload(entries: Iterable[Dict]) -> List[Dict]:
    """
    Build the cards.json payload from normalized Genesys entries.

    The key order (`name`, `points`, `code`) is the one cards.json already uses
    and is preserved so regenerating the file produces a readable diff instead
    of rewriting every line.

    Args:
        entries: Iterable of `{'code', 'points', 'name'}` dicts, as returned by
            `genesys_source.load_card_entries`.

    Returns:
        A list of `{'name': str, 'points': int, 'code': int}` dicts sorted by
        card code ascending.
    """
    cards = [
        {
            'name': str(entry.get('name', '')),
            'points': int(entry.get('points', 0)),
            'code': int(entry['code']),
        }
        for entry in entries
    ]

    return sorted(cards, key=lambda card: card['code'])


def diff_cards(current: Iterable[Dict], generated: Iterable[Dict]) -> Dict:
    """
    Compare the cards.json on disk with the payload that should be written.

    Codes are normalized to int on both sides, so a legacy file storing them as
    strings does not report every card as both added and removed.

    Args:
        current: The card list currently on disk.
        generated: The card list produced by `build_cards_payload`.

    Returns:
        A dict with `added` and `removed` (card code -> name), `changed`
        (card code -> `(old_points, new_points)`), their three counts and
        `in_sync`.
    """
    current_by_code = {int(card['code']): card for card in current}
    generated_by_code = {int(card['code']): card for card in generated}

    added: Dict[int, str] = {
        code: str(generated_by_code[code].get('name', ''))
        for code in sorted(set(generated_by_code) - set(current_by_code))
    }
    removed: Dict[int, str] = {
        code: str(current_by_code[code].get('name', ''))
        for code in sorted(set(current_by_code) - set(generated_by_code))
    }

    changed: Dict[int, Tuple[int, int]] = {}
    for code in sorted(set(current_by_code) & set(generated_by_code)):
        old_points = int(current_by_code[code].get('points', 0))
        new_points = int(generated_by_code[code].get('points', 0))
        if old_points != new_points:
            changed[code] = (old_points, new_points)

    return {
        'added': added,
        'removed': removed,
        'changed': changed,
        'added_count': len(added),
        'removed_count': len(removed),
        'changed_count': len(changed),
        'in_sync': not added and not removed and not changed,
    }


class CardSynchronizer:
    """Keeps cards.json in sync with the upstream Genesys point list."""

    def __init__(self, source_path: str, cards_path: str):
        """
        Initialize the synchronizer.

        Args:
            source_path: Path to the Genesys source (`genesys.lflist.conf`)
            cards_path: Path to the cards.json file to generate
        """
        self.source_path = Path(source_path)
        self.cards_path = Path(cards_path)

    def load_current_cards(self) -> List[Dict]:
        """
        Load the card list currently on disk.

        Returns:
            The parsed cards.json content, or an empty list if the file is absent.
        """
        if not self.cards_path.exists():
            return []

        with open(self.cards_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def write_cards(self, cards: List[Dict]) -> None:
        """
        Write the card list to disk using the project's formatting convention.

        Args:
            cards: The card list to serialize (2-space indent, trailing newline).
        """
        with open(self.cards_path, 'w', encoding='utf-8') as f:
            json.dump(cards, f, indent=2, ensure_ascii=False)
            f.write('\n')

    def sync(self, check_only: bool = False) -> Dict:
        """
        Generate the card list and either report or write it.

        Args:
            check_only: If True, report the diff without writing anything.

        Returns:
            The diff dict produced by `diff_cards`.
        """
        entries = genesys_source.load_card_entries(self.source_path)
        generated = build_cards_payload(entries)
        current = self.load_current_cards()
        diff = diff_cards(current, generated)

        print(f"📊 Genesys entries in {self.source_path.name}: {len(entries)}")
        print(
            f"📊 Cards: {len(current)} in {self.cards_path.name} -> "
            f"{len(generated)} generated"
        )

        self._print_diff(diff)

        if check_only:
            if diff['in_sync']:
                print("✅ cards.json is in sync with the Genesys list.")
            else:
                print("❌ cards.json is out of sync with the Genesys list.")
                print(f"   Run: python3 sync_cards.py --source {self.source_path}")
            return diff

        if diff['in_sync']:
            print("✅ cards.json is already in sync, nothing to write.")
            return diff

        self.write_cards(generated)
        print(f"💾 Wrote {len(generated)} cards to {self.cards_path}")
        print("ℹ️  cards.json is generated - commit it, never hand-edit it.")

        return diff

    def _print_diff(self, diff: Dict) -> None:
        """
        Print the per-card added/removed/changed summary.

        Args:
            diff: The diff dict produced by `diff_cards`.
        """
        print(
            f"📊 Diff: +{diff['added_count']} added, "
            f"-{diff['removed_count']} removed, "
            f"~{diff['changed_count']} point changes"
        )

        for code, name in diff['added'].items():
            print(f"  ➕ {code}: {name}")

        for code, name in diff['removed'].items():
            print(f"  ➖ {code}: {name}")

        for code, (old_points, new_points) in diff['changed'].items():
            print(f"  🔄 {code}: {old_points} -> {new_points} points")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Regenerate cards.json from the upstream Genesys point list.'
    )
    parser.add_argument(
        '-s', '--source', required=True,
        help='Path to the Genesys source list, normally the upstream '
             'genesys.lflist.conf from evolution-assets (required: it lives in '
             'another repository, so there is no sane default)'
    )
    parser.add_argument(
        '-c', '--cards', default='cards.json',
        help='Path to the cards JSON file to generate (default: cards.json)'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Report the diff and exit 1 if cards.json is out of sync, without '
             'writing anything (for CI)'
    )

    args = parser.parse_args()

    if not Path(args.source).exists():
        print(f"❌ Error: Required file not found: {args.source}")
        sys.exit(1)

    synchronizer = CardSynchronizer(
        source_path=args.source,
        cards_path=args.cards,
    )

    diff = synchronizer.sync(check_only=args.check)

    # --check is meant for CI: drift must break the build, not print a warning.
    if args.check and not diff['in_sync']:
        sys.exit(1)


if __name__ == '__main__':
    main()
