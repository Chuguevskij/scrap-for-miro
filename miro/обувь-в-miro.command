#!/bin/bash
cd "$(dirname "$0")"
echo "Вставь ссылку на страницу товара (Enter):"
read -r URL
python3 miro_obuv.py "$URL"
echo
read -r -p "Готово. Нажми Enter чтобы закрыть." _
