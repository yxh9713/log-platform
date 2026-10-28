import base64
import io

from PIL import Image


def image_bytes(
    fmt: str = "PNG", size: tuple[int, int] = (1800, 900), *, mode: str = "RGB"
) -> bytes:
    output = io.BytesIO()
    with Image.new(mode, size, "white") as image:
        image.save(output, format=fmt)
    return output.getvalue()


def image_input(fmt: str = "PNG", size: tuple[int, int] = (1800, 900)) -> str:
    return base64.b64encode(image_bytes(fmt, size)).decode("ascii")
