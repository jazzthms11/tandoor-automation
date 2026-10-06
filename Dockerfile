# Die CLI als Image. Gebaut wird in zwei Schritten, Abhängigkeiten vor dem Code: Docker baut eine
# Schicht nur neu, wenn sich ihre Eingabe geändert hat, und der Code ändert sich viel öfter als
# uv.lock. Ein Neubau nach einer Codeänderung dauert damit Sekunden statt Minuten.

FROM python:3.13-slim

# pdftotext für den Kaufland-Beleg, tzdata damit TZ=Europe/Berlin überhaupt etwas bedeutet:
# plan apply nimmt die Zeitzone vom System, und ohne Zonendaten bliebe es bei UTC.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends poppler-utils tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# Gearbeitet wird im eingehängten Verzeichnis, dort liegen die TSV-Dateien und der Laufzustand.
WORKDIR /work

CMD ["plan", "--help"]
