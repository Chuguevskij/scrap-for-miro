#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Картинки с товарной страницы -> доска Miro, сеткой в новом фрейме.

Только stdlib (Python 3.9+). Ничего ставить не нужно.

    python3 miro_obuv.py https://сайт/товар            # скачать и залить на доску (5 картинок в ряд)
    python3 miro_obuv.py https://сайт/каталог --below "miro.com/...moveToWidget=123..."
                                                       # снизу от объекта, партии вправо
    python3 miro_obuv.py https://сайт/каталог --skip-existing   # докачать после обрыва
    python3 miro_obuv.py https://сайт/товар --dry-run  # показать, что найдено, доску не трогать
    python3 miro_obuv.py https://сайт/товар --paste     # открыть HTML-сетку для Ctrl+C/Ctrl+V
"""

import argparse
import html
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from scraper.fetcher import HttpPageFetcher, LocalFileFetcher
    from scraper.models import ImageCandidate, Page
    from scraper.sources import discover_products
    from scraper.crawler import Scraper
    from scraper.downloader import ImageDownloader
    from scraper.downloader import image_dimensions
except ModuleNotFoundError:  # запуск через корневой wrapper как пакет miro
    from miro.scraper.fetcher import HttpPageFetcher, LocalFileFetcher
    from miro.scraper.models import ImageCandidate, Page
    from miro.scraper.sources import discover_products
    from miro.scraper.crawler import Scraper
    from miro.scraper.downloader import ImageDownloader
    from miro.scraper.downloader import image_dimensions

CONFIG_PATH = os.path.expanduser("~/Library/Application Support/miro-obuv/config.json")
OUT_ROOT = os.path.expanduser("~/Downloads/обувь")
API = "https://api.miro.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------- конфиг

def load_config():
    cfg = {"token": "", "board_id": "", "w": 1500, "cols": 5, "size": 480}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf8") as f:
                cfg.update(json.load(f))
        except Exception as exc:
            log("внимание: не смог прочитать конфиг (%s), беру значения по умолчанию" % exc)
    return cfg


# ------------------------------------------------------- получение страницы

def fetch(url):
    """Совместимый адаптер старого CLI к новому загрузчику страниц."""
    page = HttpPageFetcher().fetch(url)
    return page.html, page.final_url


def link_name(href):
    """Название по слагу ссылки: /products/alban-bear-shoes-x -> ALBAN BEAR SHOES X."""
    tail = urllib.parse.urlparse(href).path.rstrip("/").split("/")[-1]
    tail = re.sub(r"-p\d+\.html$|-\.html$|\.html$", "", tail, flags=re.I)
    return tail.replace("-", " ").strip().upper()


def catalog_items(page, base_url):
    """Адаптер старого CLI к новому слою обнаружения товаров."""
    fetcher = HttpPageFetcher() if base_url.startswith("http") else LocalFileFetcher()
    refs = discover_products(Page(base_url, base_url, page), fetcher)
    return [(ref.title or link_name(ref.url), ref.url) for ref in refs]


def slugify(name):
    s = re.sub(r"[^\w\s\-]", "", name, flags=re.U).strip()
    s = re.sub(r"[\s_]+", " ", s)
    return s[:44] or "модель"


def normalize_source(value):
    """Добавить HTTPS к домену, если пользователь вставил ссылку без схемы."""
    if re.match(r"^https?://", value, re.I) or os.path.exists(value):
        return value
    if re.match(r"^[A-Za-z0-9.-]+(?:/|$)", value) and "." in value.split("/", 1)[0]:
        return "https://" + value
    return value


# --------------------------------------------------------------- скачивание

def download(urls, out_dir, target_w, start=1):
    candidates = [ImageCandidate(url, position) for url, position in urls]
    downloaded, fails = ImageDownloader().download(candidates, out_dir, target_w, start)
    files = []
    for number, image in enumerate(downloaded, start):
        size = os.path.getsize(image.path)
        files.append({"path": image.path, "url": image.url, "w": image.width, "h": image.height})
        log("  %02d  %5d KB  %sx%s" %
            (number, size // 1024, image.width or "?", image.height or "?"))
    if fails:
        log("\nне скачалось: %d шт (подробности в %s)" % (len(fails), os.path.join(OUT_ROOT, ".log")))
        with open(os.path.join(OUT_ROOT, ".log"), "a", encoding="utf8") as f:
            for u, e in fails:
                f.write("%s\t%s\t%s\n" % (time.strftime("%F %T"), u, e))
    return files


# ----------------------------------------------------------------- Miro API

class Miro:
    def __init__(self, token, board_id):
        self.token = token
        self.bid = urllib.parse.quote(board_id, safe="")

    def call(self, method, path, body=None, raw=None, ctype="application/json", soft=False,
             timeout=90, tries=5):
        """Ретраит и HTTP-ошибки (429/5xx), и сетевые зависания (TimeoutError/URLError):
        доска большая, Miro отвечает медленно, один таймаут не должен ронять весь прогон."""
        for attempt in range(1, tries + 1):
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
            req = urllib.request.Request(API + "/v2" + path, data=data, method=method,
                                         headers={"Authorization": "Bearer " + self.token,
                                                  "Content-Type": ctype})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf8", "replace")
                if exc.code == 429:
                    pause = float(exc.headers.get("Retry-After") or 2 * attempt)
                    log("  Miro просит паузу, жду %.0f c" % pause)
                    time.sleep(pause)
                    continue
                if exc.code >= 500 and attempt < tries:
                    log("  Miro вернул %d (сбой на их стороне), повторяю ..." % exc.code)
                    time.sleep(2 * attempt)
                    continue
                if exc.code in (401, 403):
                    raise SystemExit("Miro не пускает (HTTP %d). Проверь, что токен свежий и у "
                                     "приложения стоят права boards:read и boards:write.\n%s"
                                     % (exc.code, text[:300]))
                if exc.code == 404:
                    if soft:
                        return 404, text.encode()
                    raise SystemExit("Miro не нашёл доску/объект (HTTP 404). Верно ли указан board_id и та "
                                     "ли это команда, куда установлено приложение?\n%s" % text[:300])
                raise SystemExit("Miro вернул HTTP %d: %s" % (exc.code, text[:400]))
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, OSError) as exc:
                if attempt == tries:
                    raise SystemExit("нет связи с Miro после %d попыток: %s" % (tries, exc))
                log("  связь с Miro оборвалась (%s), повторяю попытку %d/%d ..."
                    % (type(exc).__name__, attempt + 1, tries))
                time.sleep(3 * attempt)
        raise SystemExit("Miro слишком часто отказывает (429), попробуй через минуту")

    def anchor(self):
        """Точка старта нового блока: справа от рабочего ряда фреймов, на его уровне.
        Ориентир берём не по самому дальнему фрейму на доске (иногда кто-то утаскивает
        копию в пустоту на x=100000, и тогда новый блок улетел бы в никуда), а по
        полосе, где лежит большинство фреймов.
        Нюанс Miro: position фрейма = его ЦЕНТР (origin=center)."""
        fr = self.all_items("frame")
        if not fr:
            return 0.0, 0.0
        ys = sorted(f["position"]["y"] for f in fr)
        band = ys[len(ys) // 2]
        near = [f for f in fr if abs(f["position"]["y"] - band) <= 3000]
        right = max(f["position"]["x"] + f["geometry"].get("width", 0) / 2.0 for f in near)
        tops = sorted(f["position"]["y"] - f["geometry"].get("height", 0) / 2.0 for f in near)
        return right + 500, tops[len(tops) // 2]      # общий ВЕРХ рабочего ряда

    def all_items(self, itype, cap=1500):
        """Все объекты доски данного типа. Miro иногда игнорирует offset и отвечает тем же
        набором, поэтому идём до тех пор, пока страница даёт ХОТЬ ОДИН новый id."""
        out, seen, off = [], set(), 0
        while off < cap:
            _, body = self.call("GET", "/boards/%s/items?limit=50&type=%s&offset=%d"
                                % (self.bid, itype, off), timeout=120)
            got = json.loads(body).get("data", [])
            fresh = [x for x in got if x["id"] not in seen]
            if not fresh:
                break
            seen.update(x["id"] for x in fresh)
            out += fresh
            off += len(got)
        return out

    def item(self, item_id):
        st, body = self.call("GET", "/boards/%s/items/%s" % (self.bid, item_id), soft=True)
        if st == 404:
            return None
        return json.loads(body)

    def any_frame(self):
        """Запасной репер: середина ряда фреймов на доске, если указанный объект не найден."""
        fr = self.all_items("frame", cap=200)
        return fr[len(fr) // 2] if fr else None

    def box(self, it):
        """(left, top, right, bottom) объекта в абсолютных координатах доски.
        Нюанс Miro: position = ЦЕНТР (origin=center)."""
        p, g = it["position"], it.get("geometry", {})
        w, h = g.get("width", 0), g.get("height", 0)
        return (p["x"] - w / 2.0, p["y"] - h / 2.0, p["x"] + w / 2.0, p["y"] + h / 2.0)

    def create_frame(self, title, x, y, w, h):
        _, body = self.call("POST", "/boards/%s/frames" % self.bid,
                            {"data": {"title": title, "format": "custom", "type": "freeform"},
                             "position": {"x": x, "y": y},
                             "geometry": {"width": w, "height": h}})
        return json.loads(body)["id"]

    def create_group(self, item_ids, title=""):
        """Группа объектов (фреймов/текстов) - способ сохранить иерархию: вложенный фрейм
        в фрейм REST не пускает (400), а группа принимает id фреймов. None - если не вышло
        (иерархия приятна, но не обязательна: сетка от этого не страдает)."""
        ids = [int(i) for i in item_ids if i and str(i).isdigit()]
        if len(ids) < 2:
            return None
        try:
            _, body = self.call("POST", "/boards/%s/groups" % self.bid,
                                {"data": {"items": ids}}, soft=True)
            gid = json.loads(body).get("id")
            log("  группа «%s»: %d фреймов (%s)" % (title or "без названия", len(ids), gid))
            return gid
        except Exception as exc:
            log("  группу собрать не удалось (не страшно): %s" % str(exc)[:160])
            return None

    def create_text(self, content, x, y, size=32, parent_id=None):
        """Текст на доске: с parent_id - ВНУТРИ фрейма, x,y от его верхнего левого угла;
        без него - абсолютные координаты (подпись над рядом фреймов)."""
        body = {"data": {"content": "<span style=\"font-size:%dpx\">%s</span>"
                            % (size, html.escape(content))},
                "position": {"x": x, "y": y}}
        if parent_id:
            body["parent"] = {"id": parent_id}
        try:
            _, body = self.call("POST", "/boards/%s/texts" % self.bid, body, soft=True)
            return json.loads(body).get("id")
        except Exception:
            return None

    def patch_frame(self, frame_id, title=None, w=None, h=None):
        """Правит высоту фрейма под реальный размер сетки, не двигая его ВЕРХНИЙ КРАЙ:
        вместе с геометрией передвигаем и центр (y = top + h/2)."""
        cur = self.item(frame_id)
        if cur is None:
            return
        p = cur["position"]
        g = cur.get("geometry", {})
        body = {"geometry": {"width": w or g.get("width", 0), "height": h or g.get("height", 0)}}
        if title:
            body["data"] = {"title": title}
        body["position"] = {"x": p["x"],
                            "y": p["y"] - g.get("height", 0) / 2.0 + body["geometry"]["height"] / 2.0}
        try:
            self.call("PATCH", "/boards/%s/frames/%s" % (self.bid, frame_id), body)
        except SystemExit as exc:
            log("  фрейм не удалось подогнать по высоте: %s" % str(exc)[:160])

    def upload_image(self, item, x, y, width, parent_id, alt):
        """Загружает картинку. Возвращает id созданного объекта или None (ошибка не фатальна:
        одна неудачная загрузка не должна ронять всю партию)."""
        boundary = "----miroobuv%d" % int(time.time() * 1000)
        if parent_id:
            # внутри фрейма x,y считаем от ВЕРХНЕГО ЛЕВОГО УГЛА фрейма; origin=center
            # (без relativeTo=parent_top_left Miro понимает x,y как абсолютные - картинка улетит)
            pos = {"x": x, "y": y, "relativeTo": "parent_top_left"}
        else:
            pos = {"x": x, "y": y}
        data = {"title": os.path.basename(item["path"]), "altText": alt[:137],
                "position": pos, "geometry": {"width": width}}
        if parent_id:
            data["parent"] = {"id": parent_id}
        parts = []
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"data\"\r\n"
                      "Content-Type: application/json\r\n\r\n%s\r\n" % (boundary, json.dumps(data))).encode())
        with open(item["path"], "rb") as f:
            blob = f.read()
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"resource\"; filename=\"%s\"\r\n"
                      "Content-Type: image/jpeg\r\n\r\n" % (boundary, os.path.basename(item["path"]))).encode())
        parts.append(blob + b"\r\n")
        parts.append(("--%s--\r\n" % boundary).encode())
        raw = b"".join(parts)
        try:
            status, body = self.call("POST", "/boards/%s/images" % self.bid, raw=raw,
                                     ctype="multipart/form-data; boundary=%s" % boundary,
                                     timeout=180, soft=True)
        except SystemExit as exc:
            log("    загрузка не прошла: %s" % str(exc)[:160])
            return None
        if status != 201:
            log("    загрузка не прошла (HTTP %s): %s" % (status, body[:200]))
            return None
        try:
            iid = json.loads(body).get("id")
        except Exception:
            iid = "?"
        log("    загружено на доску: %s -> id %s" % (os.path.basename(item["path"]), iid))
        return iid


# --------------------------------------------------------------- режим вставки

def paste_page(files, size, cols, title, dest):
    cells = "".join('<img src="file://%s" style="width:%dpx;margin:8px">' % (f["path"], size)
                    for f in files)
    open(dest, "w", encoding="utf8").write(
        "<html><head><meta charset='utf-8'><title>%s</title></head>"
        "<body style='font-family:sans-serif'><h2>%s</h2><div>%s</div></body></html>"
        % (title, title, cells))
    import subprocess
    subprocess.call(["open", dest])
    log("\nОткрыл страницу с картинками в браузере.")
    log("Дальше: Cmd+A, Cmd+C в этой вкладке -> открой доску Miro -> Cmd+V.")


# ----------------------------------------------------------------------- main

def gather_urls(url, keep_all):
    """Адаптер старого CLI к новому скрейперу: файлы пока скачивает старый слой."""
    scraper = Scraper()
    result = scraper.scrape(url, keep_all=keep_all)
    picked = [(image.url, image.position) for image in result.images]
    if result.page_type == "catalog":
        picked = [
            (image.url, image.position)
            for product in result.products
            for image in product.images
        ]
    log("  ракурсов: %d (новый scraper)" % len(picked))
    return result.title, picked


def gather(url, target_w, keep_all, out_dir):
    """Одна страница товара -> (заголовок, файлы). Для режимов без загрузки на доску."""
    title, picked = gather_urls(url, keep_all)
    if not picked:
        return title, []
    return title, download(picked, out_dir, target_w)


def place_stream(m, title, picked, files, out_dir, fx, fy, size, cols, gap, pad, no_frame, target_w):
    """Ряд за рядом: скачали ряд -> сразу залили его в фрейм (не ждём остальные партии).
    fx, fy - ВЕРХНИЙ ЛЕВОЙ УГОЛ блока: все партии прогона делят общий верхний край.
    Возвращает (загружено, всего, ширина_фрейма, id_фрейма)."""
    src = [(None, f) for f in files] if files is not None else [(u, None) for u, _ in picked]
    rows = [src[i:i + cols] for i in range(0, len(src), cols)]
    need = len(src)
    frame_w = cols * (size + gap) - gap + 2 * pad
    ox, oy = (pad, pad + 70) if not no_frame else (fx, fy)
    parent = None
    manifest = {"title": title, "frame_id": None, "images": []}
    uplog = os.path.join(out_dir, "загрузки.log")
    ok, y = 0, oy
    for r, row in enumerate(rows, 1):
        if files is None:
            colidx = {u: c for c, (u, _) in enumerate(row)}
            row_files = download(row, out_dir, target_w, start=(r - 1) * cols + 1)
        else:
            colidx = {f["url"]: c for c, (_, f) in enumerate(row)}
            row_files = [f for _, f in row]
        if not row_files:
            continue
        rh = max([size * (f["h"] / f["w"]) for f in row_files if f.get("w")] or [size * 1.25])
        if parent is None and not no_frame:
            # высота-оценка: все ряды как этот; в конце подгоним PATCH-ем по факту
            est = (pad + 70) + rh * len(rows) + (len(rows) - 1) * gap + pad
            parent = m.create_frame(title, fx + frame_w / 2.0, fy + est / 2.0, frame_w, est)
            manifest["frame_id"] = parent
            log("  фрейм «%s» создан: id %s" % (title[:44], parent))
        for f in row_files:
            c = colidx.get(f["url"], 0)
            iid = m.upload_image(f, ox + c * (size + gap) + size / 2.0, y + rh / 2.0,
                                 size, parent, f["url"])
            ok += bool(iid)
            manifest["images"].append({"id": iid, "ok": bool(iid), "path": f["path"], "url": f["url"]})
            try:
                os.makedirs(out_dir, exist_ok=True)
                with open(uplog, "a", encoding="utf8") as fh:
                    fh.write("%s\t%s\t%s\t%s\n" % (time.strftime("%F %T"),
                                                   "OK" if iid else "FAIL",
                                                   iid or "-", f["url"]))
            except OSError:
                pass
        y += rh + gap
        time.sleep(0.15)
    if not no_frame and parent:
        m.patch_frame(parent, w=frame_w, h=max(y - gap, oy) + pad)
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "miro.json"), "w", encoding="utf8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return ok, need, frame_w, parent


def widget_id(text):
    m = re.search(r"moveToWidget=(\d+)", text or "")
    return m.group(1) if m else re.sub(r"\D", "", text or "")


def main():
    ap = argparse.ArgumentParser(description="картинки товара -> доска Miro")
    ap.add_argument("src", help="ссылка на страницу товара ИЛИ на каталог (обойдёт все модели)")
    ap.add_argument("--cols", type=int, default=None,
                    help="картинок в ряду (по умолчанию 5); рядов столько, сколько нужно")
    ap.add_argument("--size", type=int, default=None, help="ширина картинки на доске, px")
    ap.add_argument("--w", type=int, default=None, help="качать исходники такой ширины (1500)")
    ap.add_argument("--limit", type=int, default=0, help="взять не больше N моделей из каталога")
    ap.add_argument("--left-of", metavar="ССЫЛКА_НА_ОБЪЕКТ",
                    help="вставить партию слева от этого объекта (вставь ссылку вида "
                         "miro.com/app/board/...?moveToWidget=123... из браузера)")
    ap.add_argument("--below", metavar="ССЫЛКА_НА_ОБЪЕКТ",
                    help="вставить партию СНИЗУ от этого объекта, выровняв по верхнему краю "
                         "и начав от его левого края, дальше партии идут вправо")
    ap.add_argument("--skip-existing", action="store_true",
                    help="не пересоздавать фреймы с таким же названием в том же ряду "
                         "(докачка после прерванного прогона)")
    ap.add_argument("--catalog", action="store_true", help="считать страницу каталогом принудительно")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать найденные ракурсы, файлы не качать, доску не трогать")
    ap.add_argument("--no-upload", action="store_true", help="только скачать в папку")
    ap.add_argument("--paste", action="store_true", help="открыть сетку в браузере для копирования")
    ap.add_argument("--keep-all", action="store_true", help="не отбрасывать иконки/логотипы")
    ap.add_argument("--no-frame", action="store_true", help="без рамки, просто сетка на доске")
    ap.add_argument("--no-group", action="store_true",
                    help="не скреплять фреймы прогона в группу (иерархия каталог->товар не сохранится)")
    ap.add_argument("--from-folder", metavar="ПАПКА", help="взять картинки из готовой папки")
    args = ap.parse_args()
    source_url = normalize_source(args.src)

    cfg = load_config()
    cols = args.cols or cfg["cols"]
    size = args.size or cfg["size"]
    target_w = args.w or cfg["w"]
    gap, pad, step = 40, 60, 350

    # ---- список партий: (подсказка названия, ссылка на страницу товара, готовые файлы) ----
    batches = []
    if args.from_folder:
        files = []
        for name in sorted(os.listdir(args.from_folder)):
            p = os.path.join(args.from_folder, name)
            if os.path.splitext(name)[1].lower() in IMG_EXT:
                w, h = image_dimensions(p)
                files.append({"path": p, "url": "file://" + p, "w": w, "h": h})
        batches = [(os.path.basename(args.from_folder.rstrip("/")), None, files)]
        group_name = batches[0][0]
        root = args.from_folder
    else:
        if re.match(r"^https?://", source_url):
            log("читаю страницу ...")
            page, base_url = fetch(source_url)
            is_web = True
        else:
            base_url = "file://" + os.path.abspath(source_url)
            page = open(source_url, encoding="utf8", errors="replace").read()
            is_web = False
        path = urllib.parse.urlparse(source_url).path if re.match(r"^https?://", source_url) else source_url
        looks_product = (bool(re.search(r"-p\d{6,}\.html", path)) or
                         bool(re.search(r"/(products?|pd|dp)/[^/]+/?$", path))) and not args.catalog
        if looks_product:
            batches = [("", source_url, None)]
            group_name = ""
        else:
            models = catalog_items(page, base_url)
            if not models:
                batches = [("", source_url, None)]
                group_name = ""
            else:
                if args.limit:
                    models = models[:args.limit]
                log("в каталоге %d моделей" % len(models))
                for i, (name, link) in enumerate(models, 1):
                    log("  %2d. %-50s" % (i, name[:50]))
                batches = [(n, l, None) for n, l in models]
            group_name = (urllib.parse.urlparse(base_url).path.rstrip("/").split("/")[-1]
                          or group_name)
        root = os.path.join(OUT_ROOT, time.strftime("%Y-%m-%d %H-%M"))
        if not is_web:
            log("(файл, а не сайт: ссылки между страницами работать не будут)")

    modes_offline = args.dry_run or args.no_upload or args.paste or \
        not (cfg.get("token") and cfg.get("board_id"))

    # -------- режим без доски: собираем всё сразу (как раньше) --------
    if modes_offline:
        done = []
        total_need = 0
        for idx, (hint, link, files) in enumerate(batches, 1):
            if files is None:
                log("\n[%d/%d] %s" % (idx, len(batches), slugify(hint) or link.split("/")[-1][:40]))
                if args.dry_run:
                    title, picked = gather_urls(link, args.keep_all)
                    log("  «%s»: %d шт" % ((title or hint)[:55], len(picked)))
                    continue
                title, files = gather(link, target_w, args.keep_all,
                                      os.path.join(root, "%02d %s" % (idx, slugify(hint))))
                if not files:
                    log("  пропускаю: картинок нет")
                    continue
            else:
                title = hint
            total_need += len(files)
            done.append((title, files))
            log("  %d картинок, «%s»" % (len(files), title[:60]))
        if args.dry_run:
            log("\n--dry-run: файлы не качал, доску не трогал")
            return
        if not done:
            raise SystemExit("не удалось собрать ни одной картинки")
        log("\nитого: %d партии, %d картинок" % (len(done), total_need))
        if args.no_upload:
            import subprocess
            subprocess.call(["open", root])
            log("открыл папку %s: выделяй и перетаскивай на доску" % root)
            return
        paste_page([f for _, fs in done for f in fs], size, cols, "обувь",
                   os.path.join(root, "вставка.html"))
        return

    # -------- загрузка на доску: сначала точка старта, дальше ряд за рядом --------
    miro = Miro(cfg["token"], cfg["board_id"])
    batch_w = cols * (size + gap) - gap + 2 * pad

    if args.below:
        iid = widget_id(args.below)
        it = miro.item(iid)
        if it is None:
            log("реперный объект %s на доске не найден - беру фрейм из середины ряда" % iid)
            it = miro.any_frame()
        if it is None:
            log("на доске нет ни одного фрейма - начинаю от центра холста")
            fx, fy = 0.0, 0.0
        else:
            l, top, r, bottom = miro.box(it)
            fx, fy = l, bottom + 400          # партия СТАВИТСЯ СНИЗУ, старт от левого края репера
            log("снизу от объекта %s: партии пойдут вправо от x=%.0f, общий верх y=%.0f"
                % (it.get("id"), fx, fy))
    elif args.left_of:
        iid = widget_id(args.left_of)
        it = miro.item(iid)
        if it is None:
            log("реперный объект %s на доске не найден - беру фрейм из середины ряда" % iid)
            it = miro.any_frame()
        if it is None:
            raise SystemExit("нужен репер для --left-of, но на доске нет ни одного фрейма")
        l, top, r, bottom = miro.box(it)
        span = len(batches) * batch_w + (len(batches) - 1) * step
        fx = l - 300 - span                    # чтобы ПРАВЫЙ край всей партии был левее маркера
        fy = top
        log("слева от объекта %s: партии займут x=%.0f..%.0f, общий верх y=%.0f" % (iid, fx, fx + span, fy))
    else:
        fx, fy = miro.anchor()                 # справа от рабочего ряда, общий верх = уровень ряда
        log("начинаю новый блок от точки x=%.0f y=%.0f" % (fx, fy))

    taken = []
    if args.skip_existing:
        titles, right = [], 0.0
        for f in miro.all_items("frame", cap=400):
            l, top, r, bottom = miro.box(f)
            if abs(top - fy) <= 50:
                titles.append(((f.get("data") or {}).get("title") or "").strip())
                right = max(right, r)
        taken = list(titles)
        if taken:
            log("в этом ряду уже есть %d фреймов: %s" % (len(taken), "; ".join(t[:28] for t in taken)))
            fx = right + step          # новые фреймы ставим вплотную справа от существующих
        else:
            log("в этом ряду (%.0f) фреймов нет - ничего пропускать не нужно" % fy)

    total_ok = total_need = skipped = 0
    placed = []                                        # (id фрейма, заголовок) - для иерархии
    fx_start = fx
    for idx, (hint, link, files) in enumerate(batches, 1):
        key = slugify(hint).upper()
        if args.skip_existing and files is None and key:
            hit = next((t for t in taken if slugify(t).upper().startswith(key)), None)
            if hit:
                taken.remove(hit)
                skipped += 1
                log("\n[%d/%d] %s - уже есть на доске (%s), пропускаю" % (idx, len(batches), key, hit[:40]))
                continue   # fx не двигаем: он уже выставлен справа от всех существующих фреймов
        log("\n[%d/%d] %s" % (idx, len(batches), slugify(hint) or link.split("/")[-1][:40]))
        out_dir = os.path.join(root, "%02d %s" % (idx, slugify(hint)))
        if files is None:
            title, picked = gather_urls(link, args.keep_all)
            if not picked:
                log("  пропускаю: картинок нет")
                continue
        else:
            title, picked = hint, None
        ok, need, width, frame_id = place_stream(miro, title, picked, files, out_dir, fx, fy,
                                                 size, cols, gap, pad, args.no_frame, target_w)
        total_ok += ok
        total_need += need
        if frame_id:
            placed.append((frame_id, title))
        log("  фрейм %d/%d «%s»: %d из %d -> %s" % (idx, len(batches), title[:44], ok, need, out_dir))
        fx += width + step                     # следующая партия - ПРАВЕЕ, верх (fy) тот же

    # ---- иерархия: фрейм в фрейм REST запрещает, но ГРУППА принимает id фреймов.
    # Так прогон (каталог) остаётся одним объектом: выделяется и двигается целиком.
    if not args.no_group and not args.no_frame and len(placed) > 1:
        label = miro.create_text(group_name or "прогон", (fx_start + fx) / 2.0, fy - 200, 60) \
            if group_name else None
        gid = miro.create_group([f for f, _ in placed] + ([label] if label else []),
                                title=group_name or "")
        placed_ids = [f for f, _ in placed]
        try:
            os.makedirs(root, exist_ok=True)
            with open(os.path.join(root, "miro-прогон.json"), "w", encoding="utf8") as fh:
                json.dump({"group_id": gid, "catalog": group_name, "url": args.src,
                           "frames": [{"id": f, "title": t} for f, t in placed]},
                          fh, ensure_ascii=False, indent=1)
        except OSError:
            pass

    log("\nготово: %d картинок из %d (пропущено партий: %d)" % (total_ok, total_need, skipped))
    log("доска: https://miro.com/app/board/%s/" % cfg["board_id"])
    if total_ok < total_need:
        log("часть картинок не загрузилась - файлы в %s, перезапусти с --skip-existing "
            "или перетащи вручную" % root)


if __name__ == "__main__":
    main()
