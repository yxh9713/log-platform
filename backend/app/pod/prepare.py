"""Bounded JPEG/PNG validation and deterministic metadata-free preparation."""

import base64
import binascii
import hashlib
import io
from dataclasses import dataclass, field

from PIL import Image, ImageOps

from app.shipments.common import DomainError

MAX_INPUT = 5_000_000
MAX_PREPARED = 20_000_000
MAX_PIXELS = 20_000_000
MAX_SIDE = 20_000


@dataclass(frozen=True)
class PreparedImage:
    data: bytes = field(repr=False)
    content_type: str
    width: int
    height: int
    input_size: int

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def bounds(image: Image.Image) -> None:
    if (
        image.width < 1
        or image.height < 1
        or max(image.size) > MAX_SIDE
        or image.width * image.height > MAX_PIXELS
        or getattr(image, "n_frames", 1) != 1
    ):
        raise ValueError("Image dimensions/frames exceeded")


def prepare(value: str) -> PreparedImage:
    try:
        if not value or len(value) > ((MAX_INPUT + 2) // 3) * 4:
            raise ValueError("Encoded size exceeded")
        raw = base64.b64decode(value, validate=True)
        if not raw or len(raw) > MAX_INPUT:
            raise ValueError("Decoded size exceeded")
        # Restrict plugin selection before load; verify and fully decode in
        # separate opens so truncated data cannot masquerade as a valid image.
        with Image.open(io.BytesIO(raw), formats=("JPEG", "PNG")) as check:
            bounds(check)
            image_format = check.format
            check.verify()
        with Image.open(io.BytesIO(raw), formats=("JPEG", "PNG")) as decoded:
            bounds(decoded)
            decoded.load()
            with ImageOps.exif_transpose(decoded) as oriented:
                width = min(oriented.width, 900)
                height = max(
                    1, (oriented.height * width + oriented.width // 2) // oriented.width
                )
                mode = (
                    "RGBA"
                    if image_format == "PNG"
                    and ("A" in oriented.getbands() or "transparency" in oriented.info)
                    else "RGB"
                )
                with oriented.convert(mode) as converted:
                    with converted.resize(
                        (width, height), Image.Resampling.LANCZOS
                    ) as resized:
                        # Drop EXIF, comments, ICC and text instead of passing
                        # metadata copied by Pillow to the output encoder.
                        resized.info.clear()
                        output = io.BytesIO()
                        if image_format == "JPEG":
                            resized.save(
                                output, format="JPEG", quality=85, optimize=True
                            )
                        else:
                            resized.save(output, format="PNG", optimize=True)
        data = output.getvalue()
        if not data or len(data) > MAX_PREPARED:
            raise ValueError("Prepared size exceeded")
        with Image.open(io.BytesIO(data), formats=("JPEG", "PNG")) as prepared:
            if prepared.size != (width, height) or prepared.format != image_format:
                raise ValueError("Prepared image mismatch")
            prepared.verify()
        return PreparedImage(
            data,
            "image/jpeg" if image_format == "JPEG" else "image/png",
            width,
            height,
            len(raw),
        )
    except (
        binascii.Error,
        ValueError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ):
        raise DomainError(400, "Invalid POD image", "invalid_pod_image") from None
