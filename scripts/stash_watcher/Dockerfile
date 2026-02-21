FROM python:3.12-alpine

# Copy uv from the official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN apk add --no-cache tzdata \
    wget \
    curl \
    ca-certificates \
    git

COPY . .
RUN uv pip install --system -r requirements.txt
