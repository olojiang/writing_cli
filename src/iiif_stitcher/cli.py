from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import requests
import urllib3
from PIL import Image, UnidentifiedImageError

from iiif_stitcher.core import (
    CanvasImage,
    build_full_image_url,
    build_info_url,
    build_manifest_url,
    build_output_name,
    build_source_hash,
    build_tile_url,
    extract_canvas_images,
    parse_source_url,
    plan_tiles,
    stitch_tiles,
)


LOGGER = logging.getLogger("iiif_stitcher")


def _configure_logging(output_dir: Path, verbose: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    LOGGER.setLevel(level)
    LOGGER.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    LOGGER.addHandler(stream_handler)

    file_handler = logging.FileHandler(output_dir / "run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    LOGGER.addHandler(file_handler)


def _http_get_json(session: requests.Session, url: str, timeout: float) -> dict[str, Any]:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _http_get_binary(
    session: requests.Session,
    url: str,
    timeout: float,
    retries: int,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            LOGGER.warning("download failed (%s/%s): %s", attempt, retries, url)
    assert last_error is not None
    raise last_error


def _http_head_content_length(
    session: requests.Session,
    url: str,
    timeout: float,
) -> int | None:
    try:
        resp = session.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            return None
        raw = resp.headers.get("Content-Length")
        if not raw:
            return None
        return int(raw)
    except Exception:  # noqa: BLE001
        return None


def _is_existing_valid_image(
    path: Path,
    expected_width: int,
    expected_height: int,
    expected_size: int | None = None,
) -> bool:
    if not path.exists() or not path.is_file():
        return False
    size = path.stat().st_size
    if size <= 0:
        return False
    if expected_size is not None and size != expected_size:
        return False
    try:
        with Image.open(path) as img:
            return img.size == (expected_width, expected_height)
    except (OSError, UnidentifiedImageError):
        return False


def _extract_tile_conf(info: dict[str, Any]) -> tuple[int, int, int, int]:
    width = int(info["width"])
    height = int(info["height"])

    tiles = info.get("tiles") or []
    if tiles:
        first = tiles[0]
        tile_width = int(first.get("width", 512))
        tile_height = int(first.get("height", tile_width))
    else:
        tile_width = 512
        tile_height = 512

    return width, height, tile_width, tile_height


def _download_one_canvas(
    session: requests.Session,
    canvas: CanvasImage,
    output_dir: Path,
    timeout: float,
    retries: int,
    force_tiles: bool,
) -> Path:
    output_path = output_dir / build_output_name(canvas.index, canvas.label)
    LOGGER.info("[%03d] start %s", canvas.index, canvas.label)

    info = _http_get_json(session, build_info_url(canvas.service_id), timeout=timeout)
    width, height, tile_width, tile_height = _extract_tile_conf(info)

    full_url = build_full_image_url(canvas.service_id)
    expected_full_size = None if force_tiles else _http_head_content_length(session, full_url, timeout=timeout)
    if _is_existing_valid_image(
        output_path,
        expected_width=width,
        expected_height=height,
        expected_size=expected_full_size,
    ):
        LOGGER.info("[%03d] skip existing valid file: %s", canvas.index, output_path.name)
        return output_path

    if not force_tiles:
        try:
            blob = _http_get_binary(session, full_url, timeout=timeout, retries=retries)
            output_path.write_bytes(blob)
            if _is_existing_valid_image(
                output_path,
                expected_width=width,
                expected_height=height,
                expected_size=expected_full_size,
            ):
                LOGGER.info("[%03d] full image saved: %s", canvas.index, output_path.name)
                return output_path
            LOGGER.warning("[%03d] full image validation failed, fallback to tiles", canvas.index)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("[%03d] full download failed, fallback to tiles: %s", canvas.index, exc)
    regions = plan_tiles(width=width, height=height, tile_width=tile_width, tile_height=tile_height)

    LOGGER.info(
        "[%03d] tiles mode: %sx%s, tile=%sx%s, count=%s",
        canvas.index,
        width,
        height,
        tile_width,
        tile_height,
        len(regions),
    )

    payloads: dict[tuple[int, int, int, int], bytes] = {}
    for region in regions:
        tile_url = build_tile_url(canvas.service_id, region)
        payloads[region] = _http_get_binary(
            session,
            tile_url,
            timeout=timeout,
            retries=retries,
        )

    merged = stitch_tiles(width, height, payloads)
    merged.save(output_path, format="JPEG", quality=95)
    LOGGER.info("[%03d] stitched image saved: %s", canvas.index, output_path.name)
    return output_path


def run(
    source_url: str,
    output_dir: Path,
    force_tiles: bool = False,
    limit: int | None = None,
    timeout: float = 30.0,
    retries: int = 3,
    verbose: bool = False,
    insecure: bool = True,
) -> list[Path]:
    job_hash = build_source_hash(source_url)
    job_output_dir = output_dir / job_hash
    _configure_logging(job_output_dir, verbose)
    spec = parse_source_url(source_url)
    manifest_url = build_manifest_url(spec)
    LOGGER.info("job hash: %s", job_hash)
    LOGGER.info("output dir: %s", job_output_dir)
    LOGGER.info("manifest: %s", manifest_url)

    with requests.Session() as session:
        if insecure:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            session.verify = False
            LOGGER.warning("SSL verification is disabled (default)")
        session.headers.update(
            {
                "User-Agent": "iiif-stitcher/0.1 (+https://digitalarchive.npm.gov.tw)",
            }
        )

        manifest = _http_get_json(session, manifest_url, timeout=timeout)
        canvases = extract_canvas_images(manifest)
        if limit is not None and limit > 0:
            canvases = canvases[:limit]
        LOGGER.info("found canvases: %s", len(canvases))

        saved: list[Path] = []
        for canvas in canvases:
            saved.append(
                _download_one_canvas(
                    session=session,
                    canvas=canvas,
                    output_dir=job_output_dir,
                    timeout=timeout,
                    retries=retries,
                    force_tiles=force_tiles,
                )
            )
    return saved


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and stitch IIIF images from NPM IIIFViewer URL."
    )
    parser.add_argument("source_url", help="IIIFViewer URL")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="directory to store final images and logs",
    )
    parser.add_argument(
        "--force-tiles",
        action="store_true",
        help="always use tile stitching even if full image URL works",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max image count to process",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="http timeout seconds",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="retry count for each image request",
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    parser.add_argument("--insecure", dest="insecure", action="store_true", default=True, help="disable SSL certificate verification (default)")
    parser.add_argument("--secure", dest="insecure", action="store_false", help="enable SSL certificate verification")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    saved = run(
        source_url=args.source_url,
        output_dir=args.output_dir,
        force_tiles=args.force_tiles,
        limit=args.limit,
        timeout=args.timeout,
        retries=args.retries,
        verbose=args.verbose,
        insecure=args.insecure,
    )
    job_output_dir = args.output_dir / build_source_hash(args.source_url)
    print(f"saved {len(saved)} image(s) to {job_output_dir}")


if __name__ == "__main__":
    main()
