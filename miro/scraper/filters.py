"""Фильтрация служебных картинок и дедупликация найденных URL."""

import re

from .models import ImageCandidate
from .urls import normalized_image_key, resolution_rank


JUNK_IMAGE = re.compile(
    r"logo|icon|sprite|favicon|spacer|blank|pixel|placeholder|arrow|chevron|"
    r"flag|payment|badge|review|avatar|emoji|banner|promo|widget|chat|support|"
    r"nav_|_nav|/nav|editorial|campaign|hero[_-]|marquee|\.svg|\.gif|\.mp4|\.pdf|meta\.json|"
    # Промо-плитки и служебные картинки витрины, к фото товара отношения не имеют.
    r"mainrek/|/templates/|shoe_size|size[_-]grid|counter\.yandex|top\.mail",
    re.I,
)


def unique_images(images: list[ImageCandidate]) -> list[ImageCandidate]:
    """Оставить по одной ссылке на картинку, выбрав версия наибольшего разрешения."""
    best = {}
    for image in sorted(images, key=lambda item: item.position):
        key = normalized_image_key(image.url)
        current = best.get(key)
        if current is None or resolution_rank(image.url) > resolution_rank(current.url):
            best[key] = image
    return [image for _, image in sorted(best.items(), key=lambda pair: pair[1].position)]


def select_images(images: list[ImageCandidate], keep_all: bool = False) -> list[ImageCandidate]:
    """Отбросить очевидные элементы интерфейса, сохранив порядок страницы."""
    if keep_all:
        return unique_images(images)
    # Галерея и встроенный JSON — самые точные наборы ракурсов: они не содержат
    # картинок похожих товаров, но в них всё равно попадают промо-баннеры.
    for source in ("gallery", "embedded-json"):
        grouped = [image for image in images if image.source == source]
        if len(grouped) < 2:
            continue
        clean = [image for image in grouped if not JUNK_IMAGE.search(image.url)]
        return unique_images(clean if len(clean) >= 2 else grouped)
    images = unique_images(images)
    clean = [image for image in images if not JUNK_IMAGE.search(image.url)]
    return clean if len(clean) > 2 else images
