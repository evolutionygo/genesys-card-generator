#!/usr/bin/env python3
"""
Generate Yu-Gi-Oh! Card Images with Genesys Points Overlay

This script generates card images with point overlays and can run one or both phases:
1. Download cards from a Genesys list source (.json or .lflist.conf) and apply point overlays.
2. Apply point overlays to pre-downloaded alias images (alias.json + alias_images/).

All generated images are saved to a single output directory with consistent overlay settings.
"""

import json
import os
import sys
import time
import shutil
from pathlib import Path
from typing import Dict, List, Optional


class CardRegenerator:
    """Orchestrates the full card regeneration process."""

    def __init__(
        self,
        cards_path: str,
        alias_path: Optional[str],
        alias_images_dir: Optional[str],
        output_dir: str,
        delay: float,
        generation: str = "all",
        codes: Optional[List[str]] = None,
    ):
        """
        Initialize the regenerator.

        Args:
            cards_path: Path to cards.json
            alias_path: Path to alias.json
            alias_images_dir: Directory with pre-downloaded alias images
            output_dir: Directory to save all generated cards
            delay: Delay between downloads
            generation: What to generate: all, cards, alias
        """
        self.cards_path = Path(cards_path)
        self.alias_path = Path(alias_path) if alias_path else None
        self.alias_images_dir = Path(alias_images_dir) if alias_images_dir else None
        self.output_dir = Path(output_dir)
        self.delay = delay
        self.generation = generation
        self.codes_filter = {str(c) for c in (codes or [])} or None

        # Import here so `--help` works even without deps installed
        from card_downloader import YugiohCardDownloader

        # This will be used for applying overlays and for downloading
        self.downloader = YugiohCardDownloader(output_dir=str(self.output_dir), delay=self.delay)

        # Load data
        self.cards_data = self._load_cards_data()
        self.alias_data = self._load_alias_data() if self.alias_path else {}

        # Clean and recreate the output directory
        if self.output_dir.exists():
            print(f"🧹 Cleaning output directory: {self.output_dir.absolute()}")
            shutil.rmtree(self.output_dir)

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        print(f"💾 Output will be saved to: {self.output_dir.absolute()}")

    def _load_cards_data(self) -> Dict:
        """Load a Genesys source file and create a lookup dictionary by code."""
        if self.cards_path.suffix.lower() == '.conf':
            return self._load_cards_conf()

        with open(self.cards_path, 'r', encoding='utf-8') as f:
            cards_list = json.load(f)
        return {str(card.get('code')): card for card in cards_list}

    def _load_cards_conf(self) -> Dict:
        """Load a Genesys lflist.conf file and create a lookup dictionary by code."""
        cards: Dict[str, Dict] = {}
        in_genesys_section = False

        with open(self.cards_path, 'r', encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    continue
                if line.startswith('!'):
                    in_genesys_section = line == '!Genesys'
                    continue
                if not in_genesys_section:
                    continue
                if '--' not in line:
                    continue

                left, name = line.split('--', 1)
                parts = left.split()
                if len(parts) != 3:
                    continue

                code, copies, points = parts
                cards[str(code)] = {
                    'code': int(code),
                    'copies': int(copies),
                    'name': name.strip(),
                    'points': int(points),
                }

        return cards

    def _load_alias_data(self) -> Dict:
        """Load alias.json."""
        if not self.alias_path:
            return {}
        with open(self.alias_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def run_regeneration(self, limit: int = None, high_quality: bool = False):
        """Execute regeneration process based on generation scope."""
        # Determine font scale based on quality setting
        font_scale = 1.40 if high_quality else 0.70
        
        if high_quality:
            print("✨ High Quality Mode: ON (Original image sizes)")
        else:
            print("📉 Standard Mode: ON (Optimized/Thumbnail sizes)")

        if self.generation in ("all", "cards"):
            self.process_primary_cards(limit=limit, font_scale=font_scale, high_quality=high_quality)

        if self.generation in ("all", "alias"):
            # Phase 2: Alias Cards
            # Alias cards always use the specific font scale, but we match the
            # high_quality flag to preserve image fidelity if requested (no resize/compression).
            print(
                f"\nℹ️  Alias cards will be processed with Scale 0.70 and Quality: {'High' if high_quality else 'Standard'}"
            )
            self.process_alias_cards(font_scale=0.70, high_quality=high_quality)
        
        if self.generation == "cards":
            print("\n🎉 Card generation completed (cards only)!")
        elif self.generation == "alias":
            print("\n🎉 Card generation completed (alias only)!")
        else:
            print("\n🎉 Full regeneration process completed!")

    def process_primary_cards(self, limit: int = None, font_scale: float = 0.5, high_quality: bool = False):
        """Phase 1: Download and apply overlays for cards in cards.json."""
        print("\n--- Phase 1: Processing Primary Cards (from source file) ---")
        
        cards_to_process = list(self.cards_data.items())
        if self.codes_filter:
            cards_to_process = [(code, data) for (code, data) in cards_to_process if code in self.codes_filter]
            missing = sorted(self.codes_filter.difference(self.cards_data.keys()))
            if missing:
                print(f"❌ Error: The following --code values were not found in cards.json: {', '.join(missing)}")
                sys.exit(1)

        if limit:
            print(f"⚠️  Processing a limited set of {limit} cards for this test run.")
            cards_to_process = cards_to_process[:limit]

        total_cards = len(cards_to_process)
        success_count = 0
        
        for i, (card_code, card_data) in enumerate(cards_to_process, 1):
            points = card_data.get('points', 0)
            name = card_data.get('name', f"Card {card_code}")
            
            print(f"[{i}/{total_cards}] Downloading: {name} (Code: {card_code}, Points: {points})")

            # We use the downloader's direct image URL and session
            image_url = f"{self.downloader.BASE_IMAGE_URL}/{card_code}.jpg"
            filename = f"{card_code}.jpg"
            output_path = self.output_dir / filename

            try:
                # 1. Download image
                response = self.downloader.session.get(image_url, timeout=30)
                response.raise_for_status()
                
                # 2. Apply overlay with consistent settings
                # Use custom_quality=50 to keep file size down even in HQ mode (since images are large)
                modified_image_data = self.downloader.add_points_overlay(
                    response.content, points, font_scale=font_scale, high_quality=high_quality, custom_quality=50
                )

                # 3. Save to the unified output directory
                with open(output_path, 'wb') as f:
                    f.write(modified_image_data)
                
                print(f"  ✅ Generated: {filename}")
                success_count += 1

            except Exception as e:
                print(f"  ❌ FAILED to process {card_code}: {e}")

            if i < total_cards:
                time.sleep(self.delay)

        print(f"\n--- Phase 1 Summary ---")
        print(f"✅ Successfully generated: {success_count}/{total_cards} primary cards")


    def process_alias_cards(self, font_scale: float = 0.5, high_quality: bool = False):
        """Phase 2: Apply overlays for alias cards from alias.json."""
        print("\n--- Phase 2: Processing Alias Cards (from alias.json) ---")
        if not self.alias_images_dir:
            print("❌ Error: alias_images_dir was not provided, cannot process aliases.")
            return
        if not self.alias_data:
            print("⚠️  No alias data loaded (alias.json missing or empty), nothing to do.")
            return
        alias_items = list(self.alias_data.items())
        if self.codes_filter:
            # Only process aliases for the requested original card codes
            alias_items = [(k, v) for (k, v) in alias_items if str(k) in self.codes_filter]
            if not alias_items:
                print("ℹ️  No aliases found for the provided --code value(s).")
                return

        total_aliases = sum(len(v) for _, v in alias_items)
        processed_count = 0
        skipped_count = 0

        for original_code, alias_list in alias_items:
            if original_code not in self.cards_data:
                print(f"⚠️  Original card {original_code} not found, skipping its aliases")
                skipped_count += len(alias_list)
                continue

            original_card = self.cards_data[original_code]
            points = original_card.get('points', 0)
            name = original_card.get('name', f"Card {original_code}")

            print(f"Processing aliases for: {name} (Code: {original_code}, Points: {points})")

            for alias_code in alias_list:
                alias_code_str = str(alias_code)
                image_path = self.alias_images_dir / f"{alias_code_str}.jpg"
                output_path = self.output_dir / f"{alias_code_str}.jpg"

                if not image_path.exists():
                    print(f"  ⚠️  Image not found for alias {alias_code_str}, skipping.")
                    skipped_count += 1
                    continue
                
                try:
                    # 1. Read the local image file
                    with open(image_path, 'rb') as f:
                        image_data = f.read()

                    # 2. Apply overlay with consistent settings
                    modified_image_data = self.downloader.add_points_overlay(
                        image_data, points, font_scale=font_scale, high_quality=high_quality
                    )
                    
                    # 3. Save to the unified output directory
                    with open(output_path, 'wb') as f:
                        f.write(modified_image_data)

                    print(f"  ✅ Generated: {alias_code_str}.jpg")
                    processed_count += 1

                except Exception as e:
                    print(f"  ❌ FAILED to process alias {alias_code_str}: {e}")

        print(f"\n--- Phase 2 Summary ---")
        print(f"✅ Successfully generated: {processed_count} alias cards")
        if skipped_count > 0:
            print(f"⚠️  Skipped: {skipped_count} alias cards (image not found)")


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description='Regenerate all card images with updated points.')
    
    parser.add_argument(
        '-c', '--cards', default='cards.json',
        help='Path to Genesys cards source file (.json or .lflist.conf, default: cards.json)'
    )
    parser.add_argument(
        '-a', '--alias', default='alias.json',
        help='Path to alias JSON file (default: alias.json)'
    )
    parser.add_argument(
        '-i', '--alias-images', default='alias_images',
        help='Directory containing pre-downloaded alias images (default: alias_images)'
    )
    parser.add_argument(
        '-o', '--output', default='generated_cards',
        help='Unified output directory for all generated cards (default: generated_cards)'
    )
    parser.add_argument(
        '-d', '--delay', type=float, default=0.1,
        help='Delay between downloads in seconds (default: 0.1)'
    )
    parser.add_argument(
        '-l', '--limit', type=int, default=None,
        help='Limit the number of primary cards to process for testing (default: all)'
    )
    parser.add_argument(
        '-hq', '--high-quality',
        action='store_true',
        help='Generate high quality images (original size) instead of thumbnails'
    )
    parser.add_argument(
        '-g', '--generate',
        nargs='?',
        const='all',
        default='all',
        choices=['all', 'cards', 'alias'],
        help="What to generate: all, cards, alias (default: all)"
    )
    parser.add_argument(
        '--code',
        action='append',
        default=None,
        help='Generate only a specific card code from cards.json (can be used multiple times, or as a comma-separated list). '
             'When generating aliases, only aliases for these original codes are processed.'
    )

    args = parser.parse_args()

    if args.generate == 'alias' and args.limit is not None:
        print("ℹ️  Note: --limit only applies to primary cards (cards.json). It is ignored when --generate=alias.")

    # Parse --code (supports multiple flags and/or comma-separated lists)
    codes: Optional[List[str]] = None
    if args.code:
        parsed: List[str] = []
        for raw in args.code:
            if raw is None:
                continue
            for part in str(raw).split(','):
                part = part.strip()
                if part:
                    parsed.append(part)
        codes = parsed or None

    # Validate paths
    required_paths = [args.cards]
    if args.generate in ('all', 'alias'):
        required_paths.extend([args.alias, args.alias_images])
    for path in required_paths:
        if not os.path.exists(path):
            print(f"❌ Error: Required file or directory not found: {path}")
            sys.exit(1)

    regenerator = CardRegenerator(
        cards_path=args.cards,
        alias_path=args.alias if args.generate in ('all', 'alias') else None,
        alias_images_dir=args.alias_images if args.generate in ('all', 'alias') else None,
        output_dir=args.output,
        delay=args.delay,
        generation=args.generate,
        codes=codes,
    )
    
    regenerator.run_regeneration(limit=args.limit, high_quality=args.high_quality)


if __name__ == '__main__':
    main()
