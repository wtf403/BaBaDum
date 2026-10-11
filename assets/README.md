# Locally served browser assets

These files are served directly by this website, without runtime downloads from
the original game or public JavaScript CDNs.

- `native/css/ver07srfont.css` and `native/css/webfonts/*`: original Heavy and
  HeavyShadow font styles and their EOT, WOFF2, WOFF, TTF, and SVG formats from
  `https://babadum.com/css/`.
- `native/audio/sounds_fx.ogg` and `.m4a`: the original game sound-effect sprite
  from `https://babadum.com/audio/`.
- `native/img/stupid_browser_error.png` and `share.jpg`: original browser fallback
  illustration and social preview from `https://babadum.com/img/`.
- `vendor/jquery-1.10.2.min.js`: pinned jQuery 1.10.2 from Google's public CDN.
- `vendor/hanzi-writer-3.5.0.min.js`: pinned Hanzi Writer 3.5.0 from jsDelivr.
- `vendor/pinyin-pro-3.19.6.js`: pinned pinyin-pro 3.19.6 from jsDelivr.
- `vendor/webfont-1.js`: the legacy Web Font Loader from Google's public CDN.

Downloaded on 2026-10-11. Original library license notices remain in the
JavaScript files. Word recordings, artwork, and vocabulary are kept separately
under `data/library/`; this directory contains only shared application assets.

Chinese stroke animations load JSON only from `data/hanzi/`, with ordinary
character text when an entry is missing. Refresh these files after collecting
Chinese vocabulary with `python3 scripts/cache_hanzi_data.py`. The refresh tool
downloads `hanzi-writer-data@2.0`, the dataset version used by Hanzi Writer 3.5.0.
