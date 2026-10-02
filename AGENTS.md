# AGENTS.md - Genesys Card Generator

## Project Overview

Python tool that generates Yu-Gi-Oh! card images with Genesys point overlays.
Downloads card art (base cards from YGOPRODeck, prerelease and alternate-art printings from
Project Ignis, EDOPro's picture source) and composites point badges onto card
images. The Python sources are the seven top-level `*.py` files listed under
Project Structure.

**Language:** Python 3.8+
**Dependencies:** `requests`, `Pillow` (managed via `requirements.txt`)

## Project Structure

```
genesys-card-generator/
  generate.py            # Main entry point - orchestrates card + alias generation
  card_downloader.py     # Core library - image download + overlay compositing
  sync_cards.py          # Regenerates cards.json from the upstream Genesys lflist
  sync_alias.py          # Derives alias.json from EDOPro's card databases
  genesys_source.py      # Reads the Genesys list (lflist.conf or cards.json)
  sync_pictures.py       # Publishes generated_cards/ into genesys-pictures pics/
  apply_alias_overlay.py # Standalone alias overlay processor (imports card_downloader)
  cards.json             # Card data: array of {name, points, code} (generated)
  alias.json             # Maps original card codes -> alias card codes (derived)
  alias_images/          # Committed alias card images (.jpg) - the curated tier
  tests/                 # pytest suite (test_*.py) + conftest.py for sys.path
  requirements.txt       # Python deps (requests, Pillow, pytest)
  setup.sh               # Bootstrap script (creates venv, installs deps)
  .github/workflows/publish.yml # Scheduled sync + image publish to genesys-pictures
  generated_cards/       # Output directory (gitignored)
  downloaded_cards/      # Alt output directory (gitignored)
```

## Setup & Run Commands

```bash
# First-time setup
./setup.sh
# OR manually:
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Activate venv (always required before running)
source .venv/bin/activate

# Generate all cards (downloads + alias overlays)
python3 generate.py

# Generate a single card by code
python3 generate.py --code 10443957

# Generate multiple specific cards
python3 generate.py --code 10443957,14532163

# Generate only downloaded cards (no alias)
python3 generate.py --generate cards

# Generate only alias images
python3 generate.py --generate alias

# Test run with limited cards
python3 generate.py --limit 10

# High quality mode (original resolution)
python3 generate.py --high-quality

# Download-only helper (standalone)
python3 card_downloader.py --help

# Regenerate cards.json from the upstream Genesys lflist (cards.json is GENERATED)
python3 sync_cards.py --source /path/to/evolution-assets/lflist/genesys.lflist.conf

# Verify cards.json is in sync without writing (exits 1 on drift - use in CI)
python3 sync_cards.py --source /path/to/evolution-assets/lflist/genesys.lflist.conf --check

# Derive alias.json from EDOPro's card databases (Project Ignis). Shallow-clone
# both repos, then pass both directories - BabelCDB first so the delta wins:
git clone --depth 1 https://github.com/ProjectIgnis/BabelCDB.git /tmp/BabelCDB
git clone --depth 1 https://github.com/ProjectIgnis/DeltaBagooska.git /tmp/DeltaBagooska
python3 sync_alias.py --cdb-dir /tmp/BabelCDB --cdb-dir /tmp/DeltaBagooska

# Verify alias.json and alias_images/ are in sync without writing or deleting
# (exits 1 on drift - use in CI)
python3 sync_alias.py --cdb-dir /tmp/BabelCDB --cdb-dir /tmp/DeltaBagooska --check

# Publish images into a genesys-pictures checkout (THE publish command), then
# commit + push in that repo. Preview first with --dry-run.
python3 sync_pictures.py --target /path/to/genesys-pictures/pics --dry-run
python3 sync_pictures.py --target /path/to/genesys-pictures/pics

# Run the test suite
python3 -m pytest tests/ -q
```

## Publishing Pictures

`sync_pictures.py` is the only way images reach `evolutionygo/genesys-pictures`
(`pics/`, read by EDOPro), both in `publish.yml` and manually
(`python3 sync_pictures.py --target <genesys-pictures>/pics`, then commit with
`git add -A` and push in that repo). It copies every generated `*.jpg`
(overwrite propagates point updates), deletes a `pics/*.jpg` only when its code
is not in the data (every `cards.json` code plus every key and value of
`alias.json`), and keeps + reports desired images not generated this run.
Non-`.jpg` files are never touched.

It is deliberately NOT `rsync --delete`: `generate.py` continues past a failed
download, so a transient 404 would unpublish a still-valid card. The keep-set
comes from the data, never from this run's output.

Safety guard (pure `check_safety`): it refuses, exit 1 and nothing changed,
when the desired set is empty or the plan deletes more than 25% of the existing
`pics/*.jpg`, so a broken cards.json or empty run cannot wipe production.
`--force` bypasses it.

## Alias Derivation

Images target EDOPro only. An alternate art is any code that EDOPro's own card
databases declare with `datas.alias` pointing to a Genesys base card. Those
databases come from two Project Ignis repos (default branch `master`):

- `ProjectIgnis/BabelCDB` - full databases
- `ProjectIgnis/DeltaBagooska` - updates

`sync_alias.py` reads every `*.cdb` in each `--cdb-dir`, except files whose name
contains `rush`, `skills` or `goat` (case-insensitive) - Rush Duel, skill cards
and GOAT never appear in Genesys. Files are discovered by globbing because
prerelease names change. Overlay order: directories in the order given, files
within a directory in sorted name order, later rows for the same `id` win - so
pass BabelCDB first and DeltaBagooska second. The derivation is authoritative:
ids EDOPro does not declare are removed from alias.json and their images are
deleted from `alias_images/` (`--check` reports them as drift). Alias art is
fetched from Project Ignis (`https://pics.projectignis.org:2096/pics`), which
serves every alias EDOPro declares.

## Testing

`pytest` is the test framework (declared in `requirements.txt`). Tests live in
`tests/` and follow the `test_*.py` naming convention. `tests/conftest.py` puts
the project root on `sys.path` so test modules can `import generate`,
`import card_downloader` and `import sync_alias` directly.

```bash
.venv/bin/python -m pytest tests/ -q          # whole suite
.venv/bin/python -m pytest tests/test_sync_alias.py -q   # one module
```

Current modules:

| File                            | Covers                                                        |
|---------------------------------|---------------------------------------------------------------|
| `tests/test_sync_cards.py`      | cards.json payload build, sorting, added/removed/point diff    |
| `tests/test_sync_alias.py`      | Database selection, overlay read, alias derivation, orphan-image pruning, diff, CLI |
| `tests/test_card_downloader.py` | Alias art source, source fallback ordering, local cache hit, prerelease base-art source + fallback |
| `tests/test_generate.py`        | Alias phase: caching fetched art, reporting misses, `--strict`; Phase 1 art source + per-card isolation |
| `tests/test_sync_pictures.py`   | Desired set, copy/delete/stale plan, 25% guard, `--force`, dry run |

**Tests must never hit the network.** Inject a fake session (an object with a
`.get()` returning a stub exposing `.content` and `.raise_for_status()`) into
`YugiohCardDownloader.session`, and use `tmp_path` for anything on disk. Pure
logic (`select_edopro_databases`, `build_alias_map`, `normalize_listed_codes`,
`diff_alias_maps`) is kept at module level in `sync_alias.py` precisely so it
can be tested with plain data and no I/O. Tests never read real `.cdb` files:
build tiny sqlite fixtures in `tmp_path`.

New logic is written test-first: add the failing test, watch it fail, then
implement until green.

## Linting / Formatting

No linting or formatting tools are configured. No `.flake8`, `pyproject.toml`,
`mypy.ini`, or similar config files exist. If adding tooling, prefer `ruff` for
linting+formatting and `mypy` for type checking.

## Code Style Guidelines

### File Structure

Every Python source file follows this structure:
1. Shebang line: `#!/usr/bin/env python3`
2. Module-level docstring (triple-quoted)
3. Standard library imports
4. Third-party imports
5. Local imports
6. One main class
7. A `main()` function with `argparse`
8. `if __name__ == '__main__':` guard

### Imports

- Follow PEP 8 import order: stdlib, third-party, local
- Use `from pathlib import Path` (not `os.path`) for all file path handling
- Use `from typing import Dict, List, Optional` for type hints (Python 3.8 compat)
- Deferred imports are used inside `__init__` or `main()` when the module should
  remain importable without all dependencies (e.g., for `--help` to work)

### Naming Conventions

| Element         | Convention        | Example                        |
|-----------------|-------------------|--------------------------------|
| Classes         | `PascalCase`      | `CardRegenerator`              |
| Methods         | `snake_case`      | `run_regeneration`             |
| Private methods | `_leading_underscore` | `_load_cards_data`         |
| Constants       | `UPPER_SNAKE_CASE`| `BASE_IMAGE_URL`               |
| Variables       | `snake_case`      | `total_cards`, `success_count` |
| CLI arguments   | `--kebab-case`    | `--high-quality`, `--alias-images` |

### Type Hints

- Always add type hints to method signatures (parameters and return types)
- Use `typing` module types (`Dict`, `List`, `Optional`) for Python 3.8 compat
- Do NOT use modern union syntax (`str | None`) - use `Optional[str]` instead

### Docstrings

Use Google-style docstrings with `Args:` and `Returns:` sections:

```python
def process_card(self, card_code: str, points: int) -> bool:
    """
    Process a single card image with overlay.

    Args:
        card_code: The Yu-Gi-Oh! card ID
        points: Point value to overlay

    Returns:
        True if processing succeeded, False otherwise.
    """
```

### Error Handling

- Wrap individual item processing in `try/except` so one failure does not stop
  the batch. Log the error and continue.
- Use specific exceptions where possible: `requests.exceptions.RequestException`,
  `(OSError, IOError)` for file/font operations.
- Use broad `except Exception as e` only as a last-resort catch-all per item.
- Use `sys.exit(1)` for fatal/unrecoverable errors (missing required files, etc.).
- Avoid bare `except:` clauses.

### Console Output

- Use emoji-prefixed print statements for user-facing progress:
  - `"[{i}/{total}]"` for progress counters
- Standard emoji conventions in this codebase:
  - Success: print with prefix (card processed successfully)
  - Error: print with prefix (processing failed)
  - Warning: print with prefix (non-critical issue)
  - Cleanup: print with prefix (directory operations)
  - Stats: print with prefix (summary/statistics)
  - Completion: print with prefix (final success message)

### Class Design

- One class per file, encapsulating all related logic
- State initialized in `__init__` (paths, config, loaded data)
- `card_downloader.py` serves as both a standalone CLI and an importable library
- `generate.py` is the primary entry point that orchestrates the other modules

### File I/O

- Use `pathlib.Path` for all path operations (never raw `os.path`)
- Use `open(..., 'r', encoding='utf-8')` for text/JSON files
- Use `io.BytesIO` for in-memory image manipulation
- Use `shutil.rmtree` for directory cleanup

### CLI Arguments

- Use `argparse.ArgumentParser` for all CLI interfaces
- Provide both short (`-c`) and long (`--cards`) flag variants
- Include sensible defaults for all arguments

## Git Conventions

### Commit Messages

Follow **Conventional Commits** format:
- `feat:` new features
- `fix:` bug fixes
- `refactor:` code restructuring without behavior change
- `chore:` maintenance, data updates
- `docs:` documentation changes

Examples:
```
feat: add support for generating specific card codes with --code option
fix: correct points and code values for "Change of Heart"
chore: update genesys points 30/01/26
refactor: adjust font scale for high quality mode
```

### Branch Strategy

Single branch: `main`. All work is done directly on main.

### What NOT to Commit

The `.gitignore` excludes: virtual environments (`.venv/`, `venv/`), generated
output directories (`generated_cards/`, `downloaded_cards/`), Python bytecode
(`__pycache__/`, `*.pyc`), IDE files, OS files, and `.zip` archives.
