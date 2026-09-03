# Yu-Gi-Oh! Card Image Generator (Cards + Alias) with (Genesys) Points Overlay

A Python tool to generate Yu-Gi-Oh! card images with Genesys point overlays. It can (1) download official card images from YGOPRODeck using `cards.json`, and (2) apply the same point overlays to **alias** (alternate-art) images using `alias.json` + `alias_images/`, downloading any alias art that is not committed locally.

`alias.json` is not hand-maintained: `sync_alias.py` derives it from the EDOPro card database. See [Keeping alias.json in sync](#keeping-aliasjson-in-sync).

## Features

- **Direct image downloads** - No API calls needed, uses direct image URLs
- **Cards + alias support** - Generate downloaded cards, alias cards, or both
- **Derived alias list** - `sync_alias.py` reads the alternate-art printings straight from the EDOPro card database, so new printings never ship without a badge
- **Alias art fallback chain** - Committed art first, then the EDOPro picture mirrors in a deliberate order
- **Unmissable misses** - An alias image no source can serve is reported explicitly and repeated as the last line of the run, so a card shipping without a badge cannot go unnoticed (`--strict` turns it into a non-zero exit for CI)
- **Art caching** - Newly downloaded alias art is written back into `alias_images/` so the curated store survives mirror rot
- **Points overlay** - Automatically adds point values from JSON as visible text on each card
- **Color-coded points** - Background colors change based on point values for quick identification.
- **Smart font sizing** - Automatically scales text size based on image dimensions
- **Simple naming** - Images saved as `{card_code}.jpg` (e.g., `21044178.jpg`)
- **Fast processing** - Efficient image processing with PIL/Pillow
- **Configurable delays** - Respectful rate limiting
- **Comprehensive error handling** - Graceful handling of missing cards or processing errors
- **Progress reporting** - Real-time download and processing progress

## Installation

### Quick Setup (Recommended)

Run the setup script to automatically configure the Python environment:

```bash
./setup.sh
```

### Manual Setup

1. Make sure you have Python 3.8+ installed
2. Create a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```
3. Install dependencies:
```bash
pip install -r requirements.txt
```

**Note**: The script requires Pillow (PIL) for image processing.

## Usage

The main script is `generate.py`. It orchestrates both phases (downloaded cards + local alias images) and writes everything to a single output directory.

### Basic Usage

To regenerate all cards using the default file paths (`cards.json`, `alias.json`, `alias_images`) and save them to the `generated_cards` directory:

```bash
source .venv/bin/activate  # Activate virtual environment first
python3 generate.py
```

The script will first clean the output directory to ensure a fresh build.

### Generate a Single Card (and its Aliases)

To generate **only one** card defined in `cards.json` (and, if present in `alias.json`, also generate its alias images from `alias_images/`), use `--code`:

```bash
python3 generate.py --code 10443957
```

You can also pass multiple codes (repeat the flag or use a comma-separated list):

```bash
python3 generate.py --code 10443957 --code 14532163
python3 generate.py --code 10443957,14532163
```

### Test Run with a Limit

To test the process on a small number of cards, use the `--limit` option. This will only process the first 10 cards from `cards.json` (and all alias cards).

```bash
python3 generate.py --limit 10
```

### Generate Scope (cards vs alias)

By default the script generates **everything** (`all`). You can choose to run only one phase:

```bash
python3 generate.py --generate cards   # Only cards from cards.json
python3 generate.py --generate alias   # Only aliases (still needs cards.json for point values)
python3 generate.py --generate all     # Both (default)
```

`--code` works with these scopes too:

```bash
python3 generate.py --generate cards --code 10443957  # Only the downloaded card for that code
python3 generate.py --generate alias --code 10443957  # Only aliases for that original code
```

### Advanced Usage

You can customize the paths for input files and the output directory.

```bash
python3 generate.py \
    --cards /path/to/your/cards.json \
    --alias /path/to/your/alias.json \
    --alias-images /path/to/your/local_images \
    --output /path/to/final_destination
```

### Keeping alias.json in sync

`alias.json` used to be maintained by hand, which meant new alternate-art printings silently shipped with **no points badge**. `sync_alias.py` derives it instead from the `datas.alias` column of the EDOPro card database, where a row `(id, alias)` means `id` is an alternate-art printing of the base card `alias`.

```bash
python3 sync_alias.py           # rewrite alias.json from the card database
python3 sync_alias.py --check   # report drift and exit 1 without writing (for CI)
```

Only `base.en.cdb` is read. The `pre-errata.*.cdb` overlays are deliberately ignored: they contain Edison-format-only custom codes that never appear in Genesys.

**Existing entries backed by local art are never deleted.** The database is not a superset of the current file: `alias.json` also carries OCG and prerelease codes that came from other databases and that `base.en.cdb` does not declare. Those printings still have real, working art in `alias_images/`, so the derived map is unioned with them. An existing entry is dropped only when it has no file in `alias_images/`.

Options:

- `--cdb`: Path to the EDOPro card database (default: `base.en.cdb` under `evolution-assets/cdb/`).
- `-c, --cards`: Path to the Genesys cards JSON file (default: `cards.json`).
- `-a, --alias`: Path to the alias JSON file to derive (default: `alias.json`).
- `-i, --alias-images`: Directory with committed alias images, whose entries are never dropped (default: `alias_images`).
- `--check`: Report the diff and exit 1 if out of sync, writing nothing.

### Optional: Download-only helper

If you only want to download card images (with overlay) into a separate folder, you can use:

```bash
python3 card_downloader.py --help
```

### Command Line Options

- `-c, --cards`: Path to the cards JSON file (default: `cards.json`).
- `-a, --alias`: Path to the alias JSON file (default: `alias.json`).
- `-i, --alias-images`: Directory with pre-downloaded alias images (default: `alias_images`).
- `-o, --output`: Unified output directory for all generated cards (default: `generated_cards`).
- `-d, --delay`: Delay between downloads in seconds (default: 0.1).
- `-l, --limit`: For testing, limits the number of cards processed from `cards.json` (default: all).
- `-hq, --high-quality`: Generate high quality images (original size) instead of optimized thumbnails.
- `-g, --generate`: What to generate: `all`, `cards`, `alias` (default: `all`).
- `--code`: Generate only a specific card code from `cards.json` (repeatable or comma-separated). When generating aliases, only aliases for these **original** codes are processed.
- `--no-cache-alias-images`: Do not write newly downloaded alias art back into the alias images directory. By default it *is* cached, so the curated store stops depending on the mirrors.

## JSON File Format

### cards.json

`cards.json` should contain an array of card objects with at least a `code` field:

```json
[
  {
    "code": 21044178,
    "name": "深渊的潜伏者",
    "points": 100
  },
  {
    "code": 98287529,
    "name": "虚龙魔王 无形矢·心灵",
    "points": 67
  }
]
```

Required fields:
- `code`: The Yu-Gi-Oh! card ID/code (integer).
- `points`: The point value (integer) to be overlaid on the card image.

Optional fields:
- `name`: Card name, used for progress messages in the console.

### alias.json

`alias.json` maps an **original** card code (must exist in `cards.json`) to a list of **alias** card codes. It is generated by `sync_alias.py` - edit the card database, not this file.

```json
{
  "21044178": [14532164, 12580478],
  "98287529": [10802916]
}
```

An alias does not need a local image at `alias_images/{alias_code}.jpg`: if the file is absent, the art is downloaded from the mirrors and (unless `--no-cache-alias-images` is passed) saved there for next time. If **no** source can provide it, the code is reported and the run still succeeds; pass `--strict` to fail instead.

## Output

All generated images are saved to the output directory (default: `generated_cards`).

- **Standard Mode (Default)**: All cards are resized to a compact size (`177x254`) to optimize file size (approx. 10-30KB per image).
- **High Quality Mode (`--high-quality`)**: Images keep their original resolution (usually larger) for better visual quality, but larger file sizes.
- **File Naming**: Images are saved as `{card_code}.jpg`.

### Point Overlay System

Each card image will have its point value displayed in the **bottom-left corner** with:
- **Large, readable text** - Automatically sized based on image dimensions (minimum 60px)
- **Properly sized colored background** - Rectangle automatically fits the number perfectly
- **Color-coded backgrounds** for quick identification:
  - 🔴 **Red background** (white text): 50+ points
  - 🟠 **Orange background** (black text): 20-49 points  
  - 🟡 **Yellow background** (black text): 10-19 points
  - 🟢 **Green background** (black text): 1-9 points
- **Semi-transparent background** - Points are visible without completely obscuring the card art
- **Centered text** - Numbers are centered within their colored rectangles
- **System font detection** - Works with any suitable font available on the system, with a graceful fallback if none are found.

All images are high-quality JPEG files with the point values clearly overlaid.

## Image Sources

Base cards and alias (alternate-art) printings do **not** come from the same place, because no single source covers both.

### Base cards (`cards.json`)

Downloaded directly from YGOPRODeck:

```
https://images.ygoprodeck.com/images/cards/{card_code}.jpg
```

This approach is faster (no API calls), more reliable (direct image access) and simpler (consistent naming scheme). YGOPRODeck covers alias printings very poorly, so it is used for base cards only.

### Alias printings (`alias.json`)

Resolved through a fallback chain, in this exact order:

1. **`alias_images/{alias_code}.jpg`** - committed art. This is the curated tier and always wins; a local hit skips the network entirely.
2. **`https://pics.projectignis.org:2096/pics/{code}.jpg`** - Project Ignis, EDOPro's own compiled-in picture source. It is tried first among the mirrors because the client itself ships these images, so the generated badges sit on exactly the art players already see, and it already serves the `177x254` size this tool targets.
3. **`https://cdn.233.momobako.com/ygopro/pics/{code}.jpg`** - a last resort. It serves larger scans with Chinese card text, which is visually inconsistent with the rest of the pack, but it is the only source that covers the remaining printings.

A dead mirror is logged as a warning and the chain continues. Whatever is downloaded is written back into `alias_images/` by default so the curated store keeps growing and stops depending on the mirrors - the script prints the list of saved files so you know what to commit.

## Rate Limiting

The script includes configurable delays between downloads to be respectful:
- Default: 0.1 seconds (adjustable with `-d`)

You can adjust this value based on your needs, but please be considerate.

## Error Handling

The script handles various error conditions:
- Missing or invalid JSON files
- Network connectivity issues
- Missing card images
- Image processing errors
- File system errors

When a **base card** fails to process, the script logs the error and continues with the remaining items.

### Unresolvable alias images

An alias image that no source can serve does **not** abort the run. The output is
954 independent files that the client reads one card at a time, so a card whose
art is unavailable degrades on its own — EDOPro falls back to the unbadged art it
downloads itself — while every other card ships correctly. Aborting would withhold
953 good images over one rarely-played card.

It is still made impossible to overlook, because silent skipping is exactly how 62
alias cards ended up shipping with no points badge for months:

1. Every unresolvable code is collected and the full list is printed, so one run
   reports every problem rather than only the first.
2. The list is repeated as the **last line of the run**, below the completion
   banner, where the phase summary would otherwise have scrolled out of view.
3. `--strict` exits with status `1` on any miss, for a pipeline that wants the
   hard stop.

To resolve a miss: add the art to `alias_images/` and commit it, or remove the
entry from `alias.json`.

## Testing

```bash
source .venv/bin/activate
python3 -m pytest tests/ -q
```

The suite is offline: network access is faked by injecting a stub session, so the tests never touch the mirrors.

## Example Output

```
🧹 Cleaning output directory: /.../generated_cards
💾 Output will be saved to: /.../generated_cards
📉 Standard Mode: ON (Optimized/Thumbnail sizes)

--- Phase 1: Processing Primary Cards (from cards.json) ---
[1/2681] Downloading: 深渊的潜伏者 (Code: 21044178, Points: 100)
  ✅ Generated: 21044178.jpg

...

--- Phase 2: Processing Alias Cards (from alias.json) ---
Processing aliases for: 深渊的潜伏者 (Code: 21044178, Points: 100)
  ✅ Generated: 14532164.jpg (source: local)
  ✅ Generated: 12580478.jpg (source: https://pics.projectignis.org:2096/pics)

--- Phase 2 Summary ---
✅ Successfully generated: 2/2 alias cards

💾 Cached 1 newly downloaded alias images in alias_images:
  💾 12580478.jpg
ℹ️  Commit these files so the pack no longer depends on the mirrors.

🎉 Full regeneration process completed!
```

## License

This project is provided as-is for educational and personal use. Please respect the terms of service of the YGOPRODeck API and Yu-Gi-Oh! card image copyrights.