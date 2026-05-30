<p align="center">
  <img src="https://raw.githubusercontent.com/sebastian-raubach/geosnap/main/public/geosnap.svg?sanitize=true" width="300" alt="Logo">
</p>

# GeoSnap - GPX Image geotagging

A command-line tool that geotags JPEG/TIFF photos using a GPX track file, then generates a self-contained interactive map for visually verifying the results.

## How it works

1. Reads EXIF timestamps from every image in a folder
2. Interpolates a GPS position from the nearest trackpoints in a GPX file
3. Writes the latitude, longitude, and elevation back into the image's EXIF metadata
4. Saves the geotagged copies to a subfolder (originals are never modified)
5. Generates a `map.html` file and opens it in your browser, with each photo pinned at its mapped location

Images whose timestamps fall outside the GPX track (e.g. photos taken before or after the trip) are automatically skipped based on a configurable time gap threshold.

## Features

- **Linear interpolation** between GPX trackpoints for accurate positioning
- **Time offset parameter** to correct for camera clock timezone mismatches
- **Configurable gap threshold** to control how strictly images are matched to the track
- **Interactive map** with Street, Satellite (Esri), and Topo tile layers
- **Click any marker** to see a thumbnail preview of the photo; click the thumbnail to enlarge
- **Sidebar thumbnail strip** for browsing all geotagged photos at a glance
- **Self-contained HTML output** — `map.html` embeds all thumbnails as base64, no web server needed
- Supports JPEG and TIFF; correctly handles EXIF orientation rotation in thumbnails

## Requirements

- Python 3.10+
- Windows, macOS, or Linux

## Installation

```bash
pip install -r requirements.txt
```

Or install dependencies directly:

```bash
pip install gpxpy piexif Pillow
```

## Usage

```
python geotag_images.py <image_folder> <gpx_file> [options]
```

### Arguments

| Argument | Description |
|---|---|
| `image_folder` | Folder containing the photos to geotag |
| `gpx_file` | Path to the `.gpx` track file |

### Options

| Option | Default | Description |
|---|---|---|
| `--offset HOURS` | `0` | Add a time offset (in hours) to all image timestamps before matching. Accepts decimals and negative values. Use this when your camera clock was set to a different timezone than the GPS. |
| `--max-gap SECS` | `300` | Maximum allowed time gap in seconds between a photo's timestamp and the nearest GPX trackpoint. Photos outside this window are skipped. |
| `--output SUBDIR` | `geotagged` | Name of the output subfolder created inside the image folder. |
| `--no-map` | — | Skip generating the HTML map (useful for batch/automated runs). |
| `--verbose` | — | Print a line for every image, including those that are skipped and why. |

### Examples

Basic usage:
```bash
python geotag_images.py "C:\Photos\Trip2024" "C:\GPS\track.gpx"
```

Camera clock was 2 hours behind GPS (e.g. forgot to set timezone):
```bash
python geotag_images.py ./photos ./track.gpx --offset 2
```

Stricter matching (only tag photos within 1 minute of a trackpoint):
```bash
python geotag_images.py ./photos ./track.gpx --max-gap 60
```

Verbose output, custom subfolder name, no map:
```bash
python geotag_images.py ./photos ./track.gpx --output tagged --verbose --no-map
```

### Windows convenience wrapper

A `geotag_images.bat` file is included. You can run it the same way from the command prompt, or drag an image folder onto it directly:

```
geotag_images.bat "C:\Photos\Trip2024" "C:\GPS\track.gpx" --offset -1
```

## Output

After running, the image folder will contain a new subfolder (default: `geotagged/`) with:

```
geotagged/
├── photo_001.jpg      ← copy of original with GPS EXIF written
├── photo_002.jpg
├── ...
└── map.html           ← interactive map (open in any browser)
```

The GPS tags written are compatible with Apple Photos, Google Photos, Adobe Lightroom, Windows Explorer, and any other software that reads standard EXIF GPS metadata.

### The map

`map.html` opens automatically after processing. It includes:

- **GPX track line** drawn over the map so you can see the full route
- **Photo markers** at each interpolated position — click to see a popup with the image, filename, timestamp, and coordinates
- **Lightbox** — click the popup image for a full-screen view (press Esc or click outside to close)
- **Tile layer switcher** (bottom-left) to toggle between Street, Satellite, and Topo basemaps
- **Thumbnail sidebar** for browsing all geotagged photos; clicking a thumbnail pans the map to that photo

The file is entirely self-contained — thumbnails are embedded as base64 — so you can archive or share it without needing the original images alongside it.

## Tips

**Finding the right `--offset`**
If your photos consistently appear a few hours ahead or behind their actual location on the track, your camera clock was in a different timezone from the GPS. Start with your camera's UTC offset relative to the GPS device's timezone. For example, if the camera was on UTC+2 but the GPS logged UTC, use `--offset -2`.

**Sparse GPX tracks**
If your GPS device records a point every 30–60 seconds, the default 5-minute gap threshold works well. For devices that only log occasionally, increase `--max-gap` to suit (e.g. `--max-gap 600` for 10 minutes).

**Photos not being matched**
Run with `--verbose` to see the exact UTC timestamp each image is being matched against, which makes it easy to spot offset issues.

## Dependencies

| Package | Purpose |
|---|---|
| [gpxpy](https://github.com/tkrajina/gpxpy) | Parsing GPX files |
| [piexif](https://github.com/hMatoba/Piexif) | Reading and writing EXIF metadata |
| [Pillow](https://python-pillow.org/) | Image processing and thumbnail generation |

Map tiles in the generated HTML are loaded from [OpenStreetMap](https://www.openstreetmap.org/copyright), [Esri/ArcGIS](https://www.esri.com/), and [OpenTopoMap](https://opentopomap.org/) at runtime.

## Disclaimer

This tool was created using Claude.ai.

## License

Apache License, Version 2
