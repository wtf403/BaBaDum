import json
from pathlib import Path
import unittest
from unittest.mock import patch
from local_game import LocalGameAPI, LANGUAGES

ROOT = Path(__file__).resolve().parents[1]

class LocalGameTests(unittest.TestCase):
    def test_all_languages_and_modes_use_local_media_without_network(self):
        api = LocalGameAPI(ROOT)
        with patch('urllib.request.urlopen', side_effect=AssertionError('Runtime network request')):
            for language in LANGUAGES:
                for mode in ('chooseImage', 'oneImage', 'chooseImageSound', 'setLetters', 'shuffleGames'):
                    with self.subTest(language=language, mode=mode):
                        status, response, _ = api.handle({'type': 'getWord', 'lang': language, 'game': mode})
                        self.assertEqual(status, 200, response)
                        data = response['data']
                        self.assertEqual(len({word['word_key'] for word in data['words']}), 4)
                        self.assertTrue(all(url.startswith('/data/library/media/') and (ROOT / url[1:]).is_file() for url in data['audioUrls']))
                        self.assertIn(data['id'], [word['word_key'] for word in data['words']])
                        if data['game'] == 'setLetters':
                            self.assertEqual(data['words'][0]['word_key'], data['id'])
                            self.assertCountEqual(data['shuffle'], data['words'][0]['word'])

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
