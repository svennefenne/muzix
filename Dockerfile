# syntax=docker/dockerfile:1.7
# Muzix — self-hosted music, VGM, audiobook, podcast and radio player.

# ---- web interface ---------------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- ymtool (Atari ST .ym player, on StSound) ------------------------------
FROM debian:trixie-slim AS ymtool
ARG STSOUND_COMMIT=a27c29339bed5076cd3342cae8270d2e813b914c
RUN apt-get update && apt-get install -y --no-install-recommends g++ git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/arnaud-carre/StSound /stsound && git -C /stsound checkout "$STSOUND_COMMIT"
COPY docker/ymtool/ymtool.cpp /stsound/ymtool.cpp
RUN cd /stsound && g++ -O2 -w -o /usr/local/bin/ymtool ymtool.cpp StSoundLibrary/*.cpp StSoundLibrary/LZH/*.cpp \
      -IStSoundLibrary -IStSoundLibrary/LZH

# ---- zxtune123 (ZX Spectrum trackers: Pro Tracker, Sound Tracker, ASC, TurboFM...) ----
FROM debian:trixie-slim AS zxtune
ARG ZXTUNE_COMMIT=c94a1d16da4386457a3a6a39a7c3e021669b1c1e
RUN apt-get update && apt-get install -y --no-install-recommends g++ make git ca-certificates zlib1g-dev \
      libboost-program-options-dev libboost-locale-dev libboost-filesystem-dev libboost-thread-dev \
      libboost-system-dev libasound2-dev libpulse-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git init -q /zxtune && git -C /zxtune fetch -q --depth 1 https://github.com/vitamin-caig/zxtune "$ZXTUNE_COMMIT" \
 && git -C /zxtune checkout -q FETCH_HEAD
# ALSA/PulseAudio are only needed to compile; zxtune123 loads them at run time and Muzix writes files
RUN make -C /zxtune/apps/zxtune123 -j"$(nproc)" platform=linux release=1 system.zlib=1 > /tmp/build.log 2>&1 \
      || (grep -E ": error:|\*\*\*" /tmp/build.log | head -40; false) \
 && install -m755 /zxtune/bin/linux/release/zxtune123 /usr/local/bin/zxtune123

# ---- runtime ---------------------------------------------------------------
FROM python:3.13-slim-trixie
LABEL org.opencontainers.image.title="Muzix" \
      org.opencontainers.image.description="Self-hosted music, VGM, audiobook, podcast and radio player" \
      org.opencontainers.image.source="https://github.com/svennefenne/muzix" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libgme0 libopenmpt0t64 sidplayfp fluidsynth fluid-soundfont-gm furnace libboost-program-options1.83.0 \
      gosu tini ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ymtool /usr/local/bin/ymtool /usr/local/bin/ymtool
COPY --from=zxtune /usr/local/bin/zxtune123 /usr/local/bin/zxtune123
WORKDIR /app
COPY backend/pyproject.toml backend/
COPY backend/muzix backend/muzix
RUN pip install --no-cache-dir "./backend[organize]"
COPY --from=frontend /src/dist /app/static
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

ENV MUZIX_DATA=/config MUZIX_STATIC=/app/static MUZIX_PORT=8080 \
    MUZIX_DEFAULT_ROOTS="/music:music,/vgm:vgm,/audiobooks:audiobooks" \
    PUID=99 PGID=100 UMASK=002 PYTHONUNBUFFERED=1
VOLUME /config
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('MUZIX_PORT','8080')+'/api/health',timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
CMD ["python", "-m", "muzix"]
