# YouTube v2 retired runtime

YouTube v2 was retired on 2026-09-03 after production diagnostics confirmed CPU starvation and repeated local UDP circular-buffer overruns on the one-vCPU Oracle host. It is preserved here only for provenance and rollback archaeology.

All files in this directory must remain non-executable. Production may not install, enable, start, import, or source this implementation. The authorized destination path is `services/fgbears-live/youtube-v3/`.
