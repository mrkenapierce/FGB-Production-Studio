FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium xvfb pulseaudio ffmpeg curl ca-certificates openssl procps fonts-dejavu-core fonts-liberation fonts-noto-color-emoji tini && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 transport
WORKDIR /opt/transport
COPY ops/transport/run-output.sh ops/transport/heartbeat.sh ./
RUN chmod +x run-output.sh heartbeat.sh
USER transport
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./run-output.sh"]