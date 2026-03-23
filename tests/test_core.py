from __future__ import annotations

from io import BytesIO

from PIL import Image

from iiif_stitcher.core import (
    CanvasImage,
    StitcherError,
    build_full_image_url,
    build_info_url,
    build_manifest_url,
    build_source_hash,
    build_tile_url,
    extract_canvas_images,
    parse_source_url,
    plan_tiles,
    stitch_tiles,
)


def _img_bytes(color: tuple[int, int, int], size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, color=color)
    buff = BytesIO()
    image.save(buff, format="JPEG")
    return buff.getvalue()


def test_parse_source_url_extracts_expected_params() -> None:
    source = (
        "https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer"
        "?id=31252&dep=P&imageName=437238^^^19922800088"
    )
    spec = parse_source_url(source)
    assert spec.object_id == "31252"
    assert spec.dept == "P"
    assert spec.image_name == "437238^^^19922800088"


def test_parse_source_url_raises_on_missing_required_query() -> None:
    try:
        parse_source_url("https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer?id=31252")
    except StitcherError as exc:
        assert "dep" in str(exc)
    else:
        raise AssertionError("expected StitcherError")


def test_build_source_hash_is_8_chars_and_stable_for_query_order() -> None:
    u1 = (
        "https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer"
        "?id=31252&dep=P&imageName=437238^^^19922800088"
    )
    u2 = (
        "https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer"
        "?imageName=437238^^^19922800088&dep=P&id=31252"
    )
    h1 = build_source_hash(u1)
    h2 = build_source_hash(u2)
    assert h1 == h2
    assert len(h1) == 8
    assert h1.isalnum()


def test_build_manifest_and_info_urls() -> None:
    source = (
        "https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer"
        "?id=31252&dep=P&imageName=437238^^^19922800088"
    )
    spec = parse_source_url(source)
    assert (
        build_manifest_url(spec)
        == "https://digitalarchive.npm.gov.tw/Integrate/GetJson"
        "?cid=31252&dept=P&imageName=437238%5E%5E%5E19922800088"
    )
    assert (
        build_info_url("https://iiifod.npm.gov.tw/iiif/2/A2B%2FA2B000205N000000000PAB")
        == "https://iiifod.npm.gov.tw/iiif/2/A2B%2FA2B000205N000000000PAB/info.json"
    )
    assert (
        build_full_image_url("https://iiifod.npm.gov.tw/iiif/2/A2B%2FA2B000205N000000000PAB")
        == "https://iiifod.npm.gov.tw/iiif/2/A2B%2FA2B000205N000000000PAB/full/full/0/default.jpg"
    )


def test_extract_canvas_images_from_manifest() -> None:
    manifest = {
        "sequences": [
            {
                "canvases": [
                    {
                        "label": "A",
                        "width": "1000",
                        "height": "749",
                        "images": [
                            {
                                "resource": {
                                    "service": {
                                        "@id": "https://iiifod.npm.gov.tw/iiif/2/A2B%2FA",
                                    }
                                }
                            }
                        ],
                    },
                    {
                        "label": "B",
                        "width": "1000",
                        "height": "749",
                        "images": [
                            {
                                "resource": {
                                    "service": {
                                        "@id": "https://iiifod.npm.gov.tw/iiif/2/A2B%2FB",
                                    }
                                }
                            }
                        ],
                    },
                ]
            }
        ]
    }
    canvases = extract_canvas_images(manifest)
    assert canvases == [
        CanvasImage(
            index=1,
            label="A",
            service_id="https://iiifod.npm.gov.tw/iiif/2/A2B%2FA",
            width=1000,
            height=749,
        ),
        CanvasImage(
            index=2,
            label="B",
            service_id="https://iiifod.npm.gov.tw/iiif/2/A2B%2FB",
            width=1000,
            height=749,
        ),
    ]


def test_plan_tiles_covers_edge_blocks() -> None:
    tiles = plan_tiles(width=1000, height=749, tile_width=512, tile_height=512)
    assert len(tiles) == 4
    assert tiles[0] == (0, 0, 512, 512)
    assert tiles[1] == (512, 0, 488, 512)
    assert tiles[2] == (0, 512, 512, 237)
    assert tiles[3] == (512, 512, 488, 237)


def test_build_tile_url_from_region() -> None:
    url = build_tile_url(
        service_id="https://iiifod.npm.gov.tw/iiif/2/A2B%2FA2B000205N000000000PAB",
        region=(512, 1024, 488, 237),
    )
    assert (
        url
        == "https://iiifod.npm.gov.tw/iiif/2/A2B%2FA2B000205N000000000PAB/512,1024,488,237/full/0/default.jpg"
    )


def test_stitch_tiles_puts_each_tile_in_expected_position() -> None:
    tiles = {
        (0, 0, 2, 2): _img_bytes((255, 0, 0), (2, 2)),
        (2, 0, 2, 2): _img_bytes((0, 255, 0), (2, 2)),
        (0, 2, 2, 2): _img_bytes((0, 0, 255), (2, 2)),
        (2, 2, 2, 2): _img_bytes((255, 255, 0), (2, 2)),
    }
    stitched = stitch_tiles(4, 4, tiles)

    assert stitched.size == (4, 4)
    assert stitched.getpixel((0, 0))[0] > 200  # top-left red
    assert stitched.getpixel((3, 0))[1] > 200  # top-right green
    assert stitched.getpixel((0, 3))[2] > 200  # bottom-left blue
    px = stitched.getpixel((3, 3))
    assert px[0] > 200 and px[1] > 200  # bottom-right yellow
