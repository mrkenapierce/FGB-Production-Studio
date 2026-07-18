# Produced Shorts Generator — Implementation Decisions

Date: July 18, 2026

## Objective

Turn long-form FGB, FGBars, and EPIC episode footage into separate produced Shorts rather than only generating suggested timestamps and metadata.

## Decisions

1. **Build in the existing FGB Production Studio repository.** It already contains the approved one-word caption renderer and production assets. The older Lovable clip interface remains a planning prototype and is not the canonical production engine.
2. **Use local source files.** The YouTube URL is stored as a reference and included in metadata. The application does not act as a generic YouTube downloader. This preserves source quality and avoids building around an unreliable or unauthorized download pathway.
3. **Require time-coded captions for the first functional release.** SRT, VTT, and timestamped TXT are supported. This makes clip selection and one-word caption timing deterministic without requiring a cloud transcription account.
4. **Produce finished files immediately.** The generator ranks coherent transcript windows, prevents substantial overlap and duplicate ideas, renders portrait MP4s, and writes separate metadata files in one operation.
5. **Preserve the locked caption protocol.** Captions appear one word at a time in `#C83803` with a black outline, black shadow, condensed bold italic styling, and lower-middle safe placement.
6. **Preserve the full source frame by default.** Landscape footage is shown over a blurred portrait background. Center-crop mode is available when a full-frame portrait crop is preferable.
7. **Keep every video separate.** Each Short has its own MP4, JSON, TXT, caption JSON, and reproducible FFmpeg filter file. No combined montage is created.
8. **Keep publishing manual.** The generator prepares copy-ready titles, descriptions, hashtags, pinned comments, and source timestamps, but does not publish automatically.

## Next Expansion Candidates

- Add local or cloud speech-to-text so a separate transcript file is optional.
- Add a candidate-review screen before rendering, with editable in/out points.
- Add face-aware portrait crop tracking.
- Add YouTube OAuth only for owned-channel metadata and caption access, not generic downloading.
- Add per-project title-generation rules and release-order recommendations.
