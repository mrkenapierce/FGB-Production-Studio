# YouTube v3 creatives

Only local, approved PNG files may be rendered by the YouTube destination overlay.

The locked production key is `yt_rumble_trivia_redirect`. CI/deployment generates that PNG from `services/fgbears-live/tools/build-youtube-rumble-trivia-card.py`, resizes it once to the final 798x470 destination panel, and installs it locally before v3 starts. Runtime rendering never downloads creative media and never invokes a browser or QR generator.
