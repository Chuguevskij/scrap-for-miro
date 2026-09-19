"""Источники данных для разных форматов сайтов."""

import json
import re
import urllib.parse

from .extractors import parse_html_images, parse_json_ld_products, ProductLinkParser
from .fetcher import PageFetcher
from .filters import select_images
from .models import ImageCandidate, Page, ProductRef
from .urls import absolute_url


def discover_products(page: Page, fetcher: PageFetcher) -> list[ProductRef]:
    """Попробовать источники каталога в порядке от самых точных к эвристическим."""
    products = parse_json_ld_products(page.html, page.final_url)
    if products:
        return products

    collection = _shopify_collection_url(page.final_url)
    if collection:
        try:
            data = json.loads(fetcher.fetch(collection + "/products.json?limit=250").html)
            products = [
                ProductRef(
                    absolute_url("/products/" + item["handle"], page.final_url),
                    item.get("title", "").strip(),
                )
                for item in data.get("products", [])
                if item.get("handle")
            ]
            if products:
                return products
        except (KeyError, TypeError, ValueError, OSError):
            pass

    parser = ProductLinkParser()
    parser.feed(page.html)
    return [
        ProductRef(absolute_url(ref.url, page.final_url), ref.title or _title_from_url(ref.url))
        for ref in parser.found
    ]


def discover_images(page: Page, fetcher: PageFetcher, keep_all: bool = False) -> list[ImageCandidate]:
    """Получить картинки товара: сначала Shopify JSON, затем HTML."""
    shopify_images = _shopify_product_images(page.final_url, fetcher)
    if shopify_images:
        return select_images(shopify_images, keep_all=True)
    return select_images(parse_html_images(page.html, page.final_url), keep_all)


def _shopify_product_images(url: str, fetcher: PageFetcher) -> list[ImageCandidate]:
    try:
        page = fetcher.fetch(url.rstrip("/") + ".json")
        data = json.loads(page.html).get("product") or {}
    except (KeyError, OSError, TypeError, ValueError):
        return []
    result = []
    for index, image in enumerate(data.get("images") or []):
        raw_url = image.get("src") if isinstance(image, dict) else image
        if raw_url:
            result.append(ImageCandidate(absolute_url(raw_url, url), index, "shopify-json"))
    return result


def _shopify_collection_url(url: str) -> str | None:
    match = re.match(r"(https?://[^/]+/collections/[^/?#]+)", url)
    return match.group(1) if match else None


def _title_from_url(url: str) -> str:
    tail = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    return tail.replace("-", " ").upper()
