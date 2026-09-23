#!/usr/bin/env python3
"""
Read the Genesys card list from either of its two shapes.

The upstream source of truth is `lflist/genesys.lflist.conf` in the
evolution-assets repository, the same three-column file EDOPro consumes:

    #[Genesys]
    !Genesys
    <card id> 3 <points> --<card name>

`cards.json` is the legacy local copy of that list. It is a plain array of
`{name, points, code}` objects that used to be transcribed by hand, which is
precisely the hand-maintained drift this tool exists to eliminate. Reading the
`.conf` directly removes the transcription step, so both shapes are supported
and every consumer gets the same normalized entries.

Only the `!Genesys` section of the `.conf` counts: lines starting with `#` are
comments, a line without the `--` name separator is skipped, and the left side
must split into exactly three columns.
"""

import json
from pathlib import Path
from typing import Dict, List

GENESYS_SECTION = '!Genesys'
CONF_SUFFIX = '.conf'


def load_card_entries(source_path) -> List[Dict]:
    """
    Load the Genesys card entries from a `.conf` or a `.json` source.

    Args:
        source_path: Path to `genesys.lflist.conf` or to `cards.json`. The
            format is chosen by the file suffix, matched case-insensitively.

    Returns:
        A list of `{'code': int, 'points': int, 'name': str}` dicts in file
        order. Entries without a card code are skipped.
    """
    path = Path(source_path)

    if path.suffix.lower() == CONF_SUFFIX:
        return _load_conf_entries(path)

    return _load_json_entries(path)


def _load_conf_entries(conf_path: Path) -> List[Dict]:
    """
    Parse the upstream lflist `.conf` format.

    Args:
        conf_path: Path to a Genesys lflist.conf file.

    Returns:
        A list of `{'code': int, 'points': int, 'name': str}` dicts.
    """
    entries: List[Dict] = []
    in_genesys_section = False

    with open(conf_path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('!'):
                in_genesys_section = line == GENESYS_SECTION
                continue
            if not in_genesys_section or '--' not in line:
                continue

            left, name = line.split('--', 1)
            parts = left.split()
            if len(parts) != 3:
                continue

            code, _copies, points = parts
            try:
                entries.append({
                    'code': int(code),
                    'points': int(points),
                    'name': name.strip(),
                })
            except ValueError:
                print(f"⚠️  Ignoring malformed Genesys list line: {line}")
                continue

    return entries


def _load_json_entries(json_path: Path) -> List[Dict]:
    """
    Parse the legacy local `cards.json` copy of the Genesys list.

    Args:
        json_path: Path to a cards.json file.

    Returns:
        A list of `{'code': int, 'points': int, 'name': str}` dicts.
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        cards = json.load(f)

    entries: List[Dict] = []
    for card in cards:
        if card.get('code') is None:
            continue

        entries.append({
            'code': int(card['code']),
            'points': int(card.get('points', 0)),
            'name': str(card.get('name', '')),
        })

    return entries
