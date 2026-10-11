# Local game hosting

Browser gameplay uses `/api/game` on this host. Rounds are generated from
`data/library/vocabulary.json`; only entries with a downloaded picture and at
least one recording are eligible. All 21 native languages need at least four
eligible words. Arabic continues to translate local English rounds through the
existing DeepL proxy and uses browser speech where native audio is unavailable.

Native recordings, pictures, fonts, sound effects, JavaScript libraries, and
Chinese stroke data are served locally. Translation audio prefers downloaded
recordings. With translation audio enabled, round answers are chosen from the
recorded intersection of the game and menu languages where it exists. The round
includes its translation recording to avoid stale browser catalogs. If there is
no recorded intersection, audio falls back to browser speech; observed original-site filenames
never trigger remote downloads during gameplay.

Original-site accounts and shared leaderboards are not mirrored. Points remain
on the device, and server statistics count local answers since the last restart.

## Import jobs

Only explicit import jobs contact the original site or asset providers:

- `python3 scripts/crawl_babadum.py --languages all --workers 21 --request-rate 8 --rounds-per-language 5000 --target-per-language 10000 --max-no-new 500`
- `python3 scripts/cache_interfaces.py` caches public menu translations.
- `python3 scripts/cache_hanzi_data.py` updates locally hosted Chinese strokes.

The English menu is bundled. If an imported menu is unavailable, its labels fall
back to English while preserving the selected language for translation audio.
The original menu API was unreachable during migration, so additional menu
snapshots still need importing when that service responds again.

Git versions the library and browser assets. Deployment preserves extra library
media on the destination and updates tracked files, then restarts the server.
