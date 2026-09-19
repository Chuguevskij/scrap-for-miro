"""Простая расчётная раскладка изображений во фреймах."""

from .models import FramePlan, ImagePlacement, TextPlacement

MAX_IMAGES_PER_ROW = 20
ROW_HEIGHT_RESERVE = 70


def _row_heights(files, columns, size, gap):
    """Высота каждого ряда сетки: самый высокий экземпляр в ряду."""
    rows = [files[index:index + columns] for index in range(0, len(files), columns)]
    heights = []
    for row in rows:
        row_heights = [size * (item.get("h", 0) / item.get("w", 1)) for item in row]
        heights.append(max(row_heights or [size * 1.25]))
    return list(zip(rows, heights))


def build_frame_plan(title, files, left, top, size=480, columns=MAX_IMAGES_PER_ROW, gap=40, padding=60):
    """Разместить изображения сеткой и вычислить высоту фрейма."""
    if not files:
        return None
    columns = max(1, min(columns, MAX_IMAGES_PER_ROW))
    frame_width = columns * (size + gap) - gap + 2 * padding
    placements = []
    y = padding + ROW_HEIGHT_RESERVE
    for row, row_height in _row_heights(files, columns, size, gap):
        for column, item in enumerate(row):
            placements.append(ImagePlacement(
                item,
                padding + column * (size + gap) + size / 2,
                y + row_height / 2,
                size,
            ))
        y += row_height + gap
    return FramePlan(title, left, top, frame_width, y - gap + padding, tuple(placements))


def build_group_frame_plan(title, groups, left, top, size=480, columns=MAX_IMAGES_PER_ROW,
                           gap=40, group_gap=140, padding=60):
    """Собрать один фрейм с группами: группы отделены увеличенным отступом."""
    groups = [group for group in groups if group.get("files")]
    if not groups:
        return None
    columns = max(1, min(columns, MAX_IMAGES_PER_ROW))
    frame_width = columns * (size + gap) - gap + 2 * padding
    placements = []
    labels = []
    y = padding
    for group in groups:
        if group.get("title"):
            labels.append(TextPlacement(group["title"], padding + 4, y + 24, 40))
        y += ROW_HEIGHT_RESERVE
        for row, row_height in _row_heights(group["files"], columns, size, gap):
            for column, item in enumerate(row):
                placements.append(ImagePlacement(
                    item,
                    padding + column * (size + gap) + size / 2,
                    y + row_height / 2,
                    size,
                ))
            y += row_height + gap
        y += group_gap
    return FramePlan(
        title, left, top, frame_width, y - group_gap + padding,
        tuple(placements), tuple(labels),
    )


def build_frames_row(frames, left, top, size=480, columns=MAX_IMAGES_PER_ROW,
                     gap=40, group_gap=140, padding=60, frame_gap=400):
    """Разложить фреймы по одному фрейму на ссылку в ряд по горизонтали."""
    plans = []
    x = left
    for frame in frames:
        plan = build_group_frame_plan(
            frame["title"], frame["groups"], x, top, size, columns, gap, group_gap, padding
        )
        if plan is None:
            continue
        plans.append(plan)
        x += plan.width + frame_gap
    return plans
