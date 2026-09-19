"""Выбор точки начала размещения на доске."""


def below_right_aligned(item, frame_width: float, gap: float = 400):
    """Вернуть левый верхний угол блока под объектом с правым выравниванием."""
    left, _, right, bottom = item
    return right - frame_width, bottom + gap
