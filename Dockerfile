# Die CLI als Image. Gebaut wird in zwei Schritten, Abhängigkeiten vor dem Code: Docker baut eine
# Schicht nur neu, wenn sich ihre Eingabe geändert hat, und der Code ändert sich viel öfter als
# uv.lock. Ein Neubau nach einer Codeänderung dauert damit Sekunden statt Minuten.

FROM python:3.13-slim

# pdftotext für den Kaufland-Beleg, tzdata damit TZ=Europe/Berlin überhaupt etwas bedeutet:
# plan apply nimmt die Zeitzone vom System, und ohne Zonendaten bliebe es bei UTC. curl holt
# Claude Code.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends poppler-utils tzdata curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Claude Code wählt den Wochenplan. Der Installer legt es unter /root ab, wo der Nutzer aus der
# Compose-Datei nicht hinkommt, deshalb wandert die Datei nach /usr/local/bin. Eine neue Fassung
# kommt mit dem nächsten Neubau ohne Cache, im Container aktualisiert es sich nicht selbst.
ENV DISABLE_AUTOUPDATER=1
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && cp -L /root/.local/bin/claude /usr/local/bin/claude \
    && rm -rf /root/.local /root/.claude /root/.claude.json

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

# Gearbeitet wird im eingehängten Klon, dort landen bundle/, vorschlag/ und die Exporte.
WORKDIR /work

# Die Oberfläche hört auf 8000, welcher Port auf dem Server dazu passt, sagt die Compose-Datei.
# Ohne Befehl zeigt der Container die Hilfe der CLI, die Compose-Datei gibt jedem Dienst seinen.
EXPOSE 8000
CMD ["plan", "--help"]
