#!/usr/bin/env python3
"""Low-CPU YouTube branch router for the FGBears livestream.

The shared master remains encoded once. This process demuxes that already-encoded
MPEG-TS branch, keeps the master AAC audio continuous, and uses GStreamer's
input-selector to choose between the already-encoded live H.264 video and a
pre-encoded full-screen YouTube→Rumble trivia card. No live video decode or
encode occurs here.

GStreamer performs only packet parsing, keyframe-safe selection, and MPEG-TS
muxing. A child FFmpeg process receives that selected MPEG-TS on loopback and
performs copy/remux transport to YouTube RTMPS. This preserves the proven FFmpeg
TLS path without adding a second video encoder.

The router polls the sanitized Lovable routing endpoint. Any endpoint failure or
stale trivia state fails open to the normal live program. Changes are made at an
H.264 keyframe boundary to minimize decoder disturbance.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Any

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import GLib, Gst  # type: ignore

LOG = logging.getLogger("fgb-youtube-stream-router")
Gst.init(None)

DEFAULT_ROUTING_URL = "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing"
DEFAULT_CARD = "/opt/fgbears-live/assets/youtube-rumble-trivia.h264"
DEFAULT_OUTPUT_PORT = 2941
FRAME_DURATION = Gst.SECOND // 30


def parse_udp_port(url: str, fallback: int = 1939) -> int:
    m = re.search(r"udp://(?:127\.0\.0\.1|localhost):(\d+)", url or "")
    return int(m.group(1)) if m else fallback


def split_h264_access_units(blob: bytes) -> list[bytes]:
    """Split an Annex-B H.264 stream at AUD NAL units (nal_unit_type=9)."""
    starts: list[tuple[int, int, int]] = []
    i = 0
    n = len(blob)
    while i + 4 <= n:
        if blob[i : i + 4] == b"\x00\x00\x00\x01":
            nal = i + 4
            if nal < n:
                starts.append((i, nal, blob[nal] & 0x1F))
            i = nal + 1
        elif blob[i : i + 3] == b"\x00\x00\x01":
            nal = i + 3
            if nal < n:
                starts.append((i, nal, blob[nal] & 0x1F))
            i = nal + 1
        else:
            i += 1
    aud_positions = [pos for pos, _nal, typ in starts if typ == 9]
    if not aud_positions:
        raise ValueError("card H.264 asset has no AUD NAL units")
    prefix = blob[: aud_positions[0]]
    access_units: list[bytes] = []
    for idx, pos in enumerate(aud_positions):
        end = aud_positions[idx + 1] if idx + 1 < len(aud_positions) else len(blob)
        chunk = blob[pos:end]
        if idx == 0 and prefix:
            chunk = prefix + chunk
        if chunk:
            access_units.append(chunk)
    if not access_units:
        raise ValueError("card H.264 asset contains no access units")
    return access_units


def has_idr(access_unit: bytes) -> bool:
    i = 0
    n = len(access_unit)
    while i + 4 <= n:
        if access_unit[i : i + 4] == b"\x00\x00\x00\x01":
            nal = i + 4
        elif access_unit[i : i + 3] == b"\x00\x00\x01":
            nal = i + 3
        else:
            i += 1
            continue
        if nal < n and (access_unit[nal] & 0x1F) == 5:
            return True
        i = nal + 1
    return False


def desired_card(payload: dict[str, Any]) -> bool:
    """Return True only for the approved YouTube redirect during fresh trivia."""
    try:
        if not bool(payload.get("platforms", {}).get("youtube", True)):
            return False
        trivia = payload.get("trivia") or {}
        if not bool(trivia.get("active")) or bool(trivia.get("stale")):
            return False
        redirect = (payload.get("components") or {}).get("redirectCta") or {}
        if not bool(redirect.get("youtube")):
            return False
        for overlay in payload.get("overlays") or []:
            if overlay.get("key") != "yt_rumble_trivia_redirect":
                continue
            if not bool(overlay.get("enabled")):
                return False
            if overlay.get("target") not in ("youtube", "both"):
                return False
            if overlay.get("trigger") not in ("during_trivia", "always"):
                return False
            return True
        return False
    except Exception:
        return False


class StreamRouter:
    def __init__(
        self,
        input_port: int,
        output_port: int,
        card_path: str,
        routing_url: str,
        upstream_target: str | None,
        test_mode: bool = False,
        test_cycle: float = 0.0,
        runtime: float = 0.0,
    ) -> None:
        self.input_port = input_port
        self.output_port = output_port
        self.card_path = Path(card_path)
        self.routing_url = routing_url
        self.upstream_target = upstream_target
        self.test_mode = test_mode
        self.test_cycle = test_cycle
        self.runtime = runtime
        self.loop = GLib.MainLoop()
        self.pipeline = Gst.Pipeline.new("fgb-youtube-router")
        if not self.pipeline:
            raise RuntimeError("could not create GStreamer pipeline")

        blob = self.card_path.read_bytes()
        self.card_aus = split_h264_access_units(blob)
        self.card_idr = [has_idr(au) for au in self.card_aus]
        if not any(self.card_idr):
            raise ValueError("card H.264 asset contains no IDR frame")
        LOG.info("loaded card asset: %d AUs, %d IDR", len(self.card_aus), sum(self.card_idr))

        self.card_index = 0
        self.card_pts = 0
        self.live_selector_pad: Gst.Pad | None = None
        self.card_selector_pad: Gst.Pad | None = None
        self.current_mode = "live"
        self.pending_mode: str | None = None
        self._poll_inflight = False
        self._stopping = False
        self._last_config_version: Any = None
        self.ffmpeg: subprocess.Popen[bytes] | None = None
        self._build_pipeline()

    @staticmethod
    def make(factory: str, name: str) -> Gst.Element:
        element = Gst.ElementFactory.make(factory, name)
        if not element:
            raise RuntimeError(f"missing GStreamer element: {factory}")
        return element

    def _build_pipeline(self) -> None:
        self.src = self.make("udpsrc", "program_udp")
        self.src.set_property("port", self.input_port)
        self.src.set_property("buffer-size", 4_000_000)
        self.src.set_property(
            "caps",
            Gst.Caps.from_string("video/mpegts,systemstream=(boolean)true,packetsize=(int)188"),
        )
        input_queue = self.make("queue", "program_input_queue")
        input_queue.set_property("max-size-time", 2 * Gst.SECOND)
        input_queue.set_property("max-size-bytes", 0)
        input_queue.set_property("max-size-buffers", 0)
        self.demux = self.make("tsdemux", "program_demux")

        self.selector = self.make("input-selector", "video_selector")
        self.selector.set_property("sync-streams", True)
        self.selector.set_property("sync-mode", 1)  # clock
        if self.selector.find_property("cache-buffers"):
            self.selector.set_property("cache-buffers", True)
        if self.selector.find_property("drop-backwards"):
            self.selector.set_property("drop-backwards", True)

        self.live_queue = self.make("queue", "live_video_queue")
        self.live_queue.set_property("max-size-time", 3 * Gst.SECOND)
        self.live_queue.set_property("max-size-bytes", 0)
        self.live_queue.set_property("max-size-buffers", 0)
        self.live_parse = self.make("h264parse", "live_h264_parse")
        self.live_parse.set_property("config-interval", -1)
        self.live_caps = self.make("capsfilter", "live_h264_caps")
        self.live_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-h264,stream-format=(string)byte-stream,alignment=(string)au"),
        )

        # Audio never switches: YouTube continues to hear the master program.
        self.audio_queue = self.make("queue", "live_audio_queue")
        self.audio_queue.set_property("max-size-time", 3 * Gst.SECOND)
        self.audio_queue.set_property("max-size-bytes", 0)
        self.audio_queue.set_property("max-size-buffers", 0)
        self.audio_parse = self.make("aacparse", "live_aac_parse")

        # The card is a pre-encoded one-second GOP. Appsrc only copies bytes and
        # assigns current running timestamps; it performs no video encoding.
        self.card = self.make("appsrc", "card_h264")
        self.card.set_property("is-live", True)
        self.card.set_property("format", Gst.Format.TIME)
        self.card.set_property("block", False)
        self.card.set_property("do-timestamp", False)
        self.card.set_property(
            "caps",
            Gst.Caps.from_string(
                "video/x-h264,stream-format=(string)byte-stream,alignment=(string)au,framerate=(fraction)30/1"
            ),
        )
        self.card_parse = self.make("h264parse", "card_h264_parse")
        self.card_parse.set_property("config-interval", -1)
        self.card_caps = self.make("capsfilter", "card_h264_caps")
        self.card_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-h264,stream-format=(string)byte-stream,alignment=(string)au"),
        )
        self.card_queue = self.make("queue", "card_video_queue")
        self.card_queue.set_property("max-size-time", 2 * Gst.SECOND)
        self.card_queue.set_property("max-size-bytes", 0)
        self.card_queue.set_property("max-size-buffers", 0)

        self.output_parse = self.make("h264parse", "selected_h264_parse")
        self.output_parse.set_property("config-interval", -1)
        self.output_caps = self.make("capsfilter", "selected_h264_caps")
        self.output_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-h264,stream-format=(string)byte-stream,alignment=(string)au"),
        )
        self.mux = self.make("mpegtsmux", "youtube_mpegtsmux")
        if self.mux.find_property("alignment"):
            self.mux.set_property("alignment", 7)

        if self.test_mode:
            self.sink = self.make("fakesink", "test_sink")
            self.sink.set_property("sync", True)
        else:
            self.sink = self.make("udpsink", "selected_program_udp")
            self.sink.set_property("host", "127.0.0.1")
            self.sink.set_property("port", self.output_port)
            self.sink.set_property("sync", True)
            self.sink.set_property("async", False)

        for element in (
            self.src,
            input_queue,
            self.demux,
            self.live_queue,
            self.live_parse,
            self.live_caps,
            self.audio_queue,
            self.audio_parse,
            self.card,
            self.card_parse,
            self.card_caps,
            self.card_queue,
            self.selector,
            self.output_parse,
            self.output_caps,
            self.mux,
            self.sink,
        ):
            self.pipeline.add(element)

        if not self.src.link(input_queue) or not input_queue.link(self.demux):
            raise RuntimeError("could not link MPEG-TS input")
        if not self.live_queue.link(self.live_parse) or not self.live_parse.link(self.live_caps):
            raise RuntimeError("could not link live video parser")
        if not self.audio_queue.link(self.audio_parse):
            raise RuntimeError("could not link live audio parser")
        if (
            not self.card.link(self.card_parse)
            or not self.card_parse.link(self.card_caps)
            or not self.card_caps.link(self.card_queue)
        ):
            raise RuntimeError("could not link card branch")

        self.live_selector_pad = self.selector.request_pad_simple("sink_%u")
        self.card_selector_pad = self.selector.request_pad_simple("sink_%u")
        if not self.live_selector_pad or not self.card_selector_pad:
            raise RuntimeError("could not allocate input-selector pads")
        self.live_selector_pad.set_property("always-ok", True)
        self.card_selector_pad.set_property("always-ok", True)
        if self.live_caps.get_static_pad("src").link(self.live_selector_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("could not link live video to selector")
        if self.card_queue.get_static_pad("src").link(self.card_selector_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("could not link card video to selector")

        if not self.selector.link(self.output_parse) or not self.output_parse.link(self.output_caps):
            raise RuntimeError("could not link selector output")
        if not self.output_caps.link(self.mux):
            raise RuntimeError("could not link video into MPEG-TS mux")
        if not self.audio_parse.link(self.mux):
            raise RuntimeError("could not link audio into MPEG-TS mux")
        if not self.mux.link(self.sink):
            raise RuntimeError("could not link MPEG-TS mux to sink")

        self.selector.set_property("active-pad", self.live_selector_pad)
        self.demux.connect("pad-added", self._on_demux_pad)
        self.live_caps.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._on_live_buffer)
        self.card_queue.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self._on_card_buffer)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    def _start_ffmpeg_transport(self) -> None:
        if self.test_mode:
            return
        if not self.upstream_target:
            raise ValueError("YouTube upstream target is required outside test mode")
        local_input = (
            f"udp://127.0.0.1:{self.output_port}"
            "?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
        )
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            os.getenv("FFMPEG_LOGLEVEL", "warning"),
            "-fflags",
            "+genpts",
            "-probesize",
            "10000000",
            "-analyzeduration",
            "10000000",
            "-i",
            local_input,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c",
            "copy",
            "-f",
            "flv",
            "-flvflags",
            "no_duration_filesize",
            self.upstream_target,
        ]
        LOG.info("starting FFmpeg copy/remux RTMPS transport on loopback port %d", self.output_port)
        self.ffmpeg = subprocess.Popen(command)
        threading.Thread(target=self._monitor_ffmpeg, daemon=True, name="ffmpeg-transport").start()

    def _monitor_ffmpeg(self) -> None:
        child = self.ffmpeg
        if child is None:
            return
        rc = child.wait()
        if not self._stopping:
            LOG.error("FFmpeg RTMPS transport exited unexpectedly rc=%d", rc)
            GLib.idle_add(self.stop, 70)

    def _on_demux_pad(self, _demux: Gst.Element, pad: Gst.Pad) -> None:
        caps = pad.get_current_caps() or pad.query_caps(None)
        caps_name = caps.to_string() if caps else ""
        if caps_name.startswith("video/x-h264") and not self.live_queue.get_static_pad("sink").is_linked():
            result = pad.link(self.live_queue.get_static_pad("sink"))
            LOG.info("linked live video pad: %s (%s)", caps_name, result.value_nick)
        elif caps_name.startswith("audio/mpeg") and not self.audio_queue.get_static_pad("sink").is_linked():
            result = pad.link(self.audio_queue.get_static_pad("sink"))
            LOG.info("linked live audio pad: %s (%s)", caps_name, result.value_nick)

    def _on_live_buffer(self, _pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        buffer = info.get_buffer()
        if buffer is not None and self.pending_mode == "live" and not (
            buffer.get_flags() & Gst.BufferFlags.DELTA_UNIT
        ):
            GLib.idle_add(self._activate_mode, "live")
        return Gst.PadProbeReturn.OK

    def _on_card_buffer(self, _pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        buffer = info.get_buffer()
        if buffer is not None and self.pending_mode == "card" and not (
            buffer.get_flags() & Gst.BufferFlags.DELTA_UNIT
        ):
            GLib.idle_add(self._activate_mode, "card")
        return Gst.PadProbeReturn.OK

    def _activate_mode(self, mode: str) -> bool:
        target = self.card_selector_pad if mode == "card" else self.live_selector_pad
        if target and (mode != self.current_mode or self.pending_mode is not None):
            self.selector.set_property("active-pad", target)
            previous = self.current_mode
            self.current_mode = mode
            self.pending_mode = None
            LOG.warning("video route switched: %s -> %s", previous, mode)
        return False

    def request_mode(self, mode: str) -> bool:
        if mode not in ("live", "card"):
            return False
        if mode == self.current_mode:
            self.pending_mode = None
            return False
        self.pending_mode = mode
        LOG.info("video route pending keyframe: %s", mode)
        return False

    def _push_card_frame(self) -> bool:
        if self._stopping:
            return False
        access_unit = self.card_aus[self.card_index]
        buffer = Gst.Buffer.new_allocate(None, len(access_unit), None)
        buffer.fill(0, access_unit)
        clock = self.pipeline.get_clock()
        if clock:
            running = max(0, clock.get_time() - self.pipeline.get_base_time())
            pts = (running // FRAME_DURATION) * FRAME_DURATION
        else:
            pts = self.card_pts
        buffer.pts = pts
        buffer.dts = pts
        buffer.duration = FRAME_DURATION
        result = self.card.emit("push-buffer", buffer)
        if result not in (Gst.FlowReturn.OK, Gst.FlowReturn.FLUSHING):
            LOG.error("card appsrc push failed: %s", result.value_nick)
            return False
        self.card_pts = pts + FRAME_DURATION
        self.card_index = (self.card_index + 1) % len(self.card_aus)
        return True

    def _poll_config_thread(self) -> None:
        try:
            request = urllib.request.Request(
                self.routing_url,
                headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "User-Agent": "FGBears-YouTube-Stream-Router/1.1",
                },
            )
            with urllib.request.urlopen(request, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            mode = "card" if desired_card(payload) else "live"
            version = payload.get("version")
            if version != self._last_config_version:
                LOG.info(
                    "routing config version=%r preset=%r trivia=%r",
                    version,
                    payload.get("activePreset"),
                    payload.get("trivia"),
                )
                self._last_config_version = version
            GLib.idle_add(self.request_mode, mode)
        except Exception as exc:
            # Safe default: never cover YouTube when routing state is uncertain.
            LOG.warning("routing poll failed; failing open to live program: %s", exc)
            GLib.idle_add(self.request_mode, "live")
        finally:
            self._poll_inflight = False

    def _schedule_poll(self) -> bool:
        if self._stopping or self.test_mode:
            return not self._stopping
        if not self._poll_inflight:
            self._poll_inflight = True
            threading.Thread(target=self._poll_config_thread, daemon=True, name="routing-poll").start()
        return True

    def _test_toggle(self) -> bool:
        if self._stopping:
            return False
        self.request_mode("card" if self.current_mode == "live" else "live")
        return True

    def _stop_after_runtime(self) -> bool:
        LOG.info("test runtime complete")
        self.stop()
        return False

    def _on_bus_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            LOG.error("GStreamer error from %s: %s (%s)", message.src.get_name(), error, debug)
            self.stop(exit_code=70)
        elif message.type == Gst.MessageType.EOS:
            LOG.error("unexpected end of stream")
            self.stop(exit_code=70)

    def stop(self, exit_code: int = 0) -> None:
        if self._stopping:
            return
        self._stopping = True
        self.exit_code = exit_code
        try:
            self.card.emit("end-of-stream")
        except Exception:
            pass
        self.pipeline.set_state(Gst.State.NULL)
        child = self.ffmpeg
        if child is not None and child.poll() is None:
            try:
                child.send_signal(signal.SIGINT)
                child.wait(timeout=5)
            except Exception:
                child.kill()
        if self.loop.is_running():
            self.loop.quit()

    def run(self) -> int:
        self.exit_code = 0
        self._start_ffmpeg_transport()
        result = self.pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            self.stop(exit_code=70)
            raise RuntimeError("GStreamer pipeline failed to enter PLAYING")
        # H.264 is already encoded; this timer only pushes encoded access units.
        GLib.timeout_add(33, self._push_card_frame)
        if self.test_mode:
            if self.test_cycle > 0:
                GLib.timeout_add(max(250, int(self.test_cycle * 1000)), self._test_toggle)
            if self.runtime > 0:
                GLib.timeout_add(max(1000, int(self.runtime * 1000)), self._stop_after_runtime)
        else:
            self._schedule_poll()
            GLib.timeout_add_seconds(2, self._schedule_poll)
        try:
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            child = self.ffmpeg
            if child is not None and child.poll() is None:
                try:
                    child.send_signal(signal.SIGINT)
                    child.wait(timeout=5)
                except Exception:
                    child.kill()
        return self.exit_code


def validate_card(path: str) -> int:
    blob = Path(path).read_bytes()
    access_units = split_h264_access_units(blob)
    idr_count = sum(1 for au in access_units if has_idr(au))
    print(
        json.dumps(
            {
                "ok": bool(access_units and idr_count),
                "accessUnits": len(access_units),
                "idrAccessUnits": idr_count,
                "bytes": len(blob),
            }
        )
    )
    return 0 if access_units and idr_count else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-port", type=int, default=0)
    parser.add_argument("--output-port", type=int, default=int(os.getenv("FGB_YOUTUBE_ROUTER_OUTPUT_PORT", str(DEFAULT_OUTPUT_PORT))))
    parser.add_argument("--card", default=os.getenv("FGB_YOUTUBE_TRIVIA_CARD_H264", DEFAULT_CARD))
    parser.add_argument("--routing-url", default=os.getenv("FGB_STREAM_ROUTING_URL", DEFAULT_ROUTING_URL))
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--test-cycle", type=float, default=0.0)
    parser.add_argument("--runtime", type=float, default=0.0)
    parser.add_argument("--validate-card", action="store_true")
    parser.add_argument("--log-level", default=os.getenv("FGB_STREAM_ROUTER_LOGLEVEL", "INFO"))
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.validate_card:
        return validate_card(args.card)

    port = args.input_port or parse_udp_port(
        os.getenv("YOUTUBE_LOCAL_UDP_URL", "udp://127.0.0.1:1939")
    )
    target = None
    if not args.test:
        key = os.getenv("YOUTUBE_STREAM_KEY", "").strip()
        base = os.getenv(
            "YOUTUBE_UPSTREAM_RTMP_BASE", "rtmps://a.rtmps.youtube.com/live2"
        ).rstrip("/")
        if not key or key == "REPLACE_WITH_YOUTUBE_STREAM_KEY":
            raise ValueError("YOUTUBE_STREAM_KEY is required")
        target = f"{base}/{key}"

    router = StreamRouter(
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
        LOG.exception("fatal router error: %s", exc)
        raise SystemExit(70)
