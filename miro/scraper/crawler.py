"""Координация обхода страницы каталога и товарных страниц."""

from .extractors import parse_product_title
from .fetcher import HttpPageFetcher, LocalFileFetcher, PageFetcher
from .filters import unique_images
from .models import Product, ScrapeResult
from .sources import discover_images, discover_products
from .urls import normalized_image_key
import re


PRODUCT_PAGE_URL = re.compile(r"/(?:products?|pd|dp)/[^/?#]+/?$|-p\d{6,}\.html", re.I)


class Scraper:
    """Оркестратор: загрузить страницу, определить её тип и собрать картинки."""

    def __init__(self, fetcher: PageFetcher | None = None):
        self.fetcher = fetcher

    def scrape(self, url: str, keep_all: bool = False, limit: int = 0) -> ScrapeResult:
        is_local = not url.startswith(("http://", "https://"))
        fetcher = self.fetcher or (LocalFileFetcher() if is_local else HttpPageFetcher())
        page = fetcher.fetch(url)
        title = parse_product_title(page.html) or page.final_url
        refs = [] if PRODUCT_PAGE_URL.search(page.final_url) else discover_products(page, fetcher)
        if not refs:
            return ScrapeResult(
                url=url,
                title=title,
                page_type="product",
                images=discover_images(page, fetcher, keep_all),
            )

        products = []
        result_warnings = []
        for ref in refs[:limit or None]:
            try:
                product_page = fetcher.fetch(ref.url)
                product_title = parse_product_title(product_page.html) or ref.title or title
                products.append(Product(
                    ref.url,
                    product_title,
                    discover_images(product_page, fetcher, keep_all),
                ))
            except (OSError, RuntimeError, ValueError) as exc:
                # Одна сломанная карточка не должна прерывать весь каталог.
                products.append(Product(ref.url, ref.title, []))
                warning = "%s: %s" % (ref.url, exc)
                result_warnings.append(warning)

        # Одна и та же картинка может встретиться в нескольких карточках.
        # Удаляем такие повторы после обхода, сохраняя принадлежность первой карточке.
        seen_images = set()
        for product in products:
            filtered = []
            for image in unique_images(product.images):
                key = normalized_image_key(image.url)
                if key in seen_images:
                    continue
                seen_images.add(key)
                filtered.append(image)
            product.images = filtered
        return ScrapeResult(
            url=url,
            title=title,
            page_type="catalog",
            products=products,
            warnings=result_warnings,
        )
