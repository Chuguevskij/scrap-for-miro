#!/usr/bin/env python3
"""Сбор изображений товара и размещение их на доске Miro."""

import argparse
import os
import re
import time
import urllib.parse

try:
    from .config import CONFIG_PATH, load_config
    from .miro_api.auth import get_token, prompt_and_save_token
    from .miro_api.client import MiroClient
    from .placement.anchors import below_right_aligned
    from .placement.layout import MAX_IMAGES_PER_ROW, build_frames_row
    from .scraper.crawler import Scraper
    from .scraper.downloader import ImageDownloader
except ImportError:  # запуск как python3 miro/product_board.py
    from config import CONFIG_PATH, load_config
    from miro_api.auth import get_token, prompt_and_save_token
    from miro_api.client import MiroClient
    from placement.anchors import below_right_aligned
    from placement.layout import MAX_IMAGES_PER_ROW, build_frames_row
    from scraper.crawler import Scraper
    from scraper.downloader import ImageDownloader


OUT_ROOT = os.path.expanduser("~/Downloads/product-board")


def log(message):
    """Печатать сообщение сразу, чтобы был виден прогресс."""
    print(message, flush=True)


def widget_id(value):
    """Из ссылки Miro извлечь id объекта."""
    match = re.search(r"moveToWidget=(\d+)", value or "")
    if match:
        return match.group(1)
    if re.match(r"^\d+$", value or ""):
        return value
    return ""


def slugify(value):
    """Получить безопасное имя каталога из заголовка товара."""
    value = re.sub(r"[^\w\s-]", "", value, flags=re.U).strip()
    return re.sub(r"[\s_]+", " ", value)[:60] or "product"


def scrape_groups(result):
    """Превратить результат скрейпинга в группы «товар -> его картинки»."""
    if result.page_type == "catalog":
        return [
            {"title": product.title or "товар %d" % (index + 1), "images": product.images}
            for index, product in enumerate(result.products)
        ]
    return [{"title": result.title, "images": result.images}]


def scrape_and_download(source, output_dir, target_width, keep_all, limit,
                        max_images=0, max_total=0):
    """Собрать изображения одной ссылки и скачать их отдельными группами."""
    result = Scraper().scrape(source, keep_all=keep_all, limit=limit)
    for warning in result.warnings:
        log("  предупреждение: %s" % warning)
    groups = []
    next_index = 1
    downloaded_total = 0
    downloader = ImageDownloader()
    for number, group in enumerate(scrape_groups(result), 1):
        images = group["images"]
        if max_images:
            images = images[:max_images]
        if max_total:
            images = images[:max(0, max_total - downloaded_total)]
        if not images:
            continue
        directory = os.path.join(output_dir, "%02d_%s" % (number, slugify(group["title"])))
        downloaded, failures = downloader.download(
            images, directory, target_width, next_index
        )
        next_index += len(images)
        downloaded_total += len(downloaded)
        for url, error in failures:
            log("  не скачалось: %s (%s)" % (url, error))
        files = [
            {"path": image.path, "url": image.url, "w": image.width, "h": image.height}
            for image in downloaded
        ]
        if files:
            groups.append({"title": group["title"], "files": files})
        if max_total and downloaded_total >= max_total:
            log("  достигнут предел --max-total %d" % max_total)
            break
    return result.title, groups


def upload_plan(client, plan):
    """Создать фрейм, загрузить в него картинки и подписать группы."""
    frame_id = client.create_frame(
        plan.title,
        plan.x + plan.width / 2,
        plan.y + plan.height / 2,
        plan.width,
        plan.height,
    )
    uploaded = 0
    for image in plan.images:
        item_id = client.upload_image(
            image.file_info,
            image.x,
            image.y,
            image.width,
            frame_id,
            plan.title,
        )
        uploaded += bool(item_id)
    for label in plan.labels:
        client.create_text(label.text, label.dx, label.dy, label.size, parent_id=frame_id)
    return frame_id, uploaded


