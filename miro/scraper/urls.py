"""Нормализация URL картинок и ссылки на вариант нужного размера."""

import re
import urllib.parse


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
SIZE_PARAMETERS = {"w", "width", "size"}
SIZE_SUFFIX = re.compile(r"_\d+x\d*(?=\.[A-Za-z0-9]+$)")
# Часть CDN складывает одно и то же фото в каталоги вида images/, images/bimages/, images/b2images/.
RESOLUTION_DIR = re.compile(r"(?:^|/)b\d*images(?=/)", re.I)
RESOLUTION_RANK = re.compile(r"/b(\d*)images/", re.I)


def absolute_url(raw_url: str, base_url: str) -> str:
    """Преобразовать относительную, protocol-relative или обычную ссылку в абсолютную."""
    raw_url = raw_url.strip()
    if raw_url.startswith("//"):
        scheme = urllib.parse.urlparse(base_url).scheme or "https"
        return scheme + ":" + raw_url
    return urllib.parse.urljoin(base_url, raw_url)


def resolution_rank(url: str) -> int:
    """Разрешение из имени каталога CDN: bimages < b2images < b3images."""
    match = RESOLUTION_RANK.search(urllib.parse.urlsplit(url).path)
    return int(match.group(1) or 1) if match else 0


def _single_resolution_path(path: str) -> str:
    """Убрать из пути сегмент-метку разрешения, чтобы версии одного фото стали одним путём."""
    return RESOLUTION_DIR.sub("", path, count=1)


def normalized_image_key(url: str) -> str:
    """Убрать CDN-параметры и метки разрешения, сохранив остальные параметры ссылки."""
    parsed = urllib.parse.urlsplit(url)
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in SIZE_PARAMETERS
    ]
    path = SIZE_SUFFIX.sub("", _single_resolution_path(parsed.path))
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, urllib.parse.urlencode(query), "")
    ).rstrip("?&")


def download_variant(url: str, target_width: int) -> str:
    """Попросить у известных CDN картинку нужной ширины."""
    parsed = urllib.parse.urlsplit(url)
    path = SIZE_SUFFIX.sub("", parsed.path)
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in SIZE_PARAMETERS
    ]
    existing_size = next(
        (key for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
         if key.lower() in SIZE_PARAMETERS),
        None,
    )
    if existing_size:
        query.append((existing_size, str(target_width)))
    elif "zara.net" in parsed.netloc:
        query.append(("w", str(target_width)))
    elif "/cdn/shop" in path or "shopify" in parsed.netloc:
        query.append(("width", str(target_width)))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, path, urllib.parse.urlencode(query), parsed.fragment)
    )
