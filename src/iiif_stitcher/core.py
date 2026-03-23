from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Mapping
from urllib.parse import parse_qs, urlencode, urlparse

from PIL import Image


class StitcherError(RuntimeError):
    """Domain error for IIIF stitching pipeline."""


@dataclass(frozen=True)
class SourceSpec:
    object_id: str
    dept: str
    image_name: str


@dataclass(frozen=True)
class CanvasImage:
    index: int
    label: str
    service_id: str
    width: int
    height: int


TileRegion = tuple[int, int, int, int]


def parse_source_url(url: str) -> SourceSpec:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    object_id = _required_query(query, "id")
    dept = _required_query(query, "dep")
    image_name = _required_query(query, "imageName")

    return SourceSpec(object_id=object_id, dept=dept, image_name=image_name)


def _required_query(query: Mapping[str, list[str]], key: str) -> str:
    values = query.get(key)
    if not values or not values[0]:
        raise StitcherError(f"missing required query parameter: {key}")
    return values[0]


def build_manifest_url(spec: SourceSpec) -> str:
    return (
        "https://digitalarchive.npm.gov.tw/Integrate/GetJson?"
        + urlencode(
            {
                "cid": spec.object_id,
                "dept": spec.dept,
                "imageName": spec.image_name,
            }
        )
    )


def build_info_url(service_id: str) -> str:
    return service_id.rstrip("/") + "/info.json"


def build_full_image_url(service_id: str) -> str:
    return service_id.rstrip("/") + "/full/full/0/default.jpg"


def build_tile_url(service_id: str, region: TileRegion) -> str:
    x, y, w, h = region
    return f"{service_id.rstrip('/')}/{x},{y},{w},{h}/full/0/default.jpg"


def extract_canvas_images(manifest: dict) -> list[CanvasImage]:
    sequences = manifest.get("sequences") or []
    if not sequences:
        raise StitcherError("manifest has no sequences")
    canvases = sequences[0].get("canvases") or []
    if not canvases:
        raise StitcherError("manifest has no canvases")

    results: list[CanvasImage] = []
    for idx, canvas in enumerate(canvases, start=1):
        try:
            service_id = canvas["images"][0]["resource"]["service"]["@id"]
        except Exception as exc:
            raise StitcherError(f"missing service id in canvas #{idx}") from exc

        results.append(
            CanvasImage(
                index=idx,
                label=str(canvas.get("label", f"canvas-{idx}")),
                service_id=service_id,
                width=int(canvas.get("width", 0)),
                height=int(canvas.get("height", 0)),
            )
        )
    return results


def plan_tiles(width: int, height: int, tile_width: int, tile_height: int) -> list[TileRegion]:
    if width <= 0 or height <= 0:
        raise StitcherError("width/height must be positive")
    if tile_width <= 0 or tile_height <= 0:
        raise StitcherError("tile_width/tile_height must be positive")

    regions: list[TileRegion] = []
    y = 0
    while y < height:
        h = min(tile_height, height - y)
        x = 0
        while x < width:
            w = min(tile_width, width - x)
            regions.append((x, y, w, h))
            x += tile_width
        y += tile_height
    return regions


def stitch_tiles(
    width: int,
    height: int,
    tiles: Mapping[TileRegion, bytes],
) -> Image.Image:
    if width <= 0 or height <= 0:
        raise StitcherError("width/height must be positive for stitching")
    if not tiles:
        raise StitcherError("no tiles to stitch")

    canvas = Image.new("RGB", (width, height))
    for region, payload in tiles.items():
        x, y, w, h = region
        tile = Image.open(BytesIO(payload)).convert("RGB")

        if tile.size != (w, h):
            # Protect against server-side resize mismatch.
            tile = tile.resize((w, h), Image.Resampling.LANCZOS)

        canvas.paste(tile, (x, y))
    return canvas


def build_output_name(index: int, label: str) -> str:
    sanitized = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in label.strip())
    if not sanitized:
        sanitized = f"canvas_{index:03d}"
    return f"{index:03d}_{sanitized}.jpg"


def build_source_hash(source_url: str, length: int = 8) -> str:
    parsed = urlparse(source_url.strip())
    query = parse_qs(parsed.query, keep_blank_values=True)

    canonical_items: list[str] = []
    for key in sorted(query):
        for value in sorted(query[key]):
            canonical_items.append(f"{key}={value}")

    canonical = (
        f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}"
        f"?{'&'.join(canonical_items)}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]
