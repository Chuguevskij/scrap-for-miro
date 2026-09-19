"""Фильтрация служебных картинок и дедупликация найденных URL."""

import re

from .models import ImageCandidate
from .urls import normalized_image_key


JUNK_IMAGE = re.compile(
    r"logo|icon|sprite|favicon|spacer|blank|pixel|placeholder|arrow|chevron|"
    r"flag|payment|badge|review|avatar|emoji|banner|promo|widget|chat|support|"
    r"nav_|_nav|/nav|editorial|campaign|hero[_-]|marquee|\.svg|\.gif|\.mp4|\.pdf|meta\.json",
    re.I,
)


def unique_images(images: list[ImageCandidate]) -> list[ImageCandidate]:
    """Оставить первый встретившийся URL после нормализации CDN-параметров."""
    result = []
    seen = set()
    for image in sorted(images, key=lambda item: item.position):
        key = normalized_image_key(image.url)
        if key not in seen:
            seen.add(key)
            result.append(image)
    return result


def select_images(images: list[ImageCandidate], keep_all: bool = False) -> list[ImageCandidate]:
    """Отбросить очевидные элементы интерфейса, сохранив порядок страницы."""
    if keep_all:
        return unique_images(images)
    embedded = [image for image in images if image.source == "embedded-json"]
    if len(embedded) >= 2:
        return unique_images(embedded)
    images = unique_images(images)
    clean = [image for image in images if not JUNK_IMAGE.search(image.url)]
    return clean if len(clean) > 2 else images
