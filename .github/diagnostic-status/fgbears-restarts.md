# FGBears Restart Diagnostic

```text
CHECKED_AT=2026-08-18T04:50:29Z
SERVICE_STATE=active
NRESTARTS=0
ACTIVE_SINCE=Tue 2026-08-18 04:47:39 UTC
MAIN_PID=434741

===== PLAYLIST =====
PLAYLIST_COUNT=31
/srv/fgbears-live/media/FGBears-Episode-01.mp4
/srv/fgbears-live/media/FGBears-Episode-02.mp4
/srv/fgbears-live/media/FGBears-Episode-03.mp4
/srv/fgbears-live/media/FGBears-Episode-04.mp4
/srv/fgbears-live/media/FGBears-Episode-05.mp4
/srv/fgbears-live/media/FGBears-Episode-06.mp4
/srv/fgbears-live/media/FGBears-Episode-07.mp4
/srv/fgbears-live/media/FGBears-Episode-08.mp4
/srv/fgbears-live/media/FGBears-Episode-09.mp4
/srv/fgbears-live/media/FGBears-Episode-10.mp4
/srv/fgbears-live/media/FGBears-Episode-11.mp4
/srv/fgbears-live/media/FGBears-Episode-12.mp4
/srv/fgbears-live/media/FGBears-Episode-13.mp4
/srv/fgbears-live/media/FGBears-Episode-14.mp4
/srv/fgbears-live/media/FGBears-Episode-15.mp4
/srv/fgbears-live/media/FGBears-Episode-16.mp4
/srv/fgbears-live/media/FGBears-Episode-17.mp4
/srv/fgbears-live/media/FGBears-Episode-18.mp4
/srv/fgbears-live/media/FGBears-Episode-19.mp4
/srv/fgbears-live/media/FGBears-Episode-20.mp4
/srv/fgbears-live/media/FGBears-Episode-21.mp4
/srv/fgbears-live/media/FGBears-Episode-22.mp4
/srv/fgbears-live/media/FGBears-Episode-23.mp4
/srv/fgbears-live/media/FGBears-Episode-24.mp4
/srv/fgbears-live/media/FGBears-Episode-25.mp4
/srv/fgbears-live/media/FGBears-Episode-26.mp4
/srv/fgbears-live/media/FGBears-Episode-27.mp4
/srv/fgbears-live/media/FGBears-Episode-28.mp4
/srv/fgbears-live/media/FGBears-Episode-29.mp4
/srv/fgbears-live/media/FGBears-Episode-30.mp4
/srv/fgbears-live/media/FGBears-Episode-31.mp4

===== FFMPEG PROGRESS =====
PROGRESS_MTIME=1787028624
frame=3829
fps=23.51
bitrate=4289.9kbits/s
out_time_us=159500000
out_time=00:02:39.500000
speed=0.979x
progress=continue

===== GUARDED RESTART HISTORY =====
NO_GUARDED_RESTART_HISTORY

===== RESTART CIRCUIT BREAKER =====
CLOSED

===== HEALTH LOGS (6H) =====
2026-08-18T00:20:02+00:00 fgbears-live fgbears-live-health[421084]: Encoder lag warning: interval_speed=0.758x threshold=0.95x. Stream left running to avoid a restart loop.
2026-08-18T02:04:01+00:00 fgbears-live fgbears-live-health[425059]: Encoder lag warning: interval_speed=0.434x threshold=0.95x. Stream left running to avoid a restart loop.
2026-08-18T02:14:41+00:00 fgbears-live fgbears-live-health[425777]: Encoder lag warning: interval_speed=0.569x threshold=0.95x. Stream left running to avoid a restart loop.
2026-08-18T04:40:00+00:00 fgbears-live fgbears-live-health[433293]: Encoder lag warning: interval_speed=0.533x threshold=0.95x. Stream left running to avoid a restart loop.

===== SERVICE LOGS (6H) =====
2026-08-18T02:16:05+00:00 fgbears-live systemd[1]: Stopping fgbears-live.service - FGBears TV 24/7 YouTube replay stream...
2026-08-18T02:16:05+00:00 fgbears-live fgbears-start-stream[412892]:     Last message repeated 2 times
2026-08-18T02:16:05+00:00 fgbears-live fgbears-start-stream[412892]: [aost#0:1/aac @ 0xbb6449ed2350] Error submitting a packet to the muxer: Immediate exit requested
2026-08-18T02:16:05+00:00 fgbears-live fgbears-start-stream[412892]: [out#0/flv @ 0xbb6449f09930] Error muxing a packet
2026-08-18T02:16:05+00:00 fgbears-live fgbears-start-stream[412892]: [out#0/flv @ 0xbb6449f09930] Error writing trailer: Immediate exit requested
2026-08-18T02:16:05+00:00 fgbears-live fgbears-start-stream[412892]: [out#0/flv @ 0xbb6449f09930] Error closing file: Immediate exit requested
2026-08-18T02:16:05+00:00 fgbears-live fgbears-start-stream[412892]: Error closing progress log, loss of information possible: Immediate exit requested
2026-08-18T02:16:05+00:00 fgbears-live systemd[1]: fgbears-live.service: Deactivated successfully.
2026-08-18T02:16:05+00:00 fgbears-live systemd[1]: Stopped fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T02:16:05+00:00 fgbears-live systemd[1]: fgbears-live.service: Consumed 4h 47min 20.520s CPU time, 173.1M memory peak, 0B memory swap peak.
2026-08-18T02:16:05+00:00 fgbears-live systemd[1]: Started fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T02:16:08+00:00 fgbears-live fgbears-start-stream[426090]: [swscaler @ 0xb45703932170] deprecated pixel format used, make sure you did set range correctly
2026-08-18T02:16:08+00:00 fgbears-live fgbears-start-stream[426090]: [swscaler @ 0xb45703956d20] deprecated pixel format used, make sure you did set range correctly
2026-08-18T02:16:08+00:00 fgbears-live fgbears-start-stream[426090]: [swscaler @ 0xb4570397a6b0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T02:16:08+00:00 fgbears-live fgbears-start-stream[426090]: [swscaler @ 0xb45703932170] deprecated pixel format used, make sure you did set range correctly
2026-08-18T02:16:08+00:00 fgbears-live fgbears-start-stream[426090]:     Last message repeated 2 times
2026-08-18T02:16:08+00:00 fgbears-live fgbears-start-stream[426090]: [swscaler @ 0xb45703956b50] deprecated pixel format used, make sure you did set range correctly
2026-08-18T02:16:08+00:00 fgbears-live fgbears-start-stream[426090]:     Last message repeated 2 times
2026-08-18T02:16:08+00:00 fgbears-live fgbears-start-stream[426090]: [swscaler @ 0xb45703998f50] deprecated pixel format used, make sure you did set range correctly
2026-08-18T02:16:10+00:00 fgbears-live fgbears-start-stream[426090]:     Last message repeated 2 times
2026-08-18T02:16:10+00:00 fgbears-live fgbears-start-stream[426090]: [in#1/mpjpeg @ 0xb45703331340] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:36:57+00:00 fgbears-live systemd[1]: Stopping fgbears-live.service - FGBears TV 24/7 YouTube replay stream...
2026-08-18T04:36:57+00:00 fgbears-live fgbears-start-stream[426090]: [aost#0:1/aac @ 0xb45703308350] Error submitting a packet to the muxer: Immediate exit requested
2026-08-18T04:36:57+00:00 fgbears-live fgbears-start-stream[426090]: [out#0/flv @ 0xb457033270d0] Error muxing a packet
2026-08-18T04:36:57+00:00 fgbears-live fgbears-start-stream[426090]: [out#0/flv @ 0xb457033270d0] Error writing trailer: Immediate exit requested
2026-08-18T04:36:57+00:00 fgbears-live fgbears-start-stream[426090]: [out#0/flv @ 0xb457033270d0] Error closing file: Immediate exit requested
2026-08-18T04:36:57+00:00 fgbears-live fgbears-start-stream[426090]: Error closing progress log, loss of information possible: Immediate exit requested
2026-08-18T04:36:57+00:00 fgbears-live systemd[1]: fgbears-live.service: Deactivated successfully.
2026-08-18T04:36:57+00:00 fgbears-live systemd[1]: Stopped fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:36:57+00:00 fgbears-live systemd[1]: fgbears-live.service: Consumed 1h 57min 16.720s CPU time, 172.5M memory peak, 0B memory swap peak.
2026-08-18T04:36:57+00:00 fgbears-live systemd[1]: Started fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:37:00+00:00 fgbears-live fgbears-start-stream[431787]: [swscaler @ 0xc4cb62bd29d0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:00+00:00 fgbears-live fgbears-start-stream[431787]: [swscaler @ 0xc4cb62bf7580] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:00+00:00 fgbears-live fgbears-start-stream[431787]: [swscaler @ 0xc4cb62c1af10] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:00+00:00 fgbears-live fgbears-start-stream[431787]: [swscaler @ 0xc4cb62bd29d0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:00+00:00 fgbears-live fgbears-start-stream[431787]:     Last message repeated 2 times
2026-08-18T04:37:00+00:00 fgbears-live fgbears-start-stream[431787]: [swscaler @ 0xc4cb62bf73b0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:00+00:00 fgbears-live fgbears-start-stream[431787]:     Last message repeated 2 times
2026-08-18T04:37:00+00:00 fgbears-live fgbears-start-stream[431787]: [swscaler @ 0xc4cb62c397b0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:03+00:00 fgbears-live fgbears-start-stream[431787]:     Last message repeated 2 times
2026-08-18T04:37:03+00:00 fgbears-live fgbears-start-stream[431787]: [in#1/mpjpeg @ 0xc4cb625bf5c0] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:37:18+00:00 fgbears-live systemd[1]: Stopping fgbears-live.service - FGBears TV 24/7 YouTube replay stream...
2026-08-18T04:37:18+00:00 fgbears-live fgbears-start-stream[431787]: [aost#0:1/aac @ 0xc4cb625ab210] Error submitting a packet to the muxer: Immediate exit requested
2026-08-18T04:37:18+00:00 fgbears-live fgbears-start-stream[431787]: [out#0/flv @ 0xc4cb625bf950] Error muxing a packet
2026-08-18T04:37:18+00:00 fgbears-live fgbears-start-stream[431787]: [out#0/flv @ 0xc4cb625bf950] Error writing trailer: Immediate exit requested
2026-08-18T04:37:18+00:00 fgbears-live fgbears-start-stream[431787]: [out#0/flv @ 0xc4cb625bf950] Error closing file: Immediate exit requested
2026-08-18T04:37:18+00:00 fgbears-live fgbears-start-stream[431787]: Error closing progress log, loss of information possible: Immediate exit requested
2026-08-18T04:37:18+00:00 fgbears-live systemd[1]: fgbears-live.service: Deactivated successfully.
2026-08-18T04:37:18+00:00 fgbears-live systemd[1]: Stopped fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:37:18+00:00 fgbears-live systemd[1]: fgbears-live.service: Consumed 9.309s CPU time, 140.0M memory peak, 0B memory swap peak.
2026-08-18T04:37:18+00:00 fgbears-live systemd[1]: Started fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:37:21+00:00 fgbears-live fgbears-start-stream[432435]: [swscaler @ 0xb0588af8a330] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:21+00:00 fgbears-live fgbears-start-stream[432435]: [swscaler @ 0xb0588b53adf0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:21+00:00 fgbears-live fgbears-start-stream[432435]: [swscaler @ 0xb0588b565b60] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:21+00:00 fgbears-live fgbears-start-stream[432435]: [swscaler @ 0xb0588af8a330] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:21+00:00 fgbears-live fgbears-start-stream[432435]:     Last message repeated 2 times
2026-08-18T04:37:21+00:00 fgbears-live fgbears-start-stream[432435]: [swscaler @ 0xb0588b53a190] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:21+00:00 fgbears-live fgbears-start-stream[432435]:     Last message repeated 2 times
2026-08-18T04:37:21+00:00 fgbears-live fgbears-start-stream[432435]: [swscaler @ 0xb0588b565b60] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:37:23+00:00 fgbears-live fgbears-start-stream[432435]:     Last message repeated 2 times
2026-08-18T04:37:23+00:00 fgbears-live fgbears-start-stream[432435]: [in#1/mpjpeg @ 0xb0588af11270] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:37:23+00:00 fgbears-live fgbears-start-stream[432435]: [in#2/mpjpeg @ 0xb0588af22160] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:39:57+00:00 fgbears-live systemd[1]: Stopping fgbears-live.service - FGBears TV 24/7 YouTube replay stream...
2026-08-18T04:39:57+00:00 fgbears-live fgbears-start-stream[432435]: [vost#0:0/libx264 @ 0xb0588af2cbf0] Error submitting a packet to the muxer: Immediate exit requested
2026-08-18T04:39:57+00:00 fgbears-live fgbears-start-stream[432435]: [out#0/flv @ 0xb0588af30e70] Error muxing a packet
2026-08-18T04:39:57+00:00 fgbears-live fgbears-start-stream[432435]: [out#0/flv @ 0xb0588af30e70] Error writing trailer: Immediate exit requested
2026-08-18T04:39:57+00:00 fgbears-live fgbears-start-stream[432435]: [out#0/flv @ 0xb0588af30e70] Error closing file: Immediate exit requested
2026-08-18T04:39:57+00:00 fgbears-live fgbears-start-stream[432435]: Error closing progress log, loss of information possible: Immediate exit requested
2026-08-18T04:39:57+00:00 fgbears-live systemd[1]: fgbears-live.service: Deactivated successfully.
2026-08-18T04:39:57+00:00 fgbears-live systemd[1]: Stopped fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:39:57+00:00 fgbears-live systemd[1]: fgbears-live.service: Consumed 2min 10.522s CPU time, 162.8M memory peak, 0B memory swap peak.
2026-08-18T04:39:57+00:00 fgbears-live systemd[1]: Started fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:39:59+00:00 fgbears-live fgbears-start-stream[433188]: [swscaler @ 0xb4bf9fecb330] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:39:59+00:00 fgbears-live fgbears-start-stream[433188]: [swscaler @ 0xb4bfa047bdf0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:39:59+00:00 fgbears-live fgbears-start-stream[433188]: [swscaler @ 0xb4bfa04a6b60] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:39:59+00:00 fgbears-live fgbears-start-stream[433188]: [swscaler @ 0xb4bf9fecb330] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:39:59+00:00 fgbears-live fgbears-start-stream[433188]:     Last message repeated 2 times
2026-08-18T04:39:59+00:00 fgbears-live fgbears-start-stream[433188]: [swscaler @ 0xb4bfa047b190] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:39:59+00:00 fgbears-live fgbears-start-stream[433188]:     Last message repeated 2 times
2026-08-18T04:39:59+00:00 fgbears-live fgbears-start-stream[433188]: [swscaler @ 0xb4bfa04a6b60] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:40:02+00:00 fgbears-live fgbears-start-stream[433188]:     Last message repeated 2 times
2026-08-18T04:40:02+00:00 fgbears-live fgbears-start-stream[433188]: [in#1/mpjpeg @ 0xb4bf9fe52270] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:40:02+00:00 fgbears-live fgbears-start-stream[433188]: [in#2/mpjpeg @ 0xb4bf9fe63160] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:46:24+00:00 fgbears-live systemd[1]: Stopping fgbears-live.service - FGBears TV 24/7 YouTube replay stream...
2026-08-18T04:46:24+00:00 fgbears-live fgbears-start-stream[433188]: Error closing progress log, loss of information possible: Broken pipe
2026-08-18T04:46:24+00:00 fgbears-live systemd[1]: fgbears-live.service: Deactivated successfully.
2026-08-18T04:46:24+00:00 fgbears-live systemd[1]: Stopped fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:46:24+00:00 fgbears-live systemd[1]: fgbears-live.service: Consumed 5min 29.944s CPU time, 175.0M memory peak, 0B memory swap peak.
2026-08-18T04:46:24+00:00 fgbears-live systemd[1]: Started fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:46:27+00:00 fgbears-live fgbears-start-stream[434088]: [swscaler @ 0xc92cd9c275f0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:46:27+00:00 fgbears-live fgbears-start-stream[434088]: [swscaler @ 0xc92cd9c3e770] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:46:27+00:00 fgbears-live fgbears-start-stream[434088]: [swscaler @ 0xc92cd9c69eb0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:46:27+00:00 fgbears-live fgbears-start-stream[434088]: [swscaler @ 0xc92cd9c275f0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:46:27+00:00 fgbears-live fgbears-start-stream[434088]:     Last message repeated 2 times
2026-08-18T04:46:27+00:00 fgbears-live fgbears-start-stream[434088]: [swscaler @ 0xc92cd9c3e070] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:46:27+00:00 fgbears-live fgbears-start-stream[434088]:     Last message repeated 2 times
2026-08-18T04:46:27+00:00 fgbears-live fgbears-start-stream[434088]: [swscaler @ 0xc92cd9c88750] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:46:30+00:00 fgbears-live fgbears-start-stream[434088]:     Last message repeated 2 times
2026-08-18T04:46:30+00:00 fgbears-live fgbears-start-stream[434088]: [in#1/mpjpeg @ 0xc92cd9614270] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:46:30+00:00 fgbears-live fgbears-start-stream[434088]: [in#2/mpjpeg @ 0xc92cd9625160] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:47:39+00:00 fgbears-live systemd[1]: Stopping fgbears-live.service - FGBears TV 24/7 YouTube replay stream...
2026-08-18T04:47:39+00:00 fgbears-live fgbears-start-stream[434088]: Error closing progress log, loss of information possible: Broken pipe
2026-08-18T04:47:39+00:00 fgbears-live systemd[1]: fgbears-live.service: Deactivated successfully.
2026-08-18T04:47:39+00:00 fgbears-live systemd[1]: Stopped fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:47:39+00:00 fgbears-live systemd[1]: fgbears-live.service: Consumed 57.031s CPU time, 161.5M memory peak, 0B memory swap peak.
2026-08-18T04:47:39+00:00 fgbears-live systemd[1]: Started fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-18T04:47:41+00:00 fgbears-live fgbears-start-stream[434791]: [swscaler @ 0xb13182ca83f0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:47:41+00:00 fgbears-live fgbears-start-stream[434791]: [swscaler @ 0xb131832597b0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:47:41+00:00 fgbears-live fgbears-start-stream[434791]: [swscaler @ 0xb13183284ef0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:47:42+00:00 fgbears-live fgbears-start-stream[434791]: [swscaler @ 0xb13182ca83f0] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:47:42+00:00 fgbears-live fgbears-start-stream[434791]:     Last message repeated 2 times
2026-08-18T04:47:42+00:00 fgbears-live fgbears-start-stream[434791]: [swscaler @ 0xb13183255980] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:47:42+00:00 fgbears-live fgbears-start-stream[434791]:     Last message repeated 2 times
2026-08-18T04:47:42+00:00 fgbears-live fgbears-start-stream[434791]: [swscaler @ 0xb131832a3790] deprecated pixel format used, make sure you did set range correctly
2026-08-18T04:47:44+00:00 fgbears-live fgbears-start-stream[434791]:     Last message repeated 2 times
2026-08-18T04:47:44+00:00 fgbears-live fgbears-start-stream[434791]: [in#1/mpjpeg @ 0xb13182c2f270] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
2026-08-18T04:47:44+00:00 fgbears-live fgbears-start-stream[434791]: [in#2/mpjpeg @ 0xb13182c40160] Thread message queue blocking; consider raising the thread_queue_size option (current value: 8)
```
