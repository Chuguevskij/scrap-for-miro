"""Небольшие модели, которыми обмениваются этапы скрейпера."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Page:
    """Полученная HTML-страница и URL после редиректов."""

    url: str
    final_url: str
    html: str


@dataclass(frozen=True)
class ImageCandidate:
    """Кандидат на картинку до фильтрации и скачивания."""

    url: str
    position: int
    source: str = "html"


@dataclass(frozen=True)
class ProductRef:
    """Ссылка на товар, найденная на странице каталога."""

    url: str
    title: str


@dataclass
class Product:
    """Товар и найденные на его странице ракурсы."""

    url: str
    title: str
    images: list[ImageCandidate] = field(default_factory=list)


@dataclass
class ScrapeResult:
    """Итог обхода исходной ссылки."""

    url: str
    title: str
    page_type: str
    products: list[Product] = field(default_factory=list)
    images: list[ImageCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
