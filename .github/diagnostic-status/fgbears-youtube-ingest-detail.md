# YouTube Ingest Detail Diagnostic

```text
CHECKED_AT=2026-08-20T07:03:03Z
SERVICE_ACTIVE=active
FFMPEG_PID_PRESENT=true
YOUTUBE_KEY_PRESENT=true
YOUTUBE_KEY_LENGTH=24

===== DNS / TLS REACHABILITY =====
108.177.121.134
142.250.125.134
142.250.152.134
142.251.184.134
142.251.189.134
172.217.214.134
172.253.155.134
173.194.206.134
CONNECTED(00000003)
New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
Verify return code: 0 (ok)

===== FFMPEG ESTABLISHED SOCKETS =====
103611 0        127.0.0.1:42074       127.0.0.1:8787  users:(("ffmpeg",pid=561798,fd=7))                       
128000 0        127.0.0.1:60100       127.0.0.1:8788  users:(("ffmpeg",pid=561798,fd=8))                       

===== CURRENT FFMPEG OUTPUT SHAPE =====
tee
[f=flv:flvflags=no_duration_filesize:onfail=abort]rtmps://a.rtmps.youtube.com/live2/[REDACTED]

===== RECENT STREAM ERRORS (REDACTED) =====
2026-08-20T06:58:06+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8080980] Error in the pull function.
2026-08-20T06:58:06+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8080980] IO error: End of file
2026-08-20T06:58:06+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:11+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad801ee70] Error in the pull function.
2026-08-20T06:58:11+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad801ee70] IO error: End of file
2026-08-20T06:58:11+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:16+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad81ca7d0] Error in the pull function.
2026-08-20T06:58:16+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad81ca7d0] IO error: End of file
2026-08-20T06:58:16+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:21+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8276f80] Error in the pull function.
2026-08-20T06:58:21+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8276f80] IO error: End of file
2026-08-20T06:58:21+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:26+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad81ec390] Error in the pull function.
2026-08-20T06:58:26+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad81ec390] IO error: End of file
2026-08-20T06:58:26+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:31+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad83183d0] Error in the pull function.
2026-08-20T06:58:31+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad83183d0] IO error: End of file
2026-08-20T06:58:31+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:37+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad80205f0] Error in the pull function.
2026-08-20T06:58:37+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad80205f0] IO error: End of file
2026-08-20T06:58:37+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:42+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad825c290] Error in the pull function.
2026-08-20T06:58:42+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad825c290] IO error: End of file
2026-08-20T06:58:42+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:47+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad80e1a60] Error in the pull function.
2026-08-20T06:58:47+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad80e1a60] IO error: End of file
2026-08-20T06:58:47+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:52+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad82d7220] Error in the pull function.
2026-08-20T06:58:52+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad82d7220] IO error: End of file
2026-08-20T06:58:52+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:58:57+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad83167e0] Error in the pull function.
2026-08-20T06:58:57+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad83167e0] IO error: End of file
2026-08-20T06:58:57+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:02+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad806a5a0] Error in the pull function.
2026-08-20T06:59:02+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad806a5a0] IO error: End of file
2026-08-20T06:59:02+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:08+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8129180] Error in the pull function.
2026-08-20T06:59:08+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8129180] IO error: End of file
2026-08-20T06:59:08+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:13+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad806a5c0] Error in the pull function.
2026-08-20T06:59:13+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad806a5c0] IO error: End of file
2026-08-20T06:59:13+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:18+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad82ab260] Error in the pull function.
2026-08-20T06:59:18+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad82ab260] IO error: End of file
2026-08-20T06:59:18+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:23+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad80c8650] Error in the pull function.
2026-08-20T06:59:23+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad80c8650] IO error: End of file
2026-08-20T06:59:23+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:28+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8311820] Error in the pull function.
2026-08-20T06:59:28+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8311820] IO error: End of file
2026-08-20T06:59:28+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:33+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8277c00] Error in the pull function.
2026-08-20T06:59:33+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8277c00] IO error: End of file
2026-08-20T06:59:33+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:39+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad809f160] Error in the pull function.
2026-08-20T06:59:39+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad809f160] IO error: End of file
2026-08-20T06:59:39+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:44+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8315360] Error in the pull function.
2026-08-20T06:59:44+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8315360] IO error: End of file
2026-08-20T06:59:44+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:49+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8083b00] Error in the pull function.
2026-08-20T06:59:49+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8083b00] IO error: End of file
2026-08-20T06:59:49+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:54+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad804c740] Error in the pull function.
2026-08-20T06:59:54+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad804c740] IO error: End of file
2026-08-20T06:59:54+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T06:59:59+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8279230] Error in the pull function.
2026-08-20T06:59:59+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8279230] IO error: End of file
2026-08-20T06:59:59+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:04+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad81fb570] Error in the pull function.
2026-08-20T07:00:04+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad81fb570] IO error: End of file
2026-08-20T07:00:04+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:09+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8063790] Error in the pull function.
2026-08-20T07:00:09+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8063790] IO error: End of file
2026-08-20T07:00:09+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:15+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad817bbb0] Error in the pull function.
2026-08-20T07:00:15+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad817bbb0] IO error: End of file
2026-08-20T07:00:15+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:20+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad80c8090] Error in the pull function.
2026-08-20T07:00:20+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad80c8090] IO error: End of file
2026-08-20T07:00:20+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:25+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad827bb30] Error in the pull function.
2026-08-20T07:00:25+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad827bb30] IO error: End of file
2026-08-20T07:00:25+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:30+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8312d60] Error in the pull function.
2026-08-20T07:00:30+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8312d60] IO error: End of file
2026-08-20T07:00:30+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:35+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad833ae00] Error in the pull function.
2026-08-20T07:00:35+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad833ae00] IO error: End of file
2026-08-20T07:00:35+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:35+00:00 fgbears-live systemd[1]: Stopping fgbears-live.service - FGBears TV 24/7 YouTube replay stream...
2026-08-20T07:00:40+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8123c00] Error in the pull function.
2026-08-20T07:00:40+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8123c00] IO error: End of file
2026-08-20T07:00:40+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:46+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8312980] Error in the pull function.
2026-08-20T07:00:46+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8312980] IO error: End of file
2026-08-20T07:00:46+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:51+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8277560] Error in the pull function.
2026-08-20T07:00:51+00:00 fgbears-live fgbears-start-stream[561149]: [tls @ 0xe32ad8277560] IO error: End of file
2026-08-20T07:00:51+00:00 fgbears-live fgbears-start-stream[561149]: [fifo @ 0xb3042a77ae00] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:00:55+00:00 fgbears-live systemd[1]: fgbears-live.service: State 'stop-sigterm' timed out. Killing.
2026-08-20T07:00:56+00:00 fgbears-live systemd[1]: fgbears-live.service: Failed with result 'timeout'.
2026-08-20T07:00:56+00:00 fgbears-live systemd[1]: Stopped fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-20T07:00:56+00:00 fgbears-live systemd[1]: Started fgbears-live.service - FGBears TV 24/7 YouTube replay stream.
2026-08-20T07:00:56+00:00 fgbears-live fgbears-start-stream[561756]: FGBears Live output: YouTube primary X.
2026-08-20T07:01:01+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c0012a0] Error in the pull function.
2026-08-20T07:01:01+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c0012a0] IO error: End of file
2026-08-20T07:01:01+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:01+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c270330] Error in the pull function.
2026-08-20T07:01:01+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c270330] IO error: End of file
2026-08-20T07:01:01+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:06+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1ed1a0] Error in the pull function.
2026-08-20T07:01:06+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1ed1a0] IO error: End of file
2026-08-20T07:01:06+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:11+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c02a840] Error in the pull function.
2026-08-20T07:01:11+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c02a840] IO error: End of file
2026-08-20T07:01:11+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:16+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1ddb40] Error in the pull function.
2026-08-20T07:01:16+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1ddb40] IO error: End of file
2026-08-20T07:01:16+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:21+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c0cff30] Error in the pull function.
2026-08-20T07:01:21+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c0cff30] IO error: End of file
2026-08-20T07:01:21+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:26+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c062760] Error in the pull function.
2026-08-20T07:01:26+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c062760] IO error: End of file
2026-08-20T07:01:26+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:32+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1362a0] Error in the pull function.
2026-08-20T07:01:32+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1362a0] IO error: End of file
2026-08-20T07:01:32+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:37+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1c2b10] Error in the pull function.
2026-08-20T07:01:37+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1c2b10] IO error: End of file
2026-08-20T07:01:37+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:42+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2ffd40] Error in the pull function.
2026-08-20T07:01:42+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2ffd40] IO error: End of file
2026-08-20T07:01:42+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:47+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1d3c60] Error in the pull function.
2026-08-20T07:01:47+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1d3c60] IO error: End of file
2026-08-20T07:01:47+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:52+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1853f0] Error in the pull function.
2026-08-20T07:01:52+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1853f0] IO error: End of file
2026-08-20T07:01:52+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:01:57+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2b9350] Error in the pull function.
2026-08-20T07:01:57+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2b9350] IO error: End of file
2026-08-20T07:01:57+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:02+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c320a70] Error in the pull function.
2026-08-20T07:02:02+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c320a70] IO error: End of file
2026-08-20T07:02:02+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:08+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1ed4c0] Error in the pull function.
2026-08-20T07:02:08+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1ed4c0] IO error: End of file
2026-08-20T07:02:08+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:13+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2ddd40] Error in the pull function.
2026-08-20T07:02:13+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2ddd40] IO error: End of file
2026-08-20T07:02:13+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:18+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c123c20] Error in the pull function.
2026-08-20T07:02:18+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c123c20] IO error: End of file
2026-08-20T07:02:18+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:23+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c0eaa30] Error in the pull function.
2026-08-20T07:02:23+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c0eaa30] IO error: End of file
2026-08-20T07:02:23+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:28+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2b0430] Error in the pull function.
2026-08-20T07:02:28+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2b0430] IO error: End of file
2026-08-20T07:02:28+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:33+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c268be0] Error in the pull function.
2026-08-20T07:02:33+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c268be0] IO error: End of file
2026-08-20T07:02:33+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:39+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1895f0] Error in the pull function.
2026-08-20T07:02:39+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1895f0] IO error: End of file
2026-08-20T07:02:39+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:44+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c29efa0] Error in the pull function.
2026-08-20T07:02:44+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c29efa0] IO error: End of file
2026-08-20T07:02:44+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:49+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c26d1e0] Error in the pull function.
2026-08-20T07:02:49+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c26d1e0] IO error: End of file
2026-08-20T07:02:49+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:54+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2579f0] Error in the pull function.
2026-08-20T07:02:54+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c2579f0] IO error: End of file
2026-08-20T07:02:54+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
2026-08-20T07:02:59+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1e5fb0] Error in the pull function.
2026-08-20T07:02:59+00:00 fgbears-live fgbears-start-stream[561798]: [tls @ 0xfbbd4c1e5fb0] IO error: End of file
2026-08-20T07:02:59+00:00 fgbears-live fgbears-start-stream[561798]: [fifo @ 0xbef1bf0c9100] Error opening rtmps://a.rtmps.youtube.com/live2/[REDACTED] Input/output error
```
