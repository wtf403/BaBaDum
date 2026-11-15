"""Native game rounds and utility responses served entirely from local files."""

from collections import Counter, OrderedDict
import copy
import json
from pathlib import Path
import random
import re
import secrets
import threading
import time


LANGUAGES = {"es": 4, "gb": 7, "us": 1, "pl": 2, "de": 3, "fr": 5,
             "it": 6, "ru": 8, "jp": 9, "se": 10, "gr": 11, "cz": 14,
             "lt": 15, "pt": 16, "ro": 18, "hu": 23, "da": 12, "cn": 13,
             "eo": 24, "tr": 25, "uk": 26}
MODES = {"chooseImage": ("1", 1), "chooseImageSound": ("2", 2),
         "setLetters": ("3", 6), "oneImage": ("4", 3)}
COLORS = set(map(str, [1] + list(range(3, 24)) + list(range(26, 36))))
PLACEHOLDER = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><circle class="fill" cx="100" cy="100" r="80"/><path class="stroke" fill="none" stroke-width="8" d="M60 115Q100 155 140 115"/></svg>'


class GameUnavailable(Exception):
    def __init__(self, message, code="library_unavailable", status=503):
        super().__init__(message)
        self.code = code
        self.status = status


class VocabularyCatalog:
    """Immutable snapshots replaced under a lock after an atomic manifest update."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / "vocabulary.json"
        self.lock = threading.RLock()
        self.signature = None
        self.languages = {}

    def media_path(self, relative):
        if not isinstance(relative, str) or not relative.startswith("media/"):
            return None
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            return None
        return path if path.is_file() and path.stat().st_size else None

    def snapshot(self):
        with self.lock:
            try:
                stat = self.path.stat()
                signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
                if signature == self.signature:
                    return self.languages
                manifest = json.loads(self.path.read_text("utf-8"))
                if manifest.get("version") != 1 or not isinstance(manifest.get("languages"), dict):
                    raise ValueError("unsupported manifest")
                languages = {}
                for code, language in manifest["languages"].items():
                    if code not in LANGUAGES or not isinstance(language, dict):
                        continue
                    records = []
                    for concept, entry in language.get("words", {}).items():
                        if (not isinstance(entry, dict) or not re.fullmatch(r"[0-9]+", str(concept)) or
                                not re.fullmatch(r"[0-9]+", str(entry.get("id", ""))) or
                                not isinstance(entry.get("word"), str) or not entry["word"].strip() or
                                not isinstance(entry.get("audio_file"), str) or
                                not re.fullmatch(r"[^/\\%?#\x00-\x1f\x7f]+", entry["audio_file"])):
                            continue
                        image = entry.get("image")
                        if image != "media/images/" + str(concept) + ".svg" or not self.media_path(image):
                            continue
                        audio = []
                        for name in ("audio", "audio_alt"):
                            relative = entry.get(name)
                            if (isinstance(relative, str) and relative in (
                                    "media/audio/{}/{}.ogg".format(code, entry["audio_file"]),
                                    "media/audio/{}/{}.m4a".format(code, entry["audio_file"])) and
                                    self.media_path(relative)):
                                audio.append("https://raw.githubusercontent.com/wtf403/BaBaDum/main/data/library/" + relative)
                        if not audio:
                            continue
                        color = str(entry.get("color_key", "12"))
                        records.append({"word_key": str(concept), "id": str(entry["id"]),
                                        "word": entry["word"], "lang_key": LANGUAGES[code],
                                        "audio_file": entry["audio_file"], "audioUrls": list(dict.fromkeys(audio)),
                                        "color_key": color if color in COLORS else "12", "level": "0",
                                        "image": image})
                    languages[code] = tuple(records)
                self.languages = languages
                self.signature = signature
            except (OSError, ValueError, AttributeError):
                # Keep the last coherent snapshot across an interrupted update.
                pass
            return self.languages

    def image(self, relative):
        path = self.media_path(relative)
        if path is None:
            raise GameUnavailable("A local picture is missing. Continue collection and retry.")
        try:
            svg = path.read_text("utf-8")
        except (OSError, UnicodeError) as error:
            raise GameUnavailable("A local picture could not be read.") from error
        if "<svg" not in svg:
            raise GameUnavailable("A local picture is invalid.")
        return svg


class LocalGameAPI:
    def __init__(self, root, rng=None):
        self.root = Path(root)
        self.catalog = VocabularyCatalog(self.root / "data/library")
        self.snapshots = self.root / "data/local-api"
        self.rng = rng or random.SystemRandom()
        self.lock = threading.RLock()
        self.rounds = OrderedDict()
        self.answers = Counter()
        self.correct = Counter()

    def envelope(self, params):
        result = {"type": str(params.get("type", "")), "local": True}
        for name in ("onReceiveLocation", "connectId"):
            if name in params:
                result[name] = params[name]
        return result

    def load_json(self, path):
        try:
            value = json.loads(path.read_text("utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def interface(self, code):
        code = code if isinstance(code, str) and re.fullmatch(r"[a-z]{2}", code) else "us"
        value = self.load_json(self.snapshots / "interfaces" / (code + ".json"))
        if value is None:
            value = self.load_json(self.snapshots / "interfaces/us.json") or {}
        interface = copy.deepcopy(value.get("interface", value))
        interface["lang_code"] = code
        return interface

    def get_word(self, params):
        languages = self.catalog.snapshot()
        requested = str(params.get("lang", "1"))
        code = next((code for code, key in LANGUAGES.items() if requested in (code, str(key))), None)
        if requested in ("0", "shuffleLang"):
            available = [code for code, words in languages.items() if len(words) >= 4]
            code = self.rng.choice(available) if available else None
        if code is None:
            raise GameUnavailable("This language has no local native library.", "language_unavailable")
        records = languages.get(code, ())
        # Four distinct labels avoid ambiguous answers for separate pictures.
        unique = {}
        for record in records:
            unique.setdefault(record["word"].casefold().strip(), record)
        if len(unique) < 4:
            raise GameUnavailable("This language needs at least four downloaded words, pictures, and recordings.",
                                  "language_incomplete")
        game = str(params.get("game", "chooseImage"))
        aliases = {"1": "chooseImage", "2": "chooseImageSound", "3": "setLetters", "4": "oneImage",
                   "5": "shuffleGames", "chooseWord": "oneImage", "shuffle": "shuffleGames"}
        game = aliases.get(game, game)
        if game == "shuffleGames":
            game = self.rng.choice(list(MODES))
        if game not in MODES:
            raise GameUnavailable("This game is not available in the local library.", "unsupported_game", 400)
        target = str(params.get("translation_lang", "")).lower()
        translations = {record["word_key"]: record for record in languages.get(target, ())}
        paired = [record for record in unique.values() if record["word_key"] in translations]
        require_translation = str(params.get("play_translation", "false")).lower() == "true"
        answer = self.rng.choice(paired if require_translation and paired else list(unique.values()))
        chosen = [answer] + self.rng.sample([record for record in unique.values()
                                           if record["word_key"] != answer["word_key"]], 3)
        if game != "setLetters":
            self.rng.shuffle(chosen)
        words = []
        for record in chosen:
            word = dict(record)
            word["img"] = self.catalog.image(word.pop("image"))
            words.append(word)
        token = secrets.token_urlsafe(18)
        with self.lock:
            self.rounds[token] = {"answer": answer["id"], "word": answer["word"], "lang": code,
                                  "game": game, "time": time.monotonic()}
            while len(self.rounds) > 10000:
                self.rounds.popitem(last=False)
        result = {"id": answer["word_key"], "audio": answer["audio_file"],
                  "pairingMenuCode": target, "pairedAudioRequired": require_translation,
                  "audioUrls": answer["audioUrls"], "lang": code, "lang_key": LANGUAGES[code],
                  "color": answer["color_key"], "game": game, "words": words,
                  "real_m": MODES[game][1], "p_id": token, "local": True}
        translation = translations.get(answer["word_key"])
        if translation:
            result["nativeTranslation"] = {"lang": target, "word": translation["word"],
                                           "audioUrls": translation["audioUrls"]}
        if game == "setLetters":
            letters = list(answer["word"])
            self.rng.shuffle(letters)
            if "".join(letters) == answer["word"] and len(letters) > 1:
                letters = letters[1:] + letters[:1]
            result["shuffle"] = "".join(letters)
        return result

    def answer(self, params):
        with self.lock:
            saved = self.rounds.pop(str(params.get("p_id", "")), None)
            if saved is None or time.monotonic() - saved["time"] > 7200:
                return {"accepted": False, "reason": "round_expired"}
            if (str(params.get("lang_id")) != str(LANGUAGES[saved["lang"]]) or
                    str(params.get("game_id")) != MODES[saved["game"]][0]):
                return {"accepted": False, "reason": "round_mismatch"}
            expected = saved["word"] if saved["game"] == "setLetters" else saved["answer"]
            correct = str(params.get("a", "")) == expected
            key = (saved["lang"], saved["game"])
            self.answers[key] += 1
            self.correct[key] += int(correct)
            return {"accepted": True, "correct": correct}

    def stats(self):
        with self.lock:
            answers, correct = self.answers.copy(), self.correct.copy()
        def counts(keys):
            total = sum(answers[key] for key in keys)
            ok = sum(correct[key] for key in keys)
            return {"OK": str(ok), "KO": str(total - ok)}
        labels = {"stats_h1": "Local statistics", "stats_h2_num": "Answers on this server since restart",
                  "stats_h2_langs": "Languages", "stats_h2_games": "Games", "stats_total": "Total",
                  "stats_h2_easy": "", "stats_h2_hard": "", "stats_h2_cAllTime": "Local play",
                  "stats_others": "Other"}
        local = [{"code": "lo", "country": "This server", "percent": 100}]
        return {"h": labels, "count": counts(answers),
                "langCount": [dict(code=code, **counts([key for key in answers if key[0] == code]))
                              for code in LANGUAGES if any(key[0] == code for key in answers)],
                "gameCount": [dict(type=game, **counts([key for key in answers if key[1] == game]))
                              for game in MODES if any(key[1] == game for key in answers)],
                "words": {"easy": [], "hard": []}, "cTime": local, "cWeekTime": local}

    def handle(self, params, interface_code="us"):
        response = self.envelope(params)
        kind = response["type"]
        category = params.get("category", "words")
        headers = {}
        try:
            if category == "words" and kind == "getWord":
                response["data"] = self.get_word(params)
            elif category == "words" and kind in ("anwser", "answer"):
                response.update(self.answer(params))
            elif category == "utils" and kind == "changeLang":
                code = str(params.get("lang_code", "us")).lower()
                if not re.fullmatch(r"[a-z]{2}", code):
                    raise GameUnavailable("Invalid menu language.", "invalid_language", 400)
                response["interface"] = self.interface(code)
                headers["Set-Cookie"] = "local_interface=" + code + "; Path=/; SameSite=Lax"
            elif category == "utils" and kind == "getHomeImage":
                records = [record for words in self.catalog.snapshot().values() for record in words]
                record = self.rng.choice(records) if records else None
                response.update(svg=self.catalog.image(record["image"]) if record else PLACEHOLDER,
                                color_id=record["color_key"] if record else "12")
            elif category == "utils" and kind == "getStats":
                response.update(self.stats())
            elif category == "utils" and kind == "getStatsFlags":
                response["svg"] = {"lo": PLACEHOLDER}
            elif category == "utils" and kind == "getStatsImg":
                image = str(params.get("img", ""))
                match = re.match(r"^([0-9]+)(?:_|\.svg$)", image)
                if match is None:
                    raise GameUnavailable("Invalid picture identifier.", "invalid_image", 400)
                response.update(img=image, svg=self.catalog.image("media/images/" + match[1] + ".svg"))
            elif category == "utils" and kind == "getScores":
                response.update(scores=[], total=0, time=params.get("time", "all"),
                                lang=params.get("lang", "all"), startLimit=0, countLimit=20,
                                message="Online accounts and leaderboards are unavailable. Progress stays on this device.")
            elif category == "utils" and kind == "getProgress":
                response.update(progress=[], max_number={code: len(words) for code, words in self.catalog.snapshot().items()})
            elif category == "utils" and kind in ("getCredits", "getDonate", "getProgressdemo", "getThankyou"):
                code = interface_code if re.fullmatch(r"[a-z]{2}", str(interface_code)) else "us"
                saved = (self.load_json(self.snapshots / "pages" / (kind + "." + code + ".json")) or
                         self.load_json(self.snapshots / "pages" / (kind + ".json")))
                response["html"] = saved.get("html", "") if saved else (
                    '<article><h1>Local game</h1><p>Words, pictures, and native recordings are served from this host. '
                    'Your points stay on this device.</p></article>')
            elif category == "user" and kind == "signOut":
                response["user"] = None
            elif category == "user" and kind == "checkUnique":
                response.update(unique=False, input_id=params.get("input_id"), str=params.get("str", ""),
                                message="Online accounts are unavailable.")
            elif category == "user":
                response.update(error="error_server", code="local_accounts_only",
                                message="Online accounts are unavailable. Your game progress stays on this device.")
            else:
                raise GameUnavailable("Unsupported local API request.", "unsupported_request", 400)
            return 200, response, headers
        except GameUnavailable as error:
            response.update(type="error", requestType=kind, code=error.code, message=str(error))
            return error.status, response, headers