def build_parser():
    """Создать CLI-парсер."""
    parser = argparse.ArgumentParser(description="product images -> Miro board")
    parser.add_argument("src", nargs="*", help="URL товара, каталога или локальный HTML-файл")
    parser.add_argument("--below", metavar="MIRO_OBJECT_URL",
                        help="разместить блок ниже объекта из ссылки Miro")
    parser.add_argument("--board-id", help="переопределить board_id из конфигурации")
    parser.add_argument("--config", default=CONFIG_PATH, help="путь к JSON с настройками")
    parser.add_argument("--set-token", action="store_true",
                        help="сохранить токен в macOS Keychain скрытым вводом")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать найденные изображения без скачивания и Miro")
    parser.add_argument("--no-upload", action="store_true", help="скачать изображения без Miro")
    parser.add_argument("--keep-all", action="store_true", help="не отбрасывать служебные изображения")
    parser.add_argument("--limit", type=int, default=0, metavar="N",
                        help="не более N товаров из каталога")
    parser.add_argument("--max-images", type=int, default=0, metavar="N",
                        help="не более N картинок на товар (по умолчанию без предела)")
    parser.add_argument("--max-total", type=int, default=0, metavar="N",
                        help="не более N картинок всего за запуск (по умолчанию без предела)")
    parser.add_argument("--cols", type=int, default=None,
                        help="картинок в ряду (максимум %d)" % MAX_IMAGES_PER_ROW)
    parser.add_argument("--size", type=int, default=None, help="ширина картинки на доске")
    parser.add_argument("--w", type=int, default=None, help="ширина скачиваемого изображения")
    parser.add_argument("--frame-gap", type=int, default=400,
                        help="горизонтальный отступ между фреймами")
    return parser


def main(argv=None):
    """Выполнить scraping, скачивание и загрузку: на каждую ссылку — свой фрейм."""
    args = build_parser().parse_args(argv)
    if args.set_token:
        prompt_and_save_token()
        log("токен сохранён в macOS Keychain")
        return
    if not args.src:
        raise SystemExit("укажи URL товара или каталога, либо используй --set-token")

    config = load_config(args.config)
    board_id = args.board_id or config.get("board_id", "")
    board_url = config.get("board_url", "")
    target_width = args.w or config.get("w", 1500)
    image_size = args.size or config.get("size", 480)
    columns = args.cols or config.get("cols") or MAX_IMAGES_PER_ROW
    root = os.path.join(OUT_ROOT, time.strftime("%Y-%m-%d %H-%M"))

    if args.dry_run:
        for source in args.src:
            result = Scraper().scrape(source, keep_all=args.keep_all, limit=args.limit)
            log("«%s» [%s]" % (result.title[:80], source))
            for group in scrape_groups(result):
                total = len(group["images"])
                shown = min(total, args.max_images) if args.max_images else total
                log("  %-70s %d%s" % (
                    group["title"][:70], shown,
                    " (всего найдено %d)" % total if shown != total else "",
                ))
            for warning in result.warnings:
                log("  предупреждение: %s" % warning)
        log("--dry-run: файлы не скачивались, Miro не изменялся")
        return

    frames = []
    budget = args.max_total
    for number, source in enumerate(args.src, 1):
        log("[%.0f/%d] %s" % (number, len(args.src), source))
        title, groups = scrape_and_download(
            source,
            os.path.join(root, "%02d_%s" % (number, slugify(source))),
            target_width,
            args.keep_all,
            args.limit,
            max_images=args.max_images,
            max_total=budget,
        )
        count = sum(len(group["files"]) for group in groups)
        if budget:
            budget -= count
        log("  «%s»: %d групп, %d изображений" % (title[:60], len(groups), count))
        if groups:
            frames.append({"title": title, "groups": groups})
        if budget is not None and args.max_total and budget <= 0:
            log("достигнут предел --max-total %d, остальные ссылки пропускаем" % args.max_total)
            break
    if not frames:
        raise SystemExit("не удалось скачать ни одного изображения")
    log("файлы сохранены в %s" % root)
    if args.no_upload:
        return

    token = get_token()
    if not token:
        raise SystemExit(
            "не найден Miro token: задай MIRO_TOKEN или выполни python3 product_board.py --set-token"
        )
    if not board_id:
        raise SystemExit("не указан board_id: добавь его в %s или передай --board-id" % args.config)
    client = MiroClient(token, board_id)

    single_width = min(columns, MAX_IMAGES_PER_ROW) * (image_size + 40) - 40 + 120
    reference_url = args.below or board_url
    if reference_url and widget_id(reference_url):
        reference = client.get_item(widget_id(reference_url))
        if reference is None:
            raise SystemExit("объект Miro из MIRO_BOARD_URL/--below не найден")
        left, top = below_right_aligned(client.box(reference), single_width)
    else:
        left, top = 0, 0
        log("moveToWidget не указан, блоки будут размещены около начала доски")

    plans = build_frames_row(
        frames, left, top, image_size, columns,
        frame_gap=args.frame_gap,
    )
    total = 0
    for plan in plans:
        frame_id, uploaded = upload_plan(client, plan)
        total += uploaded
        log("готово: «%s» загружено %d из %d, frame_id=%s" % (
            plan.title[:60], uploaded, len(plan.images), frame_id))
    log("итого: %d фреймов, %d изображений" % (len(plans), total))


if __name__ == "__main__":
    main()
