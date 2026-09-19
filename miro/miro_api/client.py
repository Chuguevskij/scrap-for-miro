"""Предметные операции над объектами доски Miro."""

import html
import json
import os
import urllib.parse

from .transport import MiroTransport


class MiroClient:
    """Клиент доски, скрывающий JSON-формат Miro от остального приложения."""

    def __init__(self, token: str, board_id: str, transport=None):
        if not token:
            raise ValueError("не указан токен Miro")
        if not board_id:
            raise ValueError("не указан board_id Miro")
        self.board_id = urllib.parse.quote(board_id, safe="")
        self.transport = transport or MiroTransport(token)

    def list_items(self, item_type: str, cap: int = 1500) -> list[dict]:
        """Получить объекты доски, прекращая обход при повторной странице."""
        result, seen, offset = [], set(), 0
        while offset < cap:
            _, body = self.transport.request(
                "GET",
                "/boards/%s/items?limit=50&type=%s&offset=%d" %
                (self.board_id, item_type, offset),
                timeout=120,
            )
            items = json.loads(body).get("data", [])
            fresh = [item for item in items if item.get("id") not in seen]
            if not fresh:
                break
            result.extend(fresh)
            seen.update(item.get("id") for item in fresh)
            offset += len(items)
        return result

    def get_item(self, item_id: str):
        """Получить объект или None, если Miro вернул 404."""
        status, body = self.transport.request(
            "GET", "/boards/%s/items/%s" % (self.board_id, item_id), soft=True
        )
        return None if status == 404 else json.loads(body)

    def get_any_frame(self):
        """Вернуть первый доступный фрейм как запасной ориентир."""
        frames = self.list_items("frame", cap=200)
        return frames[len(frames) // 2] if frames else None

    @staticmethod
    def box(item: dict) -> tuple[float, float, float, float]:
        """Преобразовать центр и размеры Miro в left, top, right, bottom."""
        position = item.get("position", {})
        geometry = item.get("geometry", {})
        width, height = geometry.get("width", 0), geometry.get("height", 0)
        x, y = position.get("x", 0), position.get("y", 0)
        return x - width / 2, y - height / 2, x + width / 2, y + height / 2

    def create_frame(self, title, x, y, width, height):
        """Создать фрейм и вернуть его id."""
        _, body = self.transport.request(
            "POST",
            "/boards/%s/frames" % self.board_id,
            {
                "data": {"title": title, "format": "custom", "type": "freeform"},
                "position": {"x": x, "y": y},
                "geometry": {"width": width, "height": height},
            },
        )
        return json.loads(body)["id"]

    def patch_frame(self, frame_id, width, height):
        """Изменить размеры фрейма, сохранив его верхний край."""
        current = self.get_item(frame_id)
        if current is None:
            return
        position = current.get("position", {})
        geometry = current.get("geometry", {})
        body = {
            "geometry": {"width": width, "height": height},
            "position": {
                "x": position.get("x", 0),
                "y": position.get("y", 0) - geometry.get("height", 0) / 2 + height / 2,
            },
        }
        self.transport.request("PATCH", "/boards/%s/frames/%s" % (self.board_id, frame_id), body)

    def create_group(self, item_ids):
        """Объединить несколько объектов в группу."""
        ids = [int(item_id) for item_id in item_ids if str(item_id).isdigit()]
        if len(ids) < 2:
            return None
        status, body = self.transport.request(
            "POST", "/boards/%s/groups" % self.board_id, {"data": {"items": ids}}, soft=True
        )
        return json.loads(body).get("id") if status < 300 else None

    def create_text(self, content, x, y, size=32, parent_id=None):
        """Создать подпись: с parent_id — внутри фрейма, x и y от его верхнего левого угла."""
        body = {
            "data": {"content": '<span style="font-size:%dpx">%s</span>' %
                                (size, html.escape(content))},
            "position": {"x": x, "y": y},
        }
        if parent_id:
            body["parent"] = {"id": parent_id}
        _, body = self.transport.request(
            "POST", "/boards/%s/texts" % self.board_id, body, soft=True
        )
        return json.loads(body).get("id")

    def upload_image(self, file_info, x, y, width, parent_id, alt):
        """Загрузить локальную картинку в заданную точку фрейма."""
        position = {"x": x, "y": y}
        if parent_id:
            position["relativeTo"] = "parent_top_left"
        metadata = {
            "title": os.path.basename(file_info["path"]),
            "altText": alt[:137],
            "position": position,
            "geometry": {"width": width},
        }
        if parent_id:
            metadata["parent"] = {"id": parent_id}
        status, body = self.transport.upload(
            "/boards/%s/images" % self.board_id,
            file_info["path"],
            metadata,
        )
        if status != 201:
            return None
        return json.loads(body).get("id")
