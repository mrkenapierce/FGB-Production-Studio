#!/usr/bin/env python3
"""FGB YouTube router with a live 720p protected-video selector input.

This wrapper deliberately reuses the proven production router for master video,
master audio, RTMPS transport, polling, and keyframe-safe switching. It replaces
only the old static-card selector input with a local MPEG-TS/H.264 source whose
RSS/news and trivia crawl remain animated during protected trivia windows.
"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import signal
from pathlib import Path
from typing import Any

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # type: ignore

BASE_PATH = os.getenv(
    "FGB_YOUTUBE_BASE_ROUTER",
    "/opt/fgbears-live/bin/youtube-stream-router.py",
)
spec = importlib.util.spec_from_file_location("fgb_youtube_base_router", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not import base router: {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

LOG = logging.getLogger("fgb-youtube-dynamic-router")


class DynamicStreamRouter(base.StreamRouter):
    """Reuse the proven router and add a third, live protected-video pad."""

    def _on_card_buffer(self, _pad: Gst.Pad, _info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        # The inherited pre-encoded static card remains connected only as an
        # emergency-compatible dormant branch. It must never trigger selection.
        return Gst.PadProbeReturn.OK

    def _push_card_frame(self) -> bool:
        # Do not spend work pumping the dormant static branch.
        return not self._stopping

    def _build_pipeline(self) -> None:
        super()._build_pipeline()

        self.static_card_selector_pad = self.card_selector_pad
        dynamic_port = int(os.getenv("FGB_YOUTUBE_DYNAMIC_CARD_PORT", "2942"))

        self.dynamic_src = self.make("udpsrc", "dynamic_card_udp")
        self.dynamic_src.set_property("port", dynamic_port)
        self.dynamic_src.set_property("buffer-size", 4_000_000)
        self.dynamic_src.set_property(
            "caps",
            Gst.Caps.from_string(
                "video/mpegts,systemstream=(boolean)true,packetsize=(int)188"
            ),
        )
        self.dynamic_input_queue = self.make("queue", "dynamic_card_input_queue")
        self.dynamic_input_queue.set_property("max-size-time", 3 * Gst.SECOND)
        self.dynamic_input_queue.set_property("max-size-bytes", 0)
        self.dynamic_input_queue.set_property("max-size-buffers", 0)
        self.dynamic_demux = self.make("tsdemux", "dynamic_card_demux")
        self.dynamic_queue = self.make("queue", "dynamic_card_video_queue")
        self.dynamic_queue.set_property("max-size-time", 3 * Gst.SECOND)
        self.dynamic_queue.set_property("max-size-bytes", 0)
        self.dynamic_queue.set_property("max-size-buffers", 0)
        self.dynamic_parse = self.make("h264parse", "dynamic_card_h264_parse")
        self.dynamic_parse.set_property("config-interval", -1)
        self.dynamic_caps = self.make("capsfilter", "dynamic_card_h264_caps")
        self.dynamic_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                "video/x-h264,stream-format=(string)byte-stream,alignment=(string)au"
            ),
        )

        for element in (
            self.dynamic_src,
            self.dynamic_input_queue,
            self.dynamic_demux,
            self.dynamic_queue,
            self.dynamic_parse,
            self.dynamic_caps,
        ):
            self.pipeline.add(element)

        if not self.dynamic_src.link(self.dynamic_input_queue) or not self.dynamic_input_queue.link(self.dynamic_demux):
            raise RuntimeError("could not link protected MPEG-TS input")
        if not self.dynamic_queue.link(self.dynamic_parse) or not self.dynamic_parse.link(self.dynamic_caps):
            raise RuntimeError("could not link protected H.264 parser")

        dynamic_pad = self.selector.request_pad_simple("sink_%u")
        if not dynamic_pad:
            raise RuntimeError("could not allocate protected selector pad")
        dynamic_pad.set_property("always-ok", True)
        if self.dynamic_caps.get_static_pad("src").link(dynamic_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("could not link protected video to selector")

        # Every inherited card-mode switch now targets the animated protected
        # branch rather than the static appsrc branch.
        self.card_selector_pad = dynamic_pad
        self.dynamic_selector_pad = dynamic_pad
        self.dynamic_demux.connect("pad-added", self._on_dynamic_demux_pad)
        self.dynamic_caps.get_static_pad("src").add_probe(
            Gst.PadProbeType.BUFFER,
            self._on_dynamic_buffer,
        )
        LOG.info("protected video input ready on udp://127.0.0.1:%d", dynamic_port)

    def _on_dynamic_demux_pad(self, _demux: Gst.Element, pad: Gst.Pad) -> None:
        caps = pad.get_current_caps() or pad.query_caps(None)
        caps_name = caps.to_string() if caps else ""
        sink = self.dynamic_queue.get_static_pad("sink")
        if caps_name.startswith("video/x-h264") and not sink.is_linked():
            result = pad.link(sink)
            LOG.info("linked protected video pad: %s (%s)", caps_name, result.value_nick)

    def _on_dynamic_buffer(self, _pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        buffer = info.get_buffer()
        if buffer is not None and self.pending_mode == "card" and not (
            buffer.get_flags() & Gst.BufferFlags.DELTA_UNIT
        ):
            GLib.idle_add(self._activate_mode, "card")
        return Gst.PadProbeReturn.OK


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-port", type=int, default=0)
    parser.add_argument("--output-port", type=int, default=int(os.getenv("FGB_YOUTUBE_ROUTER_OUTPUT_PORT", str(base.DEFAULT_OUTPUT_PORT))))
    parser.add_argument("--card", default=os.getenv("FGB_YOUTUBE_TRIVIA_CARD_H264", base.DEFAULT_CARD))
    parser.add_argument("--routing-url", default=os.getenv("FGB_STREAM_ROUTING_URL", base.DEFAULT_ROUTING_URL))
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--test-cycle", type=float, default=0.0)
    parser.add_argument("--runtime", type=float, default=0.0)
    parser.add_argument("--log-level", default=os.getenv("FGB_STREAM_ROUTER_LOGLEVEL", "INFO"))
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    port = args.input_port or base.parse_udp_port(
        os.getenv("YOUTUBE_LOCAL_UDP_URL", "udp://127.0.0.1:1939")
    )
    target = None
    if not args.test:
        key = os.getenv("YOUTUBE_STREAM_KEY", "").strip()
        upstream = os.getenv(
            "YOUTUBE_UPSTREAM_RTMP_BASE",
            "rtmps://a.rtmps.youtube.com/live2",
        ).rstrip("/")
        if not key or key == "REPLACE_WITH_YOUTUBE_STREAM_KEY":
            raise ValueError("YOUTUBE_STREAM_KEY is required")
        target = f"{upstream}/{key}"

    router = DynamicStreamRouter(
        input_port=port,
        output_port=args.output_port,
        card_path=args.card,
        routing_url=args.routing_url,
        upstream_target=target,
        test_mode=args.test,
        test_cycle=args.test_cycle,
        runtime=args.runtime,
    )

    def handle_signal(_signum: int, _frame: Any) -> None:
        GLib.idle_add(router.stop)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    return router.run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        LOG.exception("fatal dynamic router error: %s", exc)
        raise SystemExit(70)
