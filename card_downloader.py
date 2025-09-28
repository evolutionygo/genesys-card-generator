#!/usr/bin/env python3
"""
Yu-Gi-Oh! Card Image Downloader

This script downloads card images directly from YGOPRODeck using card codes
from the cards.json file.
"""

import json
import os
import sys
import time
import requests
from pathlib import Path
from typing import List, Dict


class YugiohCardDownloader:
    """Downloads Yu-Gi-Oh! card images directly from YGOPRODeck."""
    
    BASE_IMAGE_URL = "https://images.ygoprodeck.com/images/cards"
    DEFAULT_OUTPUT_DIR = "downloaded_cards"
    
    def __init__(self, output_dir: str = None, delay: float = 0.1):
        """
        Initialize the downloader.
        
        Args:
            output_dir: Directory to save downloaded images
            delay: Delay between downloads to be respectful
        """
        self.output_dir = Path(output_dir or self.DEFAULT_OUTPUT_DIR)
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'YuGiOh-Card-Downloader/2.0'
        })
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(exist_ok=True)
        
    def load_cards_json(self, json_path: str) -> List[Dict]:
        """Load cards from JSON file."""
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def download_image(self, url: str, filename: str) -> bool:
        """
        Download an image from URL and save to file.
        
        Args:
            url: Image URL
            filename: Local filename to save
            
        Returns:
            True if successful, False otherwise
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            filepath = self.output_dir / filename
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error downloading image from {url}: {e}")
            return False
        except IOError as e:
            print(f"❌ Error saving image to {filename}: {e}")
            return False
    
    def download_card_image(self, card_data: Dict) -> bool:
        """
        Download image for a card.
        
        Args:
            card_data: Card data from JSON file
            
        Returns:
            True if image was downloaded successfully
        """
        card_code = card_data['code']
        card_name = card_data.get('name', f'Card_{card_code}')
        
        print(f"📥 Downloading image for: {card_name} (ID: {card_code})")
        
        # Construct direct image URL
        image_url = f"{self.BASE_IMAGE_URL}/{card_code}.jpg"
        filename = f"{card_code}.jpg"
        
        if self.download_image(image_url, filename):
            print(f"  ✅ Downloaded: {filename}")
            return True
        else:
            print(f"  ❌ Failed to download image for card {card_code}")
            return False
    
    def download_all_cards(self, json_path: str):
        """
        Download images for all cards in the JSON file.
        
        Args:
            json_path: Path to cards.json file
        """
        print(f"🚀 Starting card image download...")
        print(f"📁 Output directory: {self.output_dir.absolute()}")
        
        try:
            cards = self.load_cards_json(json_path)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"❌ Error loading cards JSON: {e}")
            return
        
        total_cards = len(cards)
        successful_downloads = 0
        failed_downloads = 0
        
        print(f"📊 Found {total_cards} cards to process")
        
        for i, card_data in enumerate(cards, 1):
            card_code = card_data.get('code')
            if not card_code:
                print(f"❌ Card {i} missing code, skipping")
                failed_downloads += 1
                continue
            
            print(f"\n[{i}/{total_cards}] Processing card {card_code}")
            
            # Download image
            if self.download_card_image(card_data):
                successful_downloads += 1
            else:
                failed_downloads += 1
            
            # Be respectful with downloads
            if i < total_cards:  # Don't delay after the last card
                time.sleep(self.delay)
        
        # Final summary
        print(f"\n🎉 Download completed!")
        print(f"✅ Successfully downloaded: {successful_downloads} cards")
        print(f"❌ Failed downloads: {failed_downloads} cards")
        print(f"📁 Images saved to: {self.output_dir.absolute()}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Download Yu-Gi-Oh! card images')
    parser.add_argument(
        'cards_json',
        nargs='?',
        default='cards.json',
        help='Path to cards JSON file (default: cards.json)'
    )
    parser.add_argument(
        '-o', '--output',
        default='downloaded_cards',
        help='Output directory for images (default: downloaded_cards)'
    )
    parser.add_argument(
        '-d', '--delay',
        type=float,
        default=0.1,
        help='Delay between downloads in seconds (default: 0.1)'
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.cards_json):
        print(f"❌ Cards JSON file not found: {args.cards_json}")
        sys.exit(1)
    
    downloader = YugiohCardDownloader(
        output_dir=args.output,
        delay=args.delay
    )
    
    downloader.download_all_cards(args.cards_json)


if __name__ == '__main__':
    main()