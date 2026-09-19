"""Модели плана размещения, не зависящие от Miro API."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ImagePlacement:
    """Координаты картинки относительно верхнего левого угла фрейма."""

    file_info: dict
    x: float
    y: float
    width: float


@dataclass(frozen=True)
class TextPlacement:
    """Подпись группы: смещение от верхнего левого угла фрейма, как у картинок."""

    text: str
    dx: float
    dy: float
    size: int = 40


@dataclass(frozen=True)
class FramePlan:
    """План одного фрейма, его картинок и подписей групп."""

    title: str
    x: float
    y: float
    width: float
    height: float
    images: tuple[ImagePlacement, ...]
    labels: tuple[TextPlacement, ...] = field(default_factory=tuple)
