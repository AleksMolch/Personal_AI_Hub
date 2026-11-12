"""Генератор иконок PWA из простого векторного описания.

Назначение: без внешних сервисов и бинарных ассетов воспроизводимо создавать
PNG-иконки приложения (192/512, maskable, apple-touch). Используется bundled
Pillow; запуск из корня репозитория:

    python infra/scripts/gen_icons.py

Результат — в apps/web/public/icons/. Исходный вид описан прямо здесь, чтобы
иконку можно было обновить без хранения бинарников в Git.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# Фирменная палитра: тёмный фон и акцент индиго (совпадают с UI-темой).
BACKGROUND = (15, 23, 42, 255)  # slate-900
ACCENT = (99, 102, 241, 255)  # indigo-500
ACCENT_SOFT = (129, 140, 248, 255)  # indigo-400
NODE = (255, 255, 255, 255)

OUT_DIR = Path("apps/web/public/icons")


def _draw(size: int) -> Image.Image:
    """Рисует «хаб»: три узла, соединённые в центр, на тёмном фоне."""
    image = Image.new("RGBA", (size, size), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # Мягкая подложка-пятно по центру, чтобы иконка читалась на светлых полках.
    margin = size * 0.12
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=size * 0.22,
        fill=(30, 41, 59, 255),  # slate-800
    )

    cx, cy = size * 0.5, size * 0.5
    r = size * 0.30
    node_r = size * 0.085
    # Три узла по окружности (верх, низ-лево, низ-право).
    from math import cos, pi, sin

    nodes = []
    for angle in (-pi / 2, pi / 6, 5 * pi / 6):
        nodes.append((cx + r * cos(angle), cy + r * sin(angle)))

    # Линии от узлов к центру.
    for (nx, ny) in nodes:
        draw.line([nx, ny, cx, cy], fill=ACCENT, width=max(3, size // 48))

    # Центральный узел.
    draw.ellipse(
        [cx - node_r, cy - node_r, cx + node_r, cy + node_r],
        fill=ACCENT_SOFT,
    )
    # Внешние узлы.
    for (nx, ny) in nodes:
        draw.ellipse(
            [nx - node_r, ny - node_r, nx + node_r, ny + node_r],
            fill=NODE,
        )
    return image


def main() -> None:
    """Генерирует все размеры иконок в public/icons."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sizes = {
        "icon-192.png": 192,
        "icon-512.png": 512,
        "maskable-512.png": 512,
        "apple-touch-icon.png": 180,
    }
    for filename, size in sizes.items():
        _draw(size).save(OUT_DIR / filename, format="PNG")
        print(f"written {OUT_DIR / filename} ({size}x{size})")


if __name__ == "__main__":
    main()
