"""Безопасное получение токена Miro."""

import getpass
import os
import subprocess

try:
    from ..env import load_dotenv
except ImportError:  # запуск тестов из каталога miro
    from env import load_dotenv


SERVICE = "product-board-miro"


def get_token(service: str = SERVICE) -> str:
    """Получить токен из окружения, .env или macOS Keychain."""
    load_dotenv()
    token = os.environ.get("MIRO_TOKEN", "").strip()
    if token:
        return token
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", getpass.getuser(), "-s", service, "-w"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def save_token(token: str, service: str = SERVICE) -> None:
    """Сохранить токен в macOS Keychain без записи в конфигурационный файл."""
    if not token.strip():
        raise ValueError("токен не может быть пустым")
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-a",
            getpass.getuser(),
            "-s",
            service,
            "-w",
            token.strip(),
        ],
        check=True,
    )


def prompt_and_save_token(service: str = SERVICE) -> None:
    """Запросить токен скрытым вводом и сохранить его в Keychain."""
    save_token(getpass.getpass("Miro token: "), service)
