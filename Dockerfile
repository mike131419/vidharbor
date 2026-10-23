# VidHarbor web app for phones - runs on Render, any Docker host or a VPS.
#   docker build -t vidharbor .
#   docker run -p 8787:8787 -e VIDHARBOR_CODE=YOUR-CODE vidharbor
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg merges video + audio and makes MP3s; Deno solves YouTube's JavaScript checks
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
 && curl -fsSL -o /tmp/deno.zip \
      https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip \
 && unzip -q /tmp/deno.zip -d /usr/local/bin \
 && rm /tmp/deno.zip \
 && apt-get purge -y unzip && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && ffmpeg -version | head -1 && deno --version | head -1

WORKDIR /app
COPY requirements-server.txt .
RUN pip install -r requirements-server.txt

COPY vidharbor ./vidharbor

# run as an ordinary user; downloads and engine updates go to its home folder
RUN useradd --create-home --uid 10001 vidharbor
USER vidharbor

EXPOSE 8787
CMD ["python", "-m", "vidharbor.cloud"]
