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

## Follow-up investigation

The live first-party JavaScript bundle at
`https://babadum.com/js/b7ea763.js` was inspected directly, rather than relying
only on the local modified copy. Its gameplay fetch path is the same `getWord`
request described above. It does not publish a separate translation/audio lookup
request, a vocabulary JSON asset, or a word selector used by the client.

Other modest discovery checks did not produce a complete recording index:

- A normal public `category=utils&type=getStats` request returns easiest/hardest
  words by language, with fields `lang_code`, `word`, `img`, `OK`, and `KO`.
  It does not include the localized record ID or `audio_file`. Its image endpoint
  (`getStatsImg`) is used only to retrieve SVG artwork.
- `https://babadum.com/audio/fr/` returns a “You shall not pass!” page, so the
  audio directory does not offer a usable public filename listing.
- `https://babadum.com/robots.txt` contains no sitemap or vocabulary discovery
  links. `https://babadum.com/sitemap.xml` serves the regular homepage rather
  than a vocabulary index.
- The published `https://babadum.com/ChangeLog.php` describes translations stored
  in MySQL and the addition of language support, but publishes no dictionary or
  deterministic audio API.
- Search queries restricted to the first-party domain did not find indexed
  metadata for `brouette_8346`.

The supported public client path therefore still cannot select the exact current
concept in a second language. A deterministic lookup would require a separate
trusted vocabulary/recording mapping or a newly established first-party lookup
interface. No random-round scanning, large download, or undocumented database
access was used. All 12 localized records in the three retained sample responses
have `audio_file`, and all suffixes equal their respective localized `id`.

### Progress and alternate-mode checks

A further investigation checked the actual first-party progress request names
used in the client, with no authenticated account:

- `category=utils&type=getProgress&onReceiveLocation=BumInfo` returned
  `{"type":"getProgress","onReceiveLocation":"BumInfo","progress_access_limit":1}`.
- `category=utils&type=getProgressdemo&onReceiveLocation=BumInfo` returned only
  `type`, `onReceiveLocation`, and cached `html`. The approximately 592 KB HTML
  consists largely of inline SVG flags/icons and aggregate points/learned-word
  percentages. It contains no audio metadata, no `word_key`, and no resource or
  lookup links. It is not a vocabulary export.
- The supported alternate `oneImage` game was tested using a known Spanish
  concept and full known recording metadata:
  `lang=4&game=oneImage&id=1253&word_key=1253&word_id=3141&word=volar&audio=volar_3141&a=3141`.
  It returned concept `1375`, `el radio`, `radio_5158` rather than `volar`.
  Thus the tested selectors are ignored in that mode too. Its four response
  choices still each contain localized `audio_file` metadata; changing game
  mode does not provide a second-language lookup.

No source-discovered supported endpoint provides the complete dictionary or
selects a localized recording for an arbitrary known concept. The tested paths
can supply metadata for whichever random round the server chooses. This is a
bounded investigation of supported public client behavior, not proof about every
undocumented server interface.

### Existing exporter repository

The public third-party repository
`https://github.com/wrongplanetrightgame/babadum2anki` was also checked as a
possible source of an already generated mapping. Its current `data/` directory
contains only `.gitignore`, it publishes no GitHub releases, and it has only the
`master` branch. Limited history inspection found one commit touching `data/`
(“Data folder”), rather than a removed vocabulary export. The sole listed public
fork, `rpaaron/babadum2anki`, likewise contains only `data/.gitignore`. No usable
dataset was recovered from these inventories. This observation concerns that
repository's published artifacts; its exporter source is a separate lead.

### Spanish deck availability

The exporter README's Spanish deck link,
`https://ankiweb.net/shared/info/222240580`, was investigated for an existing
Spanish word-to-recording index. The current AnkiWeb page is a JavaScript shell.
Its public frontend requests
`https://ankiweb.net/svc/shared/item-info?sharedId=222240580`; the response is
protobuf bytes `10 01`, which its published schema decodes as `missing: true`.
Thus the deck currently provides neither a download key nor size/package metadata.
No deck package or audio files were downloaded.

The public AnkiWeb shared-deck search endpoint returned empty responses for both
`search=babadum` and `search=Ba%20Ba%20Dum`. A broader `Spanish 1500` search found
an unrelated contextual vocabulary deck rather than the game's recording index.
No recoverable Spanish recording map was found through this current catalog.
