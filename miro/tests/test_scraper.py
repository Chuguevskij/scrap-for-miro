import unittest

from scraper.crawler import Scraper
from scraper.extractors import parse_html_images, parse_json_ld_products, parse_title
from scraper.filters import select_images
from scraper.fetcher import PageFetcher
from scraper.models import Page
from scraper.urls import download_variant, normalized_image_key


class FakeFetcher:
    """Фиктивный fetcher, чтобы тесты не зависели от сети."""

    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url):
        return self.pages[url]


class ScraperTests(unittest.TestCase):
    def test_normalized_keys_remove_cdn_sizes(self):
        first = "https://cdn.test/shoe_800x1000.jpg?w=800&utm_source=page"
        second = "https://cdn.test/shoe_800x1000.jpg?width=1200&utm_source=page"

        self.assertEqual(normalized_image_key(first), normalized_image_key(second))

    def test_html_images_support_lazy_loading_and_srcset(self):
        page = """
        <html><head><title>Model | Shop</title></head><body>
          <img src="/small.jpg" srcset="/small.jpg 400w, /large.jpg 1200w">
          <img data-src="//cdn.test/photo.jpg?w=800">
          <img src="/logo.svg">
        </body></html>
        """

        images = parse_html_images(page, "https://shop.test/catalog/item")

        self.assertEqual(images[0].url, "https://shop.test/large.jpg")
        self.assertIn("https://cdn.test/photo.jpg?w=800", [image.url for image in images])

    def test_json_ld_catalog_is_preferred(self):
        page = """
        <script type="application/ld+json">
        {"itemListElement": [
          {"item": {"@type": "Product", "name": "One", "url": "/products/one"}},
          {"item": {"@type": "Product", "name": "Two", "url": "/products/two"}}
        ]}
        </script>
        <a href="/products/wrong">Не должен быть выбран</a>
        """

        products = parse_json_ld_products(page, "https://shop.test/catalog")

        self.assertEqual([product.title for product in products], ["One", "Two"])

    def test_title_does_not_include_following_page_text(self):
        page = "<title>Product page</title><body>Apple PayGoogle Pay</body>"

        self.assertEqual(parse_title(page), "Product page")

    def test_embedded_product_gallery_is_preferred_over_page_images(self):
        page = """
        <img src="https://cdn.test/logo.png">
        <script>window.product = {"img":"https://cdn.test/one.jpg", "img":"https://cdn.test/two.jpg"}</script>
        """

        images = select_images(parse_html_images(page, "https://shop.test/item"))

        self.assertEqual([image.source for image in images], ["embedded-json", "embedded-json"])

    def test_catalog_scrape_deduplicates_images_between_products(self):
        catalog_url = "https://shop.test/catalog"
        one_url = "https://shop.test/products/one"
        two_url = "https://shop.test/products/two"
        shared = "https://cdn.test/shared_800x1000.jpg?w=800"
        pages = {
            catalog_url: Page(catalog_url, catalog_url, """
                <title>Catalog</title>
                <script type="application/ld+json">{"itemListElement": [
                  {"item": {"@type": "Product", "name": "One", "url": "/products/one"}},
                  {"item": {"@type": "Product", "name": "Two", "url": "/products/two"}}
                ]}</script>
            """),
            one_url: Page(one_url, one_url, '<title>One</title><img src="%s"><img src="https://cdn.test/one.jpg">' % shared),
            two_url: Page(two_url, two_url, '<title>Two</title><img src="https://cdn.test/shared_1200x1500.jpg?width=1200"><img src="https://cdn.test/two.jpg">'),
        }

        result = Scraper(FakeFetcher(pages)).scrape(catalog_url)

        self.assertEqual(result.page_type, "catalog")
        self.assertEqual([product.title for product in result.products], ["One", "Two"])
        image_urls = [image.url for product in result.products for image in product.images]
        self.assertEqual(image_urls, [shared, "https://cdn.test/one.jpg", "https://cdn.test/two.jpg"])

    def test_download_variant_changes_existing_size_parameter(self):
        url = "https://cdn.test/photo.jpg?w=500&token=abc"

        self.assertEqual(
            download_variant(url, 1500),
            "https://cdn.test/photo.jpg?token=abc&w=1500",
        )


if __name__ == "__main__":
    unittest.main()
