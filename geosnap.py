#!/usr/bin/env python3
"""
geosnap.py — GeoSnap - GPX Image geotagging

Usage:
    python geosnap.py <image_folder> <gpx_file> [options]

Options:
    --offset HOURS    Time offset in hours to apply to image timestamps (default: 0).
                      Use positive values to shift forward, negative to shift back.
                      Useful when camera clock is in a different timezone than GPS.
    --max-gap SECS    Maximum allowed gap in seconds between an image timestamp and
                      the nearest GPX trackpoint. Images outside this window are
                      skipped. (default: 300, i.e. 5 minutes)
    --output DIR      Name of the output subfolder inside the image folder.
                      (default: "geotagged")
    --no-map          Skip generating the HTML map.
    --verbose         Print per-image details even for skipped files.
    --help / -h       Show this help message and exit.

Examples:
    python geosnap.py C:\\Photos\\Trip2024 C:\\GPS\\track.gpx
    python geosnap.py ./photos ./track.gpx --offset -2 --max-gap 120
    python geosnap.py ./photos ./track.gpx --offset 1.5 --verbose
"""

import argparse
import base64
import io
import json
import sys
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import gpxpy
    import gpxpy.gpx
except ImportError:
    sys.exit("ERROR: 'gpxpy' is not installed. Run:  pip install gpxpy")

try:
    import piexif
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("ERROR: 'piexif' / 'Pillow' not installed. Run:  pip install piexif Pillow")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff"}
THUMB_SIZE = (400, 300)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Geotag JPEG/TIFF images using a GPX track file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("image_folder", help="Folder containing the images to geotag.")
    p.add_argument("gpx_file",     help="Path to the GPX file.")
    p.add_argument(
        "--offset", type=float, default=0.0, metavar="HOURS",
        help="Time offset in hours added to image timestamps before matching (default: 0).",
    )
    p.add_argument(
        "--max-gap", type=float, default=300.0, metavar="SECS",
        help="Max time gap in seconds to nearest GPX point (default: 300).",
    )
    p.add_argument(
        "--output", default="geotagged", metavar="SUBDIR",
        help="Output subfolder name inside image folder (default: 'geotagged').",
    )
    p.add_argument("--no-map",  action="store_true", help="Skip HTML map generation.")
    p.add_argument("--verbose", action="store_true", help="Show details for skipped files.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# GPX loading
# ---------------------------------------------------------------------------

def load_trackpoints(gpx_path):
    """Return a sorted list of (utc_datetime, lat, lon, elevation) tuples."""
    with open(gpx_path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                if pt.time is None:
                    continue
                t = pt.time
                t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
                points.append((t, pt.latitude, pt.longitude, pt.elevation))
    for wpt in gpx.waypoints:
        if wpt.time is not None:
            t = wpt.time
            t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
            points.append((t, wpt.latitude, wpt.longitude, wpt.elevation))
    points.sort(key=lambda x: x[0])
    return points


def load_track_polyline(gpx_path):
    """Return [[lat, lon], ...] for drawing the GPX track line."""
    with open(gpx_path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
    return [[pt.latitude, pt.longitude]
            for track in gpx.tracks
            for segment in track.segments
            for pt in segment.points]


# ---------------------------------------------------------------------------
# EXIF helpers
# ---------------------------------------------------------------------------

EXIF_DATE_FORMATS = ["%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"]


def exif_datetime(image_path):
    try:
        exif_data = piexif.load(str(image_path))
    except Exception:
        return None
    raw = (
        exif_data.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        or exif_data.get("Exif", {}).get(piexif.ExifIFD.DateTimeDigitized)
        or exif_data.get("0th",  {}).get(piexif.ImageIFD.DateTime)
    )
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="ignore").strip("\x00")
    for fmt in EXIF_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _deg_to_dms_rational(deg):
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = round((deg - d - m / 60) * 3600 * 1000)
    return [(d, 1), (m, 1), (s, 1000)]


def write_gps_exif(image_path, dest_path, lat, lon, ele):
    try:
        exif_dict = piexif.load(str(image_path))
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

    gps_ifd = {
        piexif.GPSIFD.GPSVersionID:    (2, 3, 0, 0),
        piexif.GPSIFD.GPSLatitudeRef:  b"N" if lat >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude:     _deg_to_dms_rational(lat),
        piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude:    _deg_to_dms_rational(lon),
    }
    if ele is not None:
        gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = 0 if ele >= 0 else 1
        gps_ifd[piexif.GPSIFD.GPSAltitude]    = (int(abs(ele) * 100), 100)

    exif_dict["GPS"] = gps_ifd
    img = Image.open(image_path)
    img.save(str(dest_path), exif=piexif.dump(exif_dict))
    img.close()


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------

def interpolate_position(points, image_time_utc, max_gap_secs):
    if not points:
        return None

    lo, hi = 0, len(points) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if points[mid][0] < image_time_utc:
            lo = mid + 1
        else:
            hi = mid

    before_idx = lo - 1 if lo > 0 else None
    after_idx  = lo if lo < len(points) else None

    def gap(idx):
        return abs((points[idx][0] - image_time_utc).total_seconds())

    if before_idx is None and after_idx is None:
        return None
    if before_idx is None:
        return (points[after_idx][1:4]) if gap(after_idx) <= max_gap_secs else None
    if after_idx is None:
        return (points[before_idx][1:4]) if gap(before_idx) <= max_gap_secs else None
    if gap(before_idx) > max_gap_secs and gap(after_idx) > max_gap_secs:
        return None

    t_b, lat_b, lon_b, ele_b = points[before_idx]
    t_a, lat_a, lon_a, ele_a = points[after_idx]
    span = (t_a - t_b).total_seconds()
    if span <= 0:
        return lat_b, lon_b, ele_b
    frac = max(0.0, min(1.0, (image_time_utc - t_b).total_seconds() / span))
    lat  = lat_b + frac * (lat_a - lat_b)
    lon  = lon_b + frac * (lon_a - lon_b)
    ele  = (ele_b + frac * (ele_a - ele_b)) if (ele_b is not None and ele_a is not None) else None
    return lat, lon, ele


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------

def make_thumbnail_b64(image_path, size=THUMB_SIZE):
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)   # correct rotation
    img.thumbnail(size, Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=78)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# HTML map
# ---------------------------------------------------------------------------

MAP_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GeoSnap | GPX Image geotagging</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:#111827;color:#e2e8f0;height:100vh;display:flex;flex-direction:column}

/* ── top bar ── */
#topbar{background:#1e2a3a;padding:7px 18px;display:flex;align-items:center;
        gap:14px;box-shadow:0 2px 12px #0006;z-index:1000;flex-shrink:0}
#topbar .pill{background:#0f172a;border:1px solid #1e3a5f;border-radius:999px;
              padding:3px 10px;font-size:.72rem;color:#94a3b8}
#topbar .pill b{color:#e2e8f0}

/* ── layout ── */
#shell{display:flex;flex:1;overflow:hidden}
#map{flex:1}

/* ── sidebar ── */
#sidebar{width:220px;background:#1e2a3a;border-left:1px solid #1e3a5f;
         display:flex;flex-direction:column;overflow:hidden;flex-shrink:0}
