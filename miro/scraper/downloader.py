"""Скачивание выбранных изображений и чтение их размеров."""

import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .fetcher import USER_AGENT
from .models import ImageCandidate
from .urls import download_variant


@dataclass(frozen=True)
class DownloadedImage:
    """Локальный файл, связанный с исходным кандидатом."""

    path: str
    url: str
    width: int
    height: int


def image_dimensions(path: str) -> tuple[int, int]:
    """Прочитать размеры JPEG/PNG без внешних библиотек."""
    try:
        with open(path, "rb") as stream:
            data = stream.read(65_536)
    except OSError:
        return 0, 0
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 24:
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                height, width = struct.unpack(">HH", data[index + 5:index + 9])
                return width, height
            index += 2 + struct.unpack(">H", data[index + 2:index + 4])[0]
    return 0, 0


class ImageDownloader:
    """Скачать список кандидатов, не зная ничего о Miro и раскладке."""

    def __init__(self, timeout: int = 60, retries: int = 3, sleep=time.sleep):
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep

    def download(
        self,
        images: list[ImageCandidate],
        output_dir: str,
        target_width: int,
        start_index: int = 1,
    ) -> tuple[list[DownloadedImage], list[tuple[str, str]]]:
        os.makedirs(output_dir, exist_ok=True)
        downloaded = []
        failed = []
        for number, image in enumerate(images, start_index):
            variant = download_variant(image.url, target_width)
            extension = os.path.splitext(urllib.parse.urlsplit(variant).path)[1].lower()
            if extension not in (".jpg", ".jpeg", ".png", ".webp"):
                extension = ".jpg"
            destination = os.path.join(output_dir, "%02d%s" % (number, extension))
            try:
                self._download_one(variant, destination)
                width, height = image_dimensions(destination)
                downloaded.append(DownloadedImage(destination, image.url, width, height))
            except (OSError, urllib.error.URLError, ValueError) as exc:
                failed.append((image.url, str(exc)))
        return downloaded, failed

    def _download_one(self, url: str, destination: str) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = response.read()
                if len(data) < 1500:
                    raise OSError("файл подозрительно маленький")
                with open(destination, "wb") as stream:
                    stream.write(data)
                return
            except (OSError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt < self.retries:
                    self.sleep(2 * attempt)
        raise OSError(str(last_error))
