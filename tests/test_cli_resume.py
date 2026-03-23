from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
import requests

from iiif_stitcher import cli
from iiif_stitcher.core import CanvasImage, build_output_name, build_source_hash


def _jpg_bytes(size: tuple[int, int]) -> bytes:
    img = Image.new("RGB", size, color=(12, 34, 56))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_download_one_canvas_skips_existing_valid_file(tmp_path: Path, monkeypatch) -> None:
    canvas = CanvasImage(
        index=1,
        label="A2B000205N000000000PAB",
        service_id="https://iiifod.npm.gov.tw/iiif/2/A2B%2FA2B000205N000000000PAB",
        width=1000,
        height=749,
    )
    output_path = tmp_path / build_output_name(canvas.index, canvas.label)
    output_path.write_bytes(_jpg_bytes((10, 8)))

    monkeypatch.setattr(
        cli,
        "_http_get_json",
        lambda *_args, **_kwargs: {"width": 10, "height": 8, "tiles": [{"width": 4, "height": 4}]},
    )
    monkeypatch.setattr(cli, "_http_head_content_length", lambda *_args, **_kwargs: output_path.stat().st_size)

    call_count = {"n": 0}

    def _never_download(*_args, **_kwargs) -> bytes:
        call_count["n"] += 1
        return _jpg_bytes((10, 8))

    monkeypatch.setattr(cli, "_http_get_binary", _never_download)

    session = requests.Session()
    result = cli._download_one_canvas(
        session=session,
        canvas=canvas,
        output_dir=tmp_path,
        timeout=1.0,
        retries=1,
        force_tiles=False,
    )

    assert result == output_path
    assert call_count["n"] == 0


def test_download_one_canvas_redownloads_when_existing_file_invalid(tmp_path: Path, monkeypatch) -> None:
    canvas = CanvasImage(
        index=1,
        label="A2B000205N000000000PAB",
        service_id="https://iiifod.npm.gov.tw/iiif/2/A2B%2FA2B000205N000000000PAB",
        width=1000,
        height=749,
    )
    output_path = tmp_path / build_output_name(canvas.index, canvas.label)
    output_path.write_bytes(b"not-a-valid-image")

    monkeypatch.setattr(
        cli,
        "_http_get_json",
        lambda *_args, **_kwargs: {"width": 10, "height": 8, "tiles": [{"width": 4, "height": 4}]},
    )
    monkeypatch.setattr(cli, "_http_head_content_length", lambda *_args, **_kwargs: None)

    call_count = {"n": 0}

    def _download_once(*_args, **_kwargs) -> bytes:
        call_count["n"] += 1
        return _jpg_bytes((10, 8))

    monkeypatch.setattr(cli, "_http_get_binary", _download_once)

    session = requests.Session()
    result = cli._download_one_canvas(
        session=session,
        canvas=canvas,
        output_dir=tmp_path,
        timeout=1.0,
        retries=1,
        force_tiles=False,
    )

    assert result == output_path
    assert call_count["n"] == 1
    with Image.open(output_path) as final_img:
        assert final_img.size == (10, 8)


def test_run_places_output_under_hash_subfolder(tmp_path: Path, monkeypatch) -> None:
    source = (
        "https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer"
        "?id=31252&dep=P&imageName=437238^^^19922800088"
    )
    expected_dir = tmp_path / build_source_hash(source)

    monkeypatch.setattr(cli, "_http_get_json", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        cli,
        "extract_canvas_images",
        lambda _manifest: [
            CanvasImage(
                index=1,
                label="A",
                service_id="https://iiifod.npm.gov.tw/iiif/2/A2B%2FA",
                width=1000,
                height=749,
            )
        ],
    )

    captured: dict[str, Path] = {}

    def _fake_download_one_canvas(*, output_dir: Path, **_kwargs):
        captured["output_dir"] = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        p = output_dir / "001_A.jpg"
        p.write_bytes(_jpg_bytes((2, 2)))
        return p

    monkeypatch.setattr(cli, "_download_one_canvas", _fake_download_one_canvas)

    result = cli.run(source_url=source, output_dir=tmp_path, insecure=True, limit=1)
    assert captured["output_dir"] == expected_dir
    assert result == [expected_dir / "001_A.jpg"]

