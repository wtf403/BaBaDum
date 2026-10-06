# Arabic learning

Select the **ع** language icon, or open `/play/?lang=100&game=1`.

Arabic is local language ID 100. The app requests English (ID 1) rounds from
Ba Ba Dum, batches all choice labels through the existing DeepL proxy with
`source_lang=EN` and `target_lang=AR`, then queues the translated round. Picture
and answer IDs are preserved. Up to three rounds are buffered, with one request
in flight. Translations persist in browser storage under `arabicTranslations-v1`.
Delete that key to refresh translations after corrections or provider changes.

The Python server supports batches and reads `DEEPL_API_KEY` from its environment;
it also accepts the existing `Config.deepl.apiKey` for compatibility. Restart the
server after updating `server.py`. No new service dependency is required.

Arabic text is drawn as a complete joined word using an Arabic-capable system
font. Picture choice and word choice work without speech. Listening uses an
installed browser/device Arabic voice. Without one, listening falls back to
picture choice with a visible explanation. Spelling also falls back to picture
choice; mixed games choose among supported modes.

Arabic answers and points are local and aren't submitted to Ba Ba Dum's English
leaderboard. Automatic translations can choose the wrong sense of an isolated
word and don't guarantee vowel marks. Rounds with identical translated labels
for different answers are skipped, with a finite limit and retry button. API
failures show a retry button and never display an untranslated English round.
Changing language or game discards stale pending rounds.

Validation:

```
node --test tests/arabic.test.js
node --check app.js
node --check arabic.js
python3 -m unittest discover -s tests -p 'test_*.py'
```
