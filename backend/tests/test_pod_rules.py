import base64
import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image, PngImagePlugin

from app.pod.prepare import MAX_INPUT, prepare
from app.shipments.common import DomainError
from tests.pod_support import image_bytes, image_input


@pytest.mark.parametrize("fmt", ["JPEG", "PNG"])
@pytest.mark.parametrize(
    "size,expected",
    [
        ((1800, 900), (900, 450)),
        ((1200, 2400), (900, 1800)),
        ((300, 200), (300, 200)),
        ((901, 1), (900, 1)),
    ],
)
def test_formats_aspect_cap_and_prepared_metadata(
    fmt: str, size: tuple[int, int], expected: tuple[int, int]
) -> None:
    result = prepare(image_input(fmt, size))
    assert (
        result.width,
        result.height,
    ) == expected and result.content_type == "image/" + fmt.lower().replace(
        "jpg", "jpeg"
    )
    assert result.digest and result.data and "data=" not in repr(result)
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.size == expected and image.format == fmt
        image.verify()


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not base64",
        "base64 string",
        "data:image/png;base64,YQ==",
        "a\nb",
        "☃",
        base64.b64encode(b"not an image").decode(),
    ],
)
def test_invalid_encoding_and_content(value: str) -> None:
    with pytest.raises(DomainError, match="Invalid POD image"):
        prepare(value)


@pytest.mark.parametrize("fmt", ["GIF", "WEBP", "BMP", "TIFF"])
def test_only_jpeg_png_formats(fmt: str) -> None:
    with pytest.raises(DomainError):
        prepare(base64.b64encode(image_bytes(fmt, (10, 10))).decode())


def test_decoded_five_million_byte_boundary_and_truncation() -> None:
    original = image_bytes(size=(16, 16))
    exact = original + b"\x00" * (MAX_INPUT - len(original))
    result = prepare(base64.b64encode(exact).decode())
    assert result.input_size == MAX_INPUT and len(result.data) < 1000
    with pytest.raises(DomainError):
        prepare(base64.b64encode(exact + b"\x00").decode())
    with pytest.raises(DomainError):
        prepare(base64.b64encode(image_bytes("JPEG")[:100]).decode())
    broken = bytearray(original)
    broken[40] ^= 0xFF
    with pytest.raises(DomainError):
        prepare(base64.b64encode(broken).decode())


def test_pixel_side_animation_and_prepared_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.pod.prepare.MAX_PIXELS", 100)
    with pytest.raises(DomainError):
        prepare(image_input(size=(11, 10)))
    monkeypatch.setattr("app.pod.prepare.MAX_PIXELS", 20_000_000)
    monkeypatch.setattr("app.pod.prepare.MAX_SIDE", 20)
    with pytest.raises(DomainError):
        prepare(image_input(size=(21, 1)))
    monkeypatch.setattr("app.pod.prepare.MAX_SIDE", 20_000)
    output = io.BytesIO()
    with (
        Image.new("RGB", (10, 10), "white") as first,
        Image.new("RGB", (10, 10), "black") as second,
    ):
        first.save(
            output, format="PNG", save_all=True, append_images=[second], duration=100
        )
    with pytest.raises(DomainError):
        prepare(base64.b64encode(output.getvalue()).decode())
    monkeypatch.setattr("app.pod.prepare.MAX_PREPARED", 10)
    with pytest.raises(DomainError):
        prepare(image_input(size=(10, 10)))


def test_metadata_removed_transparency_and_orientation() -> None:
    output = io.BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text("private", "must be removed")
    with Image.new("RGBA", (32, 16), (0, 0, 0, 0)) as source:
        source.save(output, format="PNG", pnginfo=meta)
    prepared = prepare(base64.b64encode(output.getvalue()).decode())
    with Image.open(io.BytesIO(prepared.data)) as image:
        assert image.mode == "RGBA" and "private" not in image.info
        pixel = image.getpixel((0, 0))
        assert isinstance(pixel, tuple) and pixel[-1] == 0
    output = io.BytesIO()
    with Image.new("RGB", (1200, 600), "white") as source:
        exif = Image.Exif()
        exif[274] = 6
        source.save(output, format="JPEG", exif=exif)
    prepared = prepare(base64.b64encode(output.getvalue()).decode())
    assert (prepared.width, prepared.height) == (600, 1200)
    with Image.open(io.BytesIO(prepared.data)) as image:
        assert not image.getexif()


def test_parallel_preparation_is_deterministic() -> None:
    value = image_input()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(prepare, [value] * 3))
    assert len({result.digest for result in results}) == 1
