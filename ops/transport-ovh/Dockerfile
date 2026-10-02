FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium xvfb pulseaudio ffmpeg curl ca-certificates openssl procps python3 tzdata fonts-dejavu-core fonts-liberation fonts-noto-color-emoji tini && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 transport
WORKDIR /opt/transport
COPY run-output.sh heartbeat.sh archive-recorder.sh archive-uploader.py ./
RUN chmod +x run-output.sh heartbeat.sh archive-recorder.sh archive-uploader.py
USER transport
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD test -f /tmp/fgb-ffmpeg.progress && [ $(( $(date +%s) - $(stat -c %Y /tmp/fgb-ffmpeg.progress) )) -lt 30 ]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./run-output.sh"]
