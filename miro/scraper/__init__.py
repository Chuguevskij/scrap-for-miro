"""Сбор данных с товарных страниц и каталогов."""

from .crawler import Scraper
from .downloader import DownloadedImage, ImageDownloader
from .fetcher import HttpPageFetcher, LocalFileFetcher
from .models import ImageCandidate, Page, Product, ProductRef, ScrapeResult

__all__ = [
    "HttpPageFetcher",
    "DownloadedImage",
    "ImageCandidate",
    "ImageDownloader",
    "LocalFileFetcher",
    "Page",
    "Product",
    "ProductRef",
    "ScrapeResult",
    "Scraper",
]
