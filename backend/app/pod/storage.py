"""Storage seam: the development adapter returns a dummy URL, no network I/O."""

from typing import Protocol


class PermanentStorageError(Exception):
    pass


class PodStorage(Protocol):
    def upload(self, object_key: str, data: bytes, content_type: str) -> str: ...


class DummyPodStorage:
    def upload(self, object_key: str, data: bytes, content_type: str) -> str:
        # .invalid cannot be confused with a configured real public bucket.
        return "https://pod.invalid/" + object_key
