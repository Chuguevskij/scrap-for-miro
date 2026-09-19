"""Извлечение заголовков, ссылок на товары и картинок из HTML."""

import html
import json
import re
import urllib.parse
from html.parser import HTMLParser

from .models import ImageCandidate, ProductRef
from .urls import absolute_url


IMAGE_ATTRIBUTES = ("src", "data-src", "data-original", "data-lazy-src", "data-ks-lazyload")
SRCSET_ATTRIBUTES = ("srcset", "data-srcset", "data-lazy-srcset")
IMAGE_PATH = re.compile(r"\.(?:jpe?g|png|webp)(?:$|[?#])", re.I)
PRODUCT_HREF = re.compile(
    r"(?:^|/)(?:products?|pd|dp)/[a-z0-9][^\"'?\#]*|-p\d{6,}\.html", re.I
)


def best_srcset(value: str) -> str | None:
    """Взять самый большой вариант из srcset."""
    candidates = []
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        width = int(re.match(r"(\d+)", bits[1]).group(1)) if len(bits) > 1 and re.match(r"\d+", bits[1]) else 0
        candidates.append((width, bits[0]))
    return max(candidates, default=(0, None))[1]


class HtmlImageParser(HTMLParser):
    """Собирает картинки из стандартных и lazy-loading атрибутов.

    Отдельно помечает картинки внутри блоков галереи: на многих витринах фото
    товара дублируются в миниатюрах, зуме и похожих товарах, и только галерея
    даёт ровно тот набор ракурсов, который показывает сайт.
    """

    GALLERY = re.compile(
        r"gallery|slider|swiper|slick|product-images|product-photo|product-preview|zoom", re.I
    )
    OUTSIDE = re.compile(
        r"nav|header|footer|menu|breadcrumb|sidebar|filter|form|widget|recommend|related|similar",
        re.I,
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.images: list[tuple[str, str]] = []
        self._in_title = False
        self._in_gallery: list[bool] = []

    def _record(self, url, source):
        gallery = bool(self._in_gallery and self._in_gallery[-1])
        self.images.append((url, "gallery" if gallery else source))

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "") + " " + (attributes.get("id") or "")
        inside = (
            False
            if self.OUTSIDE.search(classes)
            else bool(self._in_gallery and self._in_gallery[-1]) or bool(self.GALLERY.search(classes))
        )
        self._in_gallery.append(inside)
        if tag == "title":
            self._in_title = True
        if tag == "img":
            for key in SRCSET_ATTRIBUTES:
                if attributes.get(key) and (url := best_srcset(attributes[key])):
                    self._record(url, "srcset")
            for key in IMAGE_ATTRIBUTES:
                if attributes.get(key):
                    self._record(attributes[key], key)
            if attributes.get("data-lazy"):
                self._record(attributes["data-lazy"], "data-lazy")
        if tag == "source":
            for key in SRCSET_ATTRIBUTES[:2]:
                if attributes.get(key) and (url := best_srcset(attributes[key])):
                    self._record(url, "source")
        if tag == "link" and "image" in (attributes.get("as") or "") and attributes.get("href"):
            self._record(attributes["href"], "preload")
        if tag == "meta" and attributes.get("property", "").lower() in {"og:image", "og:image:url"}:
            if attributes.get("content"):
                self._record(attributes["content"], "og:image")
        for url in re.findall(r"url\(['\"]?([^'\")]+)", attributes.get("style") or ""):
            self._record(url, "style")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self._in_gallery:
            self._in_gallery.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title += data


