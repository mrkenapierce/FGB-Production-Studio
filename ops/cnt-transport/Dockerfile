# CNT capture image — separate from the FGB Dockerfile so FGB builds never change.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb pulseaudio ffmpeg curl ca-certificates procps \
      fonts-dejavu-core fonts-liberation fonts-noto-color-emoji tini tzdata \
  && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 cnt
WORKDIR /opt/cnt
COPY run-cnt.sh ./
RUN chmod +x run-cnt.sh
USER cnt

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD test -f /tmp/cnt-ffmpeg.progress && [ $(( $(date +%s) - $(stat -c %Y /tmp/cnt-ffmpeg.progress) )) -lt 30 ]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./run-cnt.sh"]