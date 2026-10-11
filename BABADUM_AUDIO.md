# Original Ba Ba Dum translation recordings

Investigated 2026-10-11 against the public first-party site and API.

## Findings

The audio filename suffix identifies a **localized word record**, not the shared
concept. In responses from `https://babadum.com/get.php`, each `words[]` record has:

- `word_key`: the shared vocabulary/concept ID.
- `id`: the localized record ID; this matches the suffix in `audio_file`.
- `word`: the localized written word, which may include an article.
- `audio_file`: the exact recording filename stem (without the extension).

For example, a real Spanish API response contained:

```json
{"word_key":"1253","id":"3141","word":"volar","lang_key":4,"audio_file":"volar_3141"}
```

The round's `data.id` was `1253`, and `data.audio` was `volar_3141`.
Another French response contained:

```json
{"word_key":"277","id":"6508","word":"le compas","lang_key":5,"audio_file":"compas_6508"}
```

The provided URL `https://babadum.com/audio/fr/brouette_8346.ogg` returned
HTTP 200, `Content-Type: audio/ogg`, `Content-Length: 11476`, and
`Access-Control-Allow-Origin: *`. Its `8346` follows the localized-record naming
pattern above. We did not retrieve the `brouette` metadata itself, so its shared
`word_key` remains unknown.

Changing `fr` to `es` and translating the filename cannot reliably select the
Spanish recording: the Spanish localized record has its own ID and may have a
different filename normalization. Use the target language's exact `audio_file`.

## Current API behavior

The app's normal request is a form POST:

```text
type=getWord&category=words&lang=4&game=chooseImage&onReceiveLocation=Words
```

Language IDs `4` and `5` are Spanish and French respectively (confirmed by both
the page's `Langs` mapping and API responses). This returns a new game round with
four localized records and one selected concept. It is not a translation lookup.

Two small targeted probes failed to select the requested word:

| Language | Additional parameters | Returned selected concept |
| --- | --- | --- |
| Spanish, `lang=4` | `id=1253&word_key=1253&word_id=1253&word=1253` | `306`, `la magdalena`, `magdalena_3182` |
| French, `lang=5` | `id=8346&word_key=1&audio=brouette_8346` | `277`, `le compas`, `compas_6508` |

These parameters were ignored for selection. The first-party client uses
`getWord` without a word selector. This is evidence that the **currently used
API does not support deterministic lookup through these parameters**; it does
not prove that no undocumented endpoint or parameter exists.

## Implementation implication

Original recordings can be used safely when a trusted mapping already provides
`(language, word_key) -> audio_file`. Cache actual metadata received during normal
gameplay and prefer it when the same concept is later needed in that language.
Keep speech synthesis as a fallback for cache misses. Fetching random rounds
until a matching word appears is inefficient and should not happen per answer.

## First-party references

- Homepage and language mapping: https://babadum.com/
- Public game API: https://babadum.com/get.php (form POST required)
- User-provided recording: https://babadum.com/audio/fr/brouette_8346.ogg
- The local copy of the original client uses `Words.get`, `Words.loadAudio`, and
  `AJAX.post` in `app.js`; it constructs audio URLs using the server-provided
  `data.lang` and `data.audio`, without deriving a translation filename.