class ProductLinkParser(HTMLParser):
    """Ищет товарные ссылки внутри блоков карточек, избегая меню и футера."""

    INSIDE = re.compile(r"product|card|grid|item|tile|listing|gallery|swiper-slide", re.I)
    OUTSIDE = re.compile(
        r"nav|header|footer|menu|breadcrumb|sidebar|filter|form|widget|recommend|related", re.I
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack: list[bool] = []
        self._link: list[str] | None = None
        self.found: list[ProductRef] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "") + " " + (attributes.get("id") or "")
        inside = False if self.OUTSIDE.search(classes) else bool(self._stack and self._stack[-1]) or bool(self.INSIDE.search(classes))
        self._stack.append(inside)
        if tag == "a" and inside:
            href = attributes.get("href") or ""
            if PRODUCT_HREF.search(href):
                self._link = [href, ""]

    def handle_endtag(self, tag):
        if tag == "a" and self._link:
            href, title = self._link
            key = href.split("#", 1)[0].split("?", 1)[0]
            if key not in self._seen:
                self._seen.add(key)
                self.found.append(ProductRef(key, re.sub(r"\s+", " ", title).strip()))
            self._link = None
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._link is not None and len(self._link[1]) < 120:
            self._link[1] += data


def parse_title(page_html: str) -> str:
    # Берём только содержимое title: на некоторых больших страницах HTMLParser
    # продолжает считать текст частью title после повреждённой разметки.
    match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", page_html, re.I | re.S)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return re.split(r"[|]", title, maxsplit=1)[0].strip()[:80]


def parse_product_title(page_html: str) -> str:
    """Название товара: h1 точнее, чем title, где обычно ещё и цена с магазином."""
    for match in re.finditer(r"<h1\b[^>]*>(.*?)</h1\s*>", page_html, re.I | re.S):
        text = re.sub(r"<[^>]+>", " ", match.group(1))
        text = re.sub(r"\s+", " ", html.unescape(text)).strip(" -–—|·")
        if len(text) > 2:
            return text[:70].strip()
    return parse_title(page_html)


def parse_html_images(page_html: str, base_url: str) -> list[ImageCandidate]:
    parser = HtmlImageParser()
    parser.feed(page_html)
    raw_images = list(parser.images)
    escaped_html = page_html.replace(r"\/", "/")
    raw_images.extend(
        (url, "raw-html")
        for url in re.findall(
            r"https?://[^\s\"'<>()]+?\.(?:jpe?g|png|webp)(?:\?[^\s\"'<>()]*)?",
            escaped_html,
            re.I,
        )
    )
    # Некоторые конструкторы (в том числе Tilda) держат галерею товара
    # внутри JSON в HTML, а не в атрибутах img.
    raw_images.extend(
        (url, "embedded-json")
        for url in re.findall(
            r"[\"']img[\"']\s*:\s*[\"'](https?:\\?/\\?/[^\"']+?\.(?:jpe?g|png|webp))(?:[?][^\"']*)?[\"']",
            escaped_html,
            re.I,
        )
    )
    result = []
    for position, (raw_url, source) in enumerate(raw_images):
        url = absolute_url(html.unescape(raw_url).strip(" \\'\""), base_url)
        if url.startswith(("http://", "https://")) and (
            source != "src" or IMAGE_PATH.search(urllib.parse.urlsplit(url).path)
        ):
            result.append(ImageCandidate(url, position, source))
    return result


def parse_json_ld_products(page_html: str, base_url: str) -> list[ProductRef]:
    """Извлечь ItemList из JSON-LD, если сайт его публикует."""
    result = []
    seen = set()
    blocks = re.findall(r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", page_html, re.I | re.S)
    for block in blocks:
        try:
            data = json.loads(html.unescape(block))
        except (TypeError, ValueError):
            continue
        groups = []
        if isinstance(data, dict) and data.get("itemListElement"):
            groups.append(data["itemListElement"])
        if isinstance(data, dict):
            groups.extend(item.get("itemListElement", []) for item in data.get("@graph", []) if isinstance(item, dict))
        for items in groups:
            for item in items:
                product = item.get("item") if isinstance(item, dict) else None
                if not isinstance(product, dict) or product.get("@type") != "Product":
                    continue
                url = product.get("url") or ((product.get("offers") or {}).get("url") if isinstance(product.get("offers"), dict) else None)
                if not url:
                    continue
                url = absolute_url(url, base_url).split("#", 1)[0]
                if url not in seen:
                    seen.add(url)
                    result.append(ProductRef(url, html.unescape(product.get("name") or "").strip()))
    return result
