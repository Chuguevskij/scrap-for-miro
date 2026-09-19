"""Минимальная загрузка переменных из локального файла .env."""

import os


def load_dotenv(path=None):
    """Загрузить .env, не перезаписывая уже заданные переменные окружения."""
    path = path or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as stream:
            lines = stream.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value
