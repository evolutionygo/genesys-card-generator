#!/usr/bin/env python3
"""
Yu-Gi-Oh! Card Image Downloader with Points Overlay

This script downloads card images using card codes from the cards.json file and
adds point values as overlay text.

Two different art sources are used, because base cards and alternate-art
(alias) printings are not available from the same place:

- Base cards come from YGOPRODeck (`BASE_IMAGE_URL`), except prerelease codes,
  which try Project Ignis (`PRERELEASE_IMAGE_URL`) first, YGOPRODeck second.
- Alias printings come from the sources in `ALIAS_IMAGE_URLS`, with committed
  art in `alias_images/` taking precedence over any network source.
"""

import json
import os
import sys
import time
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from PIL import Image, ImageDraw, ImageFont
import io


class YugiohCardDownloader:
    """Downloads Yu-Gi-Oh! card images directly from YGOPRODeck and adds Genesys point overlays."""
    
    BASE_IMAGE_URL = "https://images.ygoprodeck.com/images/cards"

    # Prerelease cards carry EDOPro's 9-digit placeholder codes until their
    # official passcode is announced. YGOPRODeck serves leaked photos of the
    # physical card for those codes (skewed, edges cropped), so they try
    # Project Ignis first (the clean render EDOPro itself shows) and keep
    # YGOPRODeck only as a fallback.
    PRERELEASE_IMAGE_URL = "https://pics.projectignis.org:2096/pics"
    PRERELEASE_CODE_MIN = 100000000

    # Alias (alternate-art) sources, tried in this exact order.
    #
    # Project Ignis is EDOPro's compiled-in picture source, so the badges sit
    # on exactly the art players already see, at the 177x254 size this tool
    # targets. It serves every alias EDOPro declares, and sync_alias.py derives
    # alias.json from EDOPro's own databases, so it is the only source needed.
    # The momobako mirror used to be a fallback for MyCard-only codes; those
    # are no longer generated. The lookup stays a generic ordered chain.
    ALIAS_IMAGE_URLS = (
        "https://pics.projectignis.org:2096/pics",
    )

    # Source label reported by fetch_alias_image for a committed local file.
    LOCAL_ALIAS_SOURCE = "local"

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
        """Load cards from JSON or Genesys .lflist.conf file."""
        source_path = Path(json_path)
        if source_path.suffix.lower() == '.conf':
            return self.load_cards_conf(json_path)

        with open(source_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def load_cards_conf(self, conf_path: str) -> List[Dict]:
        """Load cards from a Genesys lflist.conf file."""
        cards: List[Dict] = []
        in_genesys_section = False

        with open(conf_path, 'r', encoding='utf-8') as f:
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
                cards.append({
                    'code': int(code),
                    'copies': int(copies),
                    'name': name.strip(),
                    'points': int(points),
                })

        return cards
    
    def get_font(self, size: int):
        """
        Try to get a good font for text overlay.
        Falls back to default font if system fonts are not available.
        """
        font_paths = [
            # macOS fonts (prefer bold for the points badge)
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            # Windows fonts (prefer bold)
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/Arial.ttf",
            # Linux fonts
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        
        for font_path in font_paths:
            try:
                return ImageFont.truetype(font_path, size)
            except (OSError, IOError):
                continue
        
        # Fallback to default font
        try:
            return ImageFont.load_default()
        except:
            return None
    
    def add_points_overlay(self, image_data: bytes, points: int, font_scale: float = 1.0, high_quality: bool = False, custom_quality: int = None) -> bytes:
        """
        Add points overlay to the image.
        
        Args:
            image_data: Original image data as bytes
            points: Points value to overlay
            font_scale: Scale factor for font size (default: 1.0)
            high_quality: If True, keeps original image size. If False, resizes to thumbnail (default: False)
            custom_quality: Optional JPEG quality override (0-100). If None, uses default logic.
            
        Returns:
            Modified image data as bytes
        """
        try:
            # Open image from bytes
            image = Image.open(io.BytesIO(image_data))
            
            # Define a max size based on smaller alias images to keep file sizes down
            # Only resize if NOT high quality
            if not high_quality:
                max_width, max_height = 177, 254
                if image.width > max_width or image.height > max_height:
                    # Use thumbnail to downscale images that are too large, preserving aspect ratio
                    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            
            # Create a drawing context
            draw = ImageDraw.Draw(image)
            
            # Image dimensions
            img_width, img_height = image.size
            
            # Text to display
            text = str(points)

            # Badge geometry is proportional to the card width so the circle
            # looks consistent across thumbnails and high-quality renders.
            # font_scale is only used later to detect downloaded cards, not to
            # size the badge.
            diameter = max(int(img_width * 0.341 * 1.25), 71)

            # Fit the number inside the circle: pick the largest font whose
            # number fits within ~70% of the diameter (both width and height).
            inner = diameter * 0.70
            font_size = max(int(diameter * 0.6), 12)
            font = self.get_font(font_size)
            for _ in range(40):
                if not font:
                    break
                bbox = draw.textbbox((0, 0), text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                if (tw <= inner and th <= inner) or font_size <= 10:
                    break
                font_size = max(int(font_size * 0.9), 10)
                font = self.get_font(font_size)

            # Final text dimensions
            if font:
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                # Estimate text size without font
                font_size = 60
                text_width = int(len(text) * (font_size * 0.6))
                text_height = int(font_size)

            # Position: flush against the bottom-left corner of the image.
            rect_x1 = 0
            rect_y2 = img_height
            rect_y1 = rect_y2 - diameter
            rect_x2 = rect_x1 + diameter

            # Keep the badge inside the image (shift, don't squash, to stay circular)
            if rect_x1 < 0:
                rect_x2 -= rect_x1
                rect_x1 = 0
            if rect_y1 < 0:
                rect_y2 -= rect_y1
                rect_y1 = 0
            rect_x2 = min(img_width, rect_x2)
            rect_y2 = min(img_height, rect_y2)

            # Single uniform style (no per-points colors):
            # semi-transparent black circle with light-blue ring and white number.
            bg_color = (0, 0, 0, 235)
            ring_color = (93, 196, 234, 255)  # light blue (#5dc4ea)
            text_color = (255, 255, 255)
            ring_width = max(int(diameter * 0.07), 2)

            # Create overlay for semi-transparent background
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)

            # Draw the circular badge with a light-blue border ring
            overlay_draw.ellipse(
                [rect_x1, rect_y1, rect_x2, rect_y2],
                fill=bg_color,
                outline=ring_color,
                width=ring_width,
            )
            
            # Composite the overlay onto the original image
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            image = Image.alpha_composite(image, overlay)
            
            # Draw text on top, positioned to be centered in the rectangle
            draw = ImageDraw.Draw(image)
            
            # Calculate center of the rectangle
            center_x = (rect_x1 + rect_x2) / 2
            center_y = (rect_y1 + rect_y2) / 2
            
            if font:
                # Use anchor='mm' to center text exactly (middle-horizontal, middle-vertical)
                try:
                    draw.text((center_x, center_y), text, fill=text_color, font=font, anchor='mm')
                except ValueError:
                    # Fallback for older Pillow versions that might not support anchor
                    text_x = rect_x1 + (diameter - text_width) // 2
                    text_y = rect_y1 + (diameter - text_height) // 2
                    draw.text((text_x, text_y), text, fill=text_color, font=font)
            else:
                # Fallback for default font
                text_x = rect_x1 + (diameter - text_width) // 2
                text_y = rect_y1 + (diameter - text_height) // 2
                draw.text((text_x, text_y), text, fill=text_color)
            
            # Convert back to RGB if needed
            if image.mode == 'RGBA':
                # Create white background
                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                rgb_image.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
                image = rgb_image
            
            # Save to bytes with optimized compression
            output_buffer = io.BytesIO()

            # Determine quality: use custom if provided, otherwise 90 for HQ, 50 for Standard
            final_quality = custom_quality if custom_quality is not None else (90 if high_quality else 50)
            
            image.save(output_buffer, format='JPEG', quality=final_quality, optimize=True)
                
            return output_buffer.getvalue()
            
        except Exception as e:
            print(f"❌ Error adding points overlay: {e}")
            # Return original image data if overlay fails
            return image_data
    
    def fetch_alias_image(
        self, alias_code: str, local_dir: Optional[Path] = None
    ) -> Optional[Tuple[bytes, str]]:
        """
        Fetch the raw art for an alias (alternate-art) card code.

        Committed art wins: `alias_images/` is the curated tier, so a local file
        short-circuits the network entirely. Otherwise every URL in
        `ALIAS_IMAGE_URLS` is tried in order and the first non-empty body wins.

        Individual source failures are caught and logged as warnings so that one
        dead mirror does not abort the whole run. No exception is raised on a
        total miss; the caller decides what a miss means.

        Args:
            alias_code: The alias card code (as a string).
            local_dir: Optional directory holding committed alias art.

        Returns:
            A (image_bytes, source) tuple, where source is LOCAL_ALIAS_SOURCE
            for a committed file or the base URL of the mirror that served it.
            None when no source could provide the image.
        """
        if local_dir is not None:
            local_path = Path(local_dir) / f"{alias_code}.jpg"
            if local_path.exists():
                try:
                    with open(local_path, 'rb') as f:
                        return f.read(), self.LOCAL_ALIAS_SOURCE
                except (OSError, IOError) as e:
                    print(f"  ⚠️  Could not read local alias image {local_path}: {e}")

        for base_url in self.ALIAS_IMAGE_URLS:
            url = f"{base_url}/{alias_code}.jpg"
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                if not response.content:
                    print(f"  ⚠️  Empty response for alias {alias_code} from {base_url}")
                    continue
                return response.content, base_url
            except requests.exceptions.RequestException as e:
                print(f"  ⚠️  Alias {alias_code} unavailable from {base_url}: {e}")
                continue

        return None

    def base_image_urls(self, card_code: Union[str, int]) -> List[str]:
        """
        List the art URLs for a base (non-alias) card code, in try order.

        Prerelease codes try Project Ignis first and keep YGOPRODeck as a
        fallback, so an unreachable mirror degrades to the cropped photo
        instead of no image at all.

        Args:
            card_code: The card code (string or int).

        Returns:
            The ordered list of candidate URLs.
        """
        code = str(card_code)
        urls = [f"{self.BASE_IMAGE_URL}/{code}.jpg"]
        if code.isdigit() and int(code) >= self.PRERELEASE_CODE_MIN:
            urls.insert(0, f"{self.PRERELEASE_IMAGE_URL}/{code}.jpg")
        return urls

    def fetch_base_image(self, card_code: Union[str, int]) -> Optional[bytes]:
        """
        Fetch the raw art for a base card, walking `base_image_urls` in order.

        Individual source failures (network errors, empty or non-image bodies)
        are logged as warnings and the next source is tried; no exception is
        raised on a total miss.

        Args:
            card_code: The card code (string or int).

        Returns:
            The image bytes, or None when no source could provide them.
        """
        for url in self.base_image_urls(card_code):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                if not response.content:
                    print(f"  ⚠️  Empty response for {card_code} from {url}")
                    continue
                # A mirror can answer 200 with an error page or placeholder;
                # treat anything that is not a decodable image as a miss so
                # the next source still gets a chance.
                Image.open(io.BytesIO(response.content)).verify()
                return response.content
            except requests.exceptions.RequestException as e:
                print(f"  ⚠️  Card {card_code} unavailable from {url}: {e}")
            except (OSError, SyntaxError) as e:
                print(f"  ⚠️  Card {card_code} from {url} is not a valid image: {e}")
        return None

    def download_image(self, url: str, filename: str, points: int) -> bool:
        """
        Download an image from URL, add points overlay, and save to file.
        
        Args:
            url: Image URL
            filename: Local filename to save
            points: Points value to overlay
            
        Returns:
            True if successful, False otherwise
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Add points overlay to image
            modified_image_data = self.add_points_overlay(response.content, points)
            
            # Save to file
            filepath = self.output_dir / filename
            with open(filepath, 'wb') as f:
                f.write(modified_image_data)
            
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error downloading image from {url}: {e}")
            return False
        except IOError as e:
            print(f"❌ Error saving image to {filename}: {e}")
            return False
    
    def download_card_image(self, card_data: Dict) -> bool:
        """
        Download image for a card and add points overlay.
        
        Args:
            card_data: Card data from JSON file
            
        Returns:
            True if image was downloaded successfully
        """
        card_code = card_data['code']
        card_name = card_data.get('name', f'Card_{card_code}')
        points = card_data.get('points', 0)
        
        print(f"📥 Downloading image for: {card_name} (ID: {card_code}, Points: {points})")
        
        filename = f"{card_code}.jpg"

        image_data = self.fetch_base_image(card_code)
        if image_data is None:
            print(f"  ❌ Failed to download image for card {card_code}")
            return False

        try:
            with open(self.output_dir / filename, 'wb') as f:
                f.write(self.add_points_overlay(image_data, points))
        except (OSError, IOError) as e:
            print(f"❌ Error saving image to {filename}: {e}")
            return False

        print(f"  ✅ Downloaded with {points} points overlay: {filename}")
        return True
    
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
        '-f', '--file',
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
    
    if not os.path.exists(args.file):
        print(f"❌ Cards JSON file not found: {args.file}")
        sys.exit(1)
    
    downloader = YugiohCardDownloader(
        output_dir=args.output,
        delay=args.delay
    )
    
    downloader.download_all_cards(args.file)


if __name__ == '__main__':
    main()