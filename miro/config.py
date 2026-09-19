"""Загрузка несекретных настроек приложения."""

import json
import os
import re

try:
    from .env import load_dotenv
except ImportError:  # запуск как python3 miro/product_board.py
    from env import load_dotenv


CONFIG_PATH = os.path.expanduser("~/Library/Application Support/product-board/config.json")
DEFAULTS = {
    "board_id": "",
    "board_url": "",
    "w": 1500,
    "cols": 20,
    "size": 480,
}


def load_config(path: str = CONFIG_PATH) -> dict:
    """Загрузить настройки доски, не читая токен из файла."""
    load_dotenv()
    config = dict(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as stream:
                data = json.load(stream)
            if isinstance(data, dict):
                config.update({key: value for key, value in data.items() if key != "token"})
        except (OSError, ValueError) as exc:
            print("внимание: не смог прочитать конфиг (%s)" % exc, flush=True)
    config["board_url"] = os.environ.get("MIRO_BOARD_URL", config["board_url"])
    board_match = re.search(r"/board/([^/?#]+)", config["board_url"])
    if board_match:
        config["board_id"] = board_match.group(1)
    return config
