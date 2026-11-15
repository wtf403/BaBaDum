import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from local_game import LocalGameAPI, LANGUAGES

ROOT = Path(__file__).resolve().parents[1]
AUDIO_BASE = 'https://raw.githubusercontent.com/wtf403/BaBaDum/main/data/library/'
MODES = ('chooseImage', 'oneImage', 'chooseImageSound', 'setLetters', 'shuffleGames')

class LocalGameTests(unittest.TestCase):
    def setUp(self):
        for target in ('urllib.request.urlopen', 'socket.socket.connect', 'socket.socket.connect_ex'):
            blocker = patch(target, side_effect=AssertionError('Runtime network request'))
            mocked = blocker.start()
            self.addCleanup(blocker.stop)
            self.addCleanup(mocked.assert_not_called)

    def assert_audio_urls(self, urls, language, audio_file=None, local_root=None):
        self.assertTrue(urls)
        self.assertEqual(len(urls), len(set(urls)))
        for url in urls:
            self.assertTrue(url.startswith(AUDIO_BASE), url)
            relative = url.removeprefix(AUDIO_BASE)
            self.assertRegex(relative, r'\Amedia/audio/' + language + r'/[^/\\%?#\x00-\x1f\x7f]+\.(?:ogg|m4a)\Z')
            if audio_file is not None:
                self.assertIn(relative, (f'media/audio/{language}/{audio_file}.ogg',
                                         f'media/audio/{language}/{audio_file}.m4a'))
            if local_root is not None:
                self.assertTrue((local_root / 'data/library' / relative).is_file(), url)

    def make_catalog(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        library = root / 'data/library'
        images = library / 'media/images'
        images.mkdir(parents=True)
        for concept in range(1, 5):
            (images / f'{concept}.svg').write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg"><text>{concept}</text></svg>', encoding='utf-8')
        manifest = {'version': 1, 'languages': {
            code: {'words': {str(concept): {
                'id': str(concept), 'word': f'{code} word {concept}',
                'audio_file': f'word_{concept}', 'image': f'media/images/{concept}.svg',
                'audio': f'media/audio/{code}/word_{concept}.ogg',
                'audio_alt': f'media/audio/{code}/word_{concept}.m4a',
            } for concept in range(1, 5)}} for code in ('fr', 'es')
        }}
        self.write_catalog(root, manifest)
        return root, manifest

    def write_catalog(self, root, manifest):
        (root / 'data/library/vocabulary.json').write_text(json.dumps(manifest), encoding='utf-8')

    def test_all_languages_and_modes_use_safe_github_audio_without_network(self):
        api = LocalGameAPI(ROOT)
        for language in LANGUAGES:
            for mode in MODES:
                with self.subTest(language=language, mode=mode):
                    status, response, _ = api.handle({'type': 'getWord', 'lang': language, 'game': mode})
                    self.assertEqual(status, 200, response)
                    data = response['data']
                    self.assertEqual(len({word['word_key'] for word in data['words']}), 4)
                    self.assert_audio_urls(data['audioUrls'], language, data['audio'], ROOT)
                    for word in data['words']:
                        self.assert_audio_urls(word['audioUrls'], language, word['audio_file'], ROOT)
                    self.assertIn(data['id'], [word['word_key'] for word in data['words']])
                    if data['game'] == 'setLetters':
                        self.assertEqual(data['words'][0]['word_key'], data['id'])
                        self.assertCountEqual(data['shuffle'], data['words'][0]['word'])

    def test_translation_audio_chooses_matched_pairs_in_both_directions(self):
        api = LocalGameAPI(ROOT)
        for source, target in (('fr', 'es'), ('es', 'fr')):
            for mode in MODES:
                for _ in range(20):
                    status, response, _ = api.handle({'type': 'getWord', 'lang': source, 'game': mode,
                                                     'translation_lang': target, 'play_translation': 'true'})
                    self.assertEqual(status, 200)
                    data = response['data']
                    self.assertEqual(data['nativeTranslation']['lang'], target)
                    self.assert_audio_urls(data['audioUrls'], source, data['audio'], ROOT)
                    self.assert_audio_urls(data['nativeTranslation']['audioUrls'], target, local_root=ROOT)
                    self.assertTrue(data['pairedAudioRequired'])

    def test_rounds_and_translations_need_images_but_no_local_audio(self):
        root, _ = self.make_catalog()
        api = LocalGameAPI(root)
        for source, target in (('fr', 'es'), ('es', 'fr')):
            for mode in MODES:
                for translate in (False, True):
                    with self.subTest(source=source, mode=mode, translate=translate):
                        params = {'type': 'getWord', 'lang': source, 'game': mode}
                        if translate:
                            params.update(translation_lang=target, play_translation='true')
                        status, response, _ = api.handle(params)
                        self.assertEqual(status, 200, response)
                        data = response['data']
                        self.assertEqual({word['word_key'] for word in data['words']}, {'1', '2', '3', '4'})
                        self.assert_audio_urls(data['audioUrls'], source, f'word_{data["id"]}')
                        self.assertEqual(len(data['audioUrls']), 2)
                        for word in data['words']:
                            self.assertIn('<svg', word['img'])
                            self.assert_audio_urls(word['audioUrls'], source, word['audio_file'])
                        if translate:
                            translation = data['nativeTranslation']
                            self.assertEqual(translation['lang'], target)
                            self.assertEqual(translation['word'], f'{target} word {data["id"]}')
                            self.assert_audio_urls(translation['audioUrls'], target, f'word_{data["id"]}')
                            self.assertEqual(len(translation['audioUrls']), 2)
                            self.assertTrue(data['pairedAudioRequired'])
                        else:
                            self.assertNotIn('nativeTranslation', data)
                        if data['game'] == 'setLetters':
                            self.assertEqual(data['words'][0]['word_key'], data['id'])
                            self.assertCountEqual(data['shuffle'], data['words'][0]['word'])
        files = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
        self.assertEqual(files, {'data/library/vocabulary.json'} |
                         {f'data/library/media/images/{concept}.svg' for concept in range(1, 5)})

    def test_audio_and_audio_alt_accept_either_format_and_deduplicate(self):
        for audio, audio_alt, extensions in (
                ('.ogg', '.m4a', ('.ogg', '.m4a')),
                ('.m4a', '.ogg', ('.m4a', '.ogg')),
                ('.m4a', None, ('.m4a',)),
                (None, '.ogg', ('.ogg',)),
                (None, '.m4a', ('.m4a',)),
                ('.ogg', '.ogg', ('.ogg',)),
                ('invalid', '.m4a', ('.m4a',)),
                ('.ogg', 'invalid', ('.ogg',))):
            with self.subTest(audio=audio, audio_alt=audio_alt):
                root, manifest = self.make_catalog()
                for code, language in manifest['languages'].items():
                    for entry in language['words'].values():
                        for field, extension in (('audio', audio), ('audio_alt', audio_alt)):
                            if extension is None:
                                entry.pop(field)
                            else:
                                entry[field] = f'media/audio/{code}/{entry["audio_file"]}{extension}'
                self.write_catalog(root, manifest)
                api = LocalGameAPI(root)
                status, response, _ = api.handle({'type': 'getWord', 'lang': 'fr',
                                                 'translation_lang': 'es', 'play_translation': 'true'})
                self.assertEqual(status, 200, response)
                data = response['data']
                for code, urls in (('fr', data['audioUrls']), ('es', data['nativeTranslation']['audioUrls'])):
                    self.assertEqual(urls, [f'{AUDIO_BASE}media/audio/{code}/word_{data["id"]}{ext}'
                                            for ext in extensions])

    def test_invalid_audio_paths_are_excluded(self):
        invalid_paths = (
            None, 42, [], {}, '', 'word_1.ogg', '/media/audio/fr/word_1.ogg',
            AUDIO_BASE + 'media/audio/fr/word_1.ogg',
            'media/audio/fr/../fr/word_1.ogg', 'media/audio/fr/./word_1.ogg',
            'media/audio/fr/../../word_1.ogg', 'media/audio/fr/%2e%2e/word_1.ogg',
            'media/audio/fr\\word_1.ogg', 'media/audio/fr//word_1.ogg',
            'media/audio/es/word_1.ogg', 'media/audio/FR/word_1.ogg',
            'media/audio/fr/word_2.ogg', 'media/audio/fr/word_1.mp3',
            'media/audio/fr/word_1.OGG', 'media/audio/fr/word_1.ogg.exe',
            'media/audio/fr/word_1.ogg?download=1', 'media/audio/fr/word_1.ogg#fragment',
            'media/audio/fr/word_1.ogg\x00', 'media/audio/fr/word_1.ogg\n',
        )
        for field in ('audio', 'audio_alt'):
            for relative in invalid_paths:
                with self.subTest(field=field, relative=relative):
                    root, manifest = self.make_catalog()
                    entry = manifest['languages']['fr']['words']['1']
                    entry.pop('audio')
                    entry.pop('audio_alt')
                    entry[field] = relative
                    self.write_catalog(root, manifest)
                    api = LocalGameAPI(root)
                    self.assertEqual({record['word_key'] for record in api.catalog.snapshot()['fr']},
                                     {'2', '3', '4'})
                    status, response, _ = api.handle({'type': 'getWord', 'lang': 'fr'})
                    self.assertEqual(status, 503, response)
                    self.assertEqual(response['code'], 'language_incomplete')

    def test_invalid_audio_filenames_are_excluded_even_when_paths_match(self):
        for filename in (None, 42, '', '../word_1', 'nested/word_1', 'nested\\word_1',
                         'word%2f1', 'word?1', 'word#1', 'word\x001', 'word\n1', 'word\x7f1'):
            with self.subTest(filename=filename):
                root, manifest = self.make_catalog()
                entry = manifest['languages']['fr']['words']['1']
                entry['audio_file'] = filename
                entry['audio'] = f'media/audio/fr/{filename}.ogg'
                entry['audio_alt'] = f'media/audio/fr/{filename}.m4a'
                self.write_catalog(root, manifest)
                api = LocalGameAPI(root)
                self.assertEqual({record['word_key'] for record in api.catalog.snapshot()['fr']},
                                 {'2', '3', '4'})
                status, response, _ = api.handle({'type': 'getWord', 'lang': 'fr'})
                self.assertEqual(status, 503, response)
                self.assertEqual(response['code'], 'language_incomplete')

    def test_missing_local_images_are_still_excluded(self):
        root, _ = self.make_catalog()
        (root / 'data/library/media/images/1.svg').unlink()
        api = LocalGameAPI(root)
        for code in ('fr', 'es'):
            with self.subTest(language=code):
                self.assertEqual({record['word_key'] for record in api.catalog.snapshot()[code]},
                                 {'2', '3', '4'})
                status, response, _ = api.handle({'type': 'getWord', 'lang': code})
                self.assertEqual(status, 503, response)
                self.assertEqual(response['code'], 'language_incomplete')

    def test_interface_fallback_preserves_translation_language(self):
        api = LocalGameAPI(ROOT)
        for code in ('es', 'fr', 'ar', 'jp'):
            status, response, _ = api.handle({'category': 'utils', 'type': 'changeLang', 'lang_code': code})
            self.assertEqual(status, 200)
            self.assertEqual(response['interface']['lang_code'], code)
            self.assertIn('play', response['interface'])

    def test_invalid_and_incomplete_language_do_not_request_upstream(self):
        api = LocalGameAPI(ROOT)
        status, response, _ = api.handle({'type': 'getWord', 'lang': 'not-a-language'})
        self.assertEqual(status, 503)
        self.assertEqual(response['code'], 'language_unavailable')

if __name__ == '__main__':
    unittest.main()
