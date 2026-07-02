#!/usr/bin/env python3
"""
Apply Points Overlay to Alias Cards

This script processes alias card images and applies the same point overlay
as their corresponding original cards.
"""

import json
import os
from pathlib import Path
from typing import Dict, List
from card_downloader import YugiohCardDownloader


class AliasOverlayProcessor:
    """Processes alias cards and applies point overlays based on original cards."""
    
    def __init__(self, cards_json_path: str, alias_json_path: str, images_dir: str, output_dir: str = None):
        """
        Initialize the processor.
        
        Args:
            cards_json_path: Path to cards.json with card data and points
            alias_json_path: Path to alias.json with alias mappings
            images_dir: Directory containing alias card images
            output_dir: Directory to save processed images (default: images_dir + '_processed')
        """
        self.cards_json_path = Path(cards_json_path)
        self.alias_json_path = Path(alias_json_path)
        self.images_dir = Path(images_dir)
        
        # Set output directory
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = Path(str(self.images_dir) + '_processed')
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(exist_ok=True)
        
        # Create downloader instance to use its overlay functionality
        self.downloader = YugiohCardDownloader()
        
        # Load data
        self.cards_data = self._load_cards_data()
        self.alias_data = self._load_alias_data()
        
    def _load_cards_data(self) -> Dict:
        """Load a Genesys source file and create a lookup dictionary by code."""
        if self.cards_json_path.suffix.lower() == '.conf':
            cards_dict = {}
            in_genesys_section = False
            with open(self.cards_json_path, 'r', encoding='utf-8') as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    if line.startswith('#'):
                        continue
                    if line.startswith('!'):
                        in_genesys_section = line == '!Genesys'
                        continue
                    if not in_genesys_section or '--' not in line:
                        continue
                    left, name = line.split('--', 1)
                    parts = left.split()
                    if len(parts) != 3:
                        continue
                    code, copies, points = parts
                    cards_dict[str(code)] = {
                        'code': int(code),
                        'copies': int(copies),
                        'name': name.strip(),
                        'points': int(points),
                    }
            return cards_dict

        with open(self.cards_json_path, 'r', encoding='utf-8') as f:
            cards_list = json.load(f)
        
        # Create a dictionary with code as key for quick lookup
        cards_dict = {}
        for card in cards_list:
            code = str(card.get('code'))
            cards_dict[code] = card
        
        return cards_dict
    
    def _load_alias_data(self) -> Dict:
        """Load alias.json."""
        with open(self.alias_json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def process_all_aliases(self):
        """Process all alias cards and apply overlays."""
        total_processed = 0
        total_skipped = 0
        total_errors = 0
        
        print(f"🚀 Starting alias overlay processing...")
        print(f"📁 Input directory: {self.images_dir.absolute()}")
        print(f"💾 Output directory: {self.output_dir.absolute()}")
        print(f"📊 Found {len(self.alias_data)} original cards with aliases\n")
        
        for original_code, alias_list in self.alias_data.items():
            # Get points from original card
            if original_code not in self.cards_data:
                print(f"⚠️  Original card {original_code} not found in cards.json, skipping aliases")
                total_skipped += len(alias_list)
                continue
            
            original_card = self.cards_data[original_code]
            points = original_card.get('points', 0)
            original_name = original_card.get('name', f'Card {original_code}')
            
            print(f"📋 Processing aliases for: {original_name} (Code: {original_code}, Points: {points})")
            
            # Process each alias
            for alias_code in alias_list:
                alias_code_str = str(alias_code)
                image_path = self.images_dir / f"{alias_code_str}.jpg"
                
                if not image_path.exists():
                    print(f"  ⚠️  Image not found: {alias_code_str}.jpg")
                    total_skipped += 1
                    continue
                
                # Apply overlay
                success = self._apply_overlay_to_image(image_path, points, alias_code_str)
                
                if success:
                    print(f"  ✅ Applied {points} points overlay to: {alias_code_str}.jpg")
                    total_processed += 1
                else:
                    print(f"  ❌ Failed to process: {alias_code_str}.jpg")
                    total_errors += 1
            
            print()  # Empty line between original cards
        
        # Final summary
        print(f"🎉 Processing completed!")
        print(f"✅ Successfully processed: {total_processed} images")
        print(f"⚠️  Skipped: {total_skipped} images")
        print(f"❌ Errors: {total_errors} images")
    
    def _apply_overlay_to_image(self, image_path: Path, points: int, alias_code: str) -> bool:
        """
        Apply points overlay to a single image.
        
        Args:
            image_path: Path to the image file
            points: Points value to overlay
            alias_code: Alias card code for logging
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Read the image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Apply overlay using the downloader's method with 50% smaller font
            modified_image_data = self.downloader.add_points_overlay(image_data, points, font_scale=0.5)
            
            # Save to output directory
            output_path = self.output_dir / f"{alias_code}.jpg"
            with open(output_path, 'wb') as f:
                f.write(modified_image_data)
            
            return True
            
        except Exception as e:
            print(f"  ❌ Error processing {alias_code}: {e}")
            return False


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Apply points overlay to alias card images'
    )
    parser.add_argument(
        '-c', '--cards',
        default='cards.json',
        help='Path to cards JSON file (default: cards.json)'
    )
    parser.add_argument(
        '-a', '--alias',
        default='alias.json',
        help='Path to alias JSON file (default: alias.json)'
    )
    parser.add_argument(
        '-i', '--images',
        default='alias_images',
        help='Directory containing alias images (default: alias_images)'
    )
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='Output directory for processed images (default: images_dir + "_processed")'
    )
    
    args = parser.parse_args()
    
    # Check if files exist
    if not os.path.exists(args.cards):
        print(f"❌ Cards JSON file not found: {args.cards}")
        return 1
    
    if not os.path.exists(args.alias):
        print(f"❌ Alias JSON file not found: {args.alias}")
        return 1
    
    if not os.path.exists(args.images):
        print(f"❌ Images directory not found: {args.images}")
        return 1
    
    # Process aliases
    processor = AliasOverlayProcessor(
        cards_json_path=args.cards,
        alias_json_path=args.alias,
        images_dir=args.images,
        output_dir=args.output
    )
    
    processor.process_all_aliases()
    
    return 0


if __name__ == '__main__':
    exit(main())