#sidebar-head{padding:10px 12px;font-size:.72rem;font-weight:600;color:#7dd3fc;
              text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid #1e3a5f}
#thumb-list{flex:1;overflow-y:auto;padding:6px}
#thumb-list::-webkit-scrollbar{width:4px}
#thumb-list::-webkit-scrollbar-thumb{background:#2a4060;border-radius:2px}
.thumb-item{border-radius:6px;overflow:hidden;margin-bottom:6px;cursor:pointer;
            border:2px solid transparent;transition:border-color .15s,transform .15s}
.thumb-item:hover{border-color:#7dd3fc;transform:scale(1.02)}
.thumb-item.active{border-color:#38bdf8}
.thumb-item img{display:block;width:100%;height:90px;object-fit:cover}
.thumb-label{font-size:.65rem;color:#64748b;padding:3px 5px;
             white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
             background:#111827}

/* ── Leaflet popup ── */
.leaflet-popup-content-wrapper{
  background:#1e2a3a;border:1px solid #1e3a5f;border-radius:10px;
  box-shadow:0 8px 32px #000b;padding:0;overflow:hidden}
.leaflet-popup-content{margin:0;width:100%!important}
.leaflet-popup-tip{background:#1e2a3a}
.leaflet-popup-close-button{color:#7dd3fc!important;font-size:18px!important;
  top:6px!important;right:8px!important;z-index:10}

.popup-img{display:block;width:100%;max-height:210px;object-fit:cover;
           border-bottom:1px solid #1e3a5f;cursor:zoom-in}
.popup-img:hover{opacity:.9}
.popup-body{padding:10px 12px 12px}
.popup-name{font-size:.82rem;font-weight:600;color:#7dd3fc;
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.popup-meta{font-size:.72rem;color:#64748b;margin-top:5px;line-height:1.7}
.popup-meta span{display:block}
.popup-meta .coord{font-family:monospace;font-size:.68rem;color:#475569}

/* ── tile layer switcher ── */
#tile-switcher{position:absolute;bottom:28px;left:10px;z-index:1000;
               display:flex;gap:4px;background:#1e2a3acc;
               border:1px solid #1e3a5f;border-radius:8px;padding:4px;
               backdrop-filter:blur(6px)}
.tile-btn{background:transparent;border:none;color:#94a3b8;font-size:.72rem;
          font-weight:500;padding:4px 10px;border-radius:5px;cursor:pointer;
          transition:background .15s,color .15s;white-space:nowrap}
.tile-btn:hover{background:#2a4060;color:#e2e8f0}
.tile-btn.active{background:#2563eb;color:#fff}

/* ── camera pin marker ── */
.cam-pin{width:34px;height:34px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);
         background:#2563eb;border:2.5px solid #fff;box-shadow:0 3px 10px #0009;
         display:flex;align-items:center;justify-content:center;
         transition:background .15s,transform .15s;cursor:pointer}
.cam-pin:hover,.cam-pin.active{background:#38bdf8;transform:rotate(-45deg) scale(1.18)}
.cam-pin .inner{transform:rotate(45deg);font-size:14px;line-height:1;user-select:none}

/* ── lightbox ── */
#lb{display:none;position:fixed;inset:0;background:#000d;z-index:9999;
    align-items:center;justify-content:center;flex-direction:column;gap:10px}
#lb.on{display:flex}
#lb img{max-width:94vw;max-height:88vh;border-radius:6px;box-shadow:0 10px 50px #000}
#lb-close{position:fixed;top:14px;right:20px;font-size:2rem;color:#fff;
          cursor:pointer;line-height:1;user-select:none;text-shadow:0 2px 8px #000}
#lb-name{color:#94a3b8;font-size:.8rem}
</style>
</head>
<body>

<div id="topbar">
  <svg height="60" viewBox="0 0 480 240" role="img" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">
    <rect x="20" y="20" width="200" height="200" rx="30" fill="#0f1e38"/>
    <rect x="20" y="20" width="200" height="200" rx="30" fill="none" stroke="#1e3a5f" stroke-width="1.5"/>
    <path d="M55 195 C55 195 70 158 90 147 C108 137 110 165 130 155 C150 145 144 115 168 108 C180 104 188 121 196 131"
          stroke="#1d4ed8" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="6 5"/>
    <path d="M196 131 C210 148 198 88 178 72"
          stroke="#1d4ed8" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="6 5"/>
    <circle cx="55"  cy="195" r="5" fill="#60a5fa"/>
    <circle cx="90"  cy="147" r="5" fill="#60a5fa"/>
    <circle cx="130" cy="155" r="5" fill="#60a5fa"/>
    <circle cx="168" cy="108" r="5" fill="#60a5fa"/>
    <path d="M163 72 C163 72 163 50 178 50 C193 50 193 72 193 72 C193 72 178 92 178 92 C178 92 163 72 163 72 Z" fill="#3b82f6"/>
    <rect x="169" y="54" width="18" height="14" rx="3.5" fill="#0f1e38" opacity="0.25"/>
    <circle cx="178" cy="62" r="6.5" fill="#0f1e38" opacity="0.9"/>
    <circle cx="178" cy="62" r="3"   fill="#3b82f6"/>
    <text x="242" y="130" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif" font-size="52" font-weight="700" letter-spacing="-1.5" fill="#bfdbfe"><tspan fill="#60a5fa">Geo</tspan>Snap</text>
  </svg>
  <span class="pill" id="pill-photos"></span>
  <span class="pill" id="pill-gpx"></span>
</div>

<div id="shell">
  <div id="map"></div>
  <div id="sidebar">
    <div id="sidebar-head">Photos</div>
    <div id="thumb-list"></div>
  </div>
</div>

<div id="lb">
  <span id="lb-close" title="Close (Esc)">&times;</span>
  <img id="lb-img" src="" alt="">
  <span id="lb-name"></span>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
// ── injected data ──────────────────────────────────────────────────────────
const TRACK  = DATA_TRACK_LINE;
const PHOTOS = DATA_PHOTOS;
const GPX    = DATA_GPX_NAME;
// ──────────────────────────────────────────────────────────────────────────

document.getElementById('pill-photos').innerHTML =
  '<b>' + PHOTOS.length + '</b> photo' + (PHOTOS.length !== 1 ? 's' : '') + ' geotagged';
document.getElementById('pill-gpx').innerHTML = '📍 ' + GPX;

// Map setup
const map = L.map('map', {zoomControl: true, layers: []});

const baseLayers = {
  'Street': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
  }),
  'Satellite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    maxZoom: 19
  }),
  'Topo': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://opentopomap.org">OpenTopoMap</a> contributors',
    maxZoom: 17
  }),
};
baseLayers['Street'].addTo(map);

// Custom tile switcher UI
const switcherEl = document.createElement('div');
switcherEl.id = 'tile-switcher';
switcherEl.innerHTML = Object.keys(baseLayers).map((name, i) =>
  `<button class="tile-btn${i===0?' active':''}" data-layer="${name}">${name}</button>`
).join('');
document.getElementById('map').appendChild(switcherEl);

let activeLayer = baseLayers['Street'];
switcherEl.addEventListener('click', e => {
  const btn = e.target.closest('.tile-btn');
  if (!btn) return;
  const name = btn.dataset.layer;
  if (baseLayers[name] === activeLayer) return;
  map.removeLayer(activeLayer);
  baseLayers[name].addTo(map);
  // keep track line and markers on top
  activeLayer = baseLayers[name];
  switcherEl.querySelectorAll('.tile-btn').forEach(b => b.classList.toggle('active', b === btn));
});

// GPX polyline
if (TRACK.length > 1) {
  L.polyline(TRACK, {color:'#38bdf8', weight:3, opacity:.6}).addTo(map);
}

// Lightbox
const lb      = document.getElementById('lb');
const lbImg   = document.getElementById('lb-img');
const lbName  = document.getElementById('lb-name');
function openLb(src, name) { lbImg.src = src; lbName.textContent = name; lb.classList.add('on'); }
document.getElementById('lb-close').onclick = () => lb.classList.remove('on');
lb.addEventListener('click', e => { if (e.target === lb) lb.classList.remove('on'); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') lb.classList.remove('on'); });

// Sidebar + markers
const thumbList = document.getElementById('thumb-list');
const allMarkers = [];
const allPins    = [];
const bounds     = [];

function activatePhoto(i) {
  // deactivate all
  allPins.forEach((el, j) => {
    el.classList.toggle('active', j === i);
  });
  document.querySelectorAll('.thumb-item').forEach((el, j) => {
    el.classList.toggle('active', j === i);
  });
  // pan and open popup
  const m = allMarkers[i];
  map.panTo(m.getLatLng(), {animate: true});
  m.openPopup();
  // scroll sidebar
  const thumb = document.querySelectorAll('.thumb-item')[i];
  if (thumb) thumb.scrollIntoView({block:'nearest', behavior:'smooth'});
}

PHOTOS.forEach((p, i) => {
  const src = 'data:image/jpeg;base64,' + p.thumb;

  // ── marker ──
  const pinEl = document.createElement('div');
  pinEl.className = 'cam-pin';
  pinEl.innerHTML = '<span class="inner">📷</span>';
  allPins.push(pinEl);

  const icon = L.divIcon({
    html: pinEl, className: '',
    iconSize: [34,34], iconAnchor: [17,34], popupAnchor: [0,-36]
  });

  const marker = L.marker([p.lat, p.lon], {icon}).addTo(map);
  allMarkers.push(marker);
  bounds.push([p.lat, p.lon]);

  const eleStr = p.ele !== null
    ? '<span>⬆ ' + p.ele.toFixed(1) + ' m elevation</span>' : '';

  marker.bindPopup(`
    <img class="popup-img" src="${src}" alt="${p.name}"
         onclick="openLb('${src}','${p.name}')">
    <div class="popup-body">
      <div class="popup-name">${p.name}</div>
      <div class="popup-meta">
        <span>🕐 ${p.time}</span>
        <span class="coord">📍 ${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}</span>
        ${eleStr}
      </div>
    </div>`, {maxWidth:320, minWidth:260});

  marker.on('click', () => activatePhoto(i));

  // ── sidebar thumbnail ──
  const item = document.createElement('div');
  item.className = 'thumb-item';
  item.innerHTML = `<img src="${src}" alt="${p.name}">
                    <div class="thumb-label">${p.name}</div>`;
  item.addEventListener('click', () => activatePhoto(i));
  thumbList.appendChild(item);
});

// Fit view
if (bounds.length > 0) {
  map.fitBounds(bounds, {padding:[40,40]});
} else if (TRACK.length > 0) {
  map.fitBounds(TRACK, {padding:[40,40]});
} else {
  map.setView([0,0], 2);
}
</script>
</body>
</html>
"""


def generate_map(output_folder, tagged_images, track_line, gpx_name):
    """Build a self-contained HTML map and return its path."""
    photo_data = []
    print(f"  Building thumbnails for {len(tagged_images)} image(s)…")
    for item in tagged_images:
        try:
            thumb = make_thumbnail_b64(item["img_path"])
        except Exception as e:
            print(f"    WARNING: thumbnail failed for {item['name']}: {e}")
            thumb = ""
        photo_data.append({
            "name":  item["name"],
            "lat":   item["lat"],
            "lon":   item["lon"],
            "ele":   item["ele"],
            "time":  item["time_str"],
            "thumb": thumb,
        })

    html = MAP_HTML \
        .replace("DATA_TRACK_LINE", json.dumps(track_line)) \
        .replace("DATA_PHOTOS",     json.dumps(photo_data)) \
        .replace("DATA_GPX_NAME",   json.dumps(gpx_name))

    map_path = output_folder / "map.html"
    map_path.write_text(html, encoding="utf-8")
    return map_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    image_folder = Path(args.image_folder)
    gpx_file     = Path(args.gpx_file)

    if not image_folder.is_dir():
        sys.exit(f"ERROR: Image folder not found: {image_folder}")
    if not gpx_file.is_file():
        sys.exit(f"ERROR: GPX file not found: {gpx_file}")

    print(f"Loading GPX track: {gpx_file}")
    try:
        points     = load_trackpoints(str(gpx_file))
        track_line = load_track_polyline(str(gpx_file))
    except Exception as e:
        sys.exit(f"ERROR: Could not parse GPX file: {e}")

    if not points:
        sys.exit("ERROR: GPX file contains no timestamped trackpoints.")

    print(f"  {len(points)} trackpoints  |  "
          f"{points[0][0].strftime('%Y-%m-%d %H:%M:%S')} → "
          f"{points[-1][0].strftime('%Y-%m-%d %H:%M:%S')} UTC")

    output_folder = image_folder / args.output
    output_folder.mkdir(parents=True, exist_ok=True)
    print(f"Output folder: {output_folder}\n")

    images = sorted(p for p in image_folder.iterdir()
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
    if not images:
        sys.exit(f"No JPEG/TIFF images found in {image_folder}")

    offset_delta = timedelta(hours=args.offset)
    label = f"{args.offset:+.2g}h offset" if args.offset != 0 else "no time offset"
    stats = {"tagged": 0, "no_exif": 0, "out_of_range": 0, "error": 0}
    tagged_images = []

    print(f"Processing {len(images)} image(s)  [{label}, max gap {args.max_gap:.0f}s]\n")
    print(f"  {'File':<35}  Status")
    print(f"  {'-'*35}  {'-'*42}")

    for img_path in images:
        dest_path = output_folder / img_path.name

        img_dt = exif_datetime(img_path)
        if img_dt is None:
            stats["no_exif"] += 1
            if args.verbose:
                print(f"  {img_path.name:<35}  SKIP — no EXIF timestamp")
            continue

        img_dt_utc = img_dt.replace(tzinfo=timezone.utc) + offset_delta
        result = interpolate_position(points, img_dt_utc, args.max_gap)
        if result is None:
            stats["out_of_range"] += 1
            if args.verbose:
                print(f"  {img_path.name:<35}  SKIP — outside track window "
                      f"({img_dt_utc.strftime('%H:%M:%S')} UTC)")
            continue

        lat, lon, ele = result
        try:
            write_gps_exif(img_path, dest_path, lat, lon, ele)
            stats["tagged"] += 1
            ele_str = f"  ele {ele:+.1f}m" if ele is not None else ""
            print(f"  {img_path.name:<35}  OK  {lat:+.6f}, {lon:+.6f}{ele_str}")
            tagged_images.append({
                "name":     img_path.name,
                "lat":      lat,  "lon": lon,  "ele": ele,
                "time_str": img_dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "img_path": dest_path,
            })
        except Exception as e:
            stats["error"] += 1
            print(f"  {img_path.name:<35}  ERROR — {e}")

    print(f"\n{'─'*60}")
    print(f"  Geotagged   : {stats['tagged']}")
    print(f"  No EXIF time: {stats['no_exif']}")
    print(f"  Out of range: {stats['out_of_range']}")
    if stats["error"]:
        print(f"  Errors      : {stats['error']}")
    print(f"{'─'*60}")

    if stats["tagged"]:
        print(f"\nGeotagged images saved to: {output_folder}")

    if not args.no_map and tagged_images:
        print("\nGenerating interactive map…")
        map_path = generate_map(output_folder, tagged_images, track_line, gpx_file.name)
        print(f"  Saved: {map_path}")
        print("  Opening in browser…")
        webbrowser.open(map_path.as_uri())
    elif not tagged_images:
        print("\nNo images geotagged — map not generated.")


if __name__ == "__main__":
    main()
