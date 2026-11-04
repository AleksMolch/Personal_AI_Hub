# Образ сервиса headless-рендера страниц (ADR-0006).
#
# Назначение: открывать страницы тарифов в Chromium и отдавать их текст, когда
# цены дорисовывает JavaScript. Сервис опционален: запускается профилем
# compose `pricebot`, базовый стек работает без него.
#
# Chromium и его системные библиотеки ставятся только сюда: в образе API их нет,
# чтобы не утяжелять его и не исполнять чужой JavaScript рядом с ключами.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/packages/core

WORKDIR /app

COPY infra/pricebot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# --with-deps доустанавливает системные библиотеки, нужные Chromium.
# Кэш apt чистим, иначе образ растёт на десятки мегабайт.
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache/ms-playwright/.links

# Код SSRF-проверки переиспользуется из доменного пакета: одна реализация
# правила вместо копии в контейнере.
COPY packages/core /app/packages/core
COPY infra/pricebot/app.py /app/app.py

EXPOSE 8100

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
