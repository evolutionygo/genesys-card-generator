# Yu-Gi-Oh! Card Image Downloader with Points Overlay

A fast and efficient Python script to download Yu-Gi-Oh! card images directly from YGOPRODeck using card codes from a JSON file and automatically overlays point values on each card.

## Features

- **Direct image downloads** - No API calls needed, uses direct image URLs
- **Points overlay** - Automatically adds point values from JSON as visible text on each card
- **Color-coded points** - Different background colors based on point values:
  - 🔴 Red: 50+ points (high value)
  - 🟠 Orange: 20-49 points (medium-high value)
  - 🟡 Yellow: 10-19 points (medium value)
  - 🟢 Green: 1-9 points (low value)
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

1. Make sure you have Python 3.6+ installed
2. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```
3. Install dependencies:
```bash
pip install -r requirements.txt
```

**Note**: The script now requires Pillow (PIL) for image processing to add point overlays.

## Usage

### Basic Usage

Download all cards from the default `cards.json` file:

```bash
source venv/bin/activate  # Activate virtual environment first
python3 card_downloader.py
```

### Advanced Usage

```bash
# Specify a different JSON file
python3 card_downloader.py /path/to/your/cards.json

# Specify output directory
python3 card_downloader.py -o /path/to/output/directory

# Adjust delay between downloads (be respectful!)
python3 card_downloader.py -d 0.2
```

### Command Line Options

- `cards_json`: Path to the cards JSON file (default: `cards.json`)
- `-o, --output`: Output directory for downloaded images (default: `downloaded_cards`)
- `-d, --delay`: Delay between downloads in seconds (default: 0.1)

## JSON File Format

The JSON file should contain an array of card objects with at least a `code` field:

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
    "points": 100
  }
]
```

Required fields:
- `code`: The Yu-Gi-Oh! card ID/code (integer)

Optional fields:
- `name`: Card name (will be used for filename if available)
- `points`: Any additional data (ignored by downloader)

## Output

Images are saved with simple naming and include point overlays:
```
{card_code}.jpg
```

For example:
- `21044178.jpg` (Abyss Dweller with points overlay)
- `98287529.jpg` (Amorphactor Pain with points overlay)

### Point Overlay System

Each card image will have its point value displayed in the **bottom-left corner** with:
- **Large, readable text** - Automatically sized based on image dimensions (minimum 40px)
- **Properly sized colored background** - Rectangle automatically fits the number perfectly
- **Color-coded backgrounds** for quick identification:
  - 🔴 **Red background** (white text): 50+ points
  - 🟠 **Orange background** (black text): 20-49 points  
  - 🟡 **Yellow background** (black text): 10-19 points
  - 🟢 **Green background** (black text): 1-9 points
- **Semi-transparent background** - Points are visible without completely obscuring the card art
- **Centered text** - Numbers are perfectly centered within their colored rectangles

All images are high-quality full-resolution JPEG files with the point values clearly overlaid.

## Image Sources

Images are downloaded directly from YGOPRODeck using the URL pattern:
```
https://images.ygoprodeck.com/images/cards/{card_code}.jpg
```

This approach is:
- **Faster** - No API calls required
- **More reliable** - Direct image access
- **Simpler** - Consistent naming scheme

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

If point overlay processing fails for any image, the script will save the original image without the overlay and continue processing.

## Example Output

```
🚀 Starting card image download...
📁 Output directory: /Users/diego/personal/ygopro/genesys-card-generator/downloaded_cards
📊 Found 2681 cards to process

[1/2681] Processing card 21044178
📥 Downloading image for: 深渊的潜伏者 (ID: 21044178, Points: 100)
  ✅ Downloaded with 100 points overlay: 21044178.jpg

[2/2681] Processing card 98287529
📥 Downloading image for: 虚龙魔王 无形矢·心灵 (ID: 98287529, Points: 67)
  ✅ Downloaded with 67 points overlay: 98287529.jpg

...

🎉 Download completed!
✅ Successfully downloaded: 2650 cards
❌ Failed downloads: 31 cards
📁 Images saved to: /Users/diego/personal/ygopro/genesys-card-generator/downloaded_cards
```

## Notes

- Much faster than API-based approaches (no API calls needed)
- Simple, consistent file naming using card codes
- **Point values are clearly visible** on each card image for easy identification
- **Automatic color coding** helps quickly identify high-value vs low-value cards
- Images are high-quality full-resolution JPEGs with professional overlays
- The script will create the output directory if it doesn't exist
- Comprehensive error handling and progress reporting
- Respectful rate limiting to avoid overwhelming servers
- Works with any font available on the system, falls back gracefully if none found

## License

This project is provided as-is for educational and personal use. Please respect the terms of service of the YGOPRODeck API and Yu-Gi-Oh! card image copyrights.