// Arabic is a local learning language; upstream rounds retain their picture IDs.
var ArabicLearning = {
  id: 100,
  pending: null,
  generation: 0,
  skipped: 0,
  cache: {},
  voice: function () {
    if (!window.speechSynthesis) return null;
    return window.speechSynthesis.getVoices().filter(function (v) {
      return /^ar(?:-|$)/i.test(v.lang);
    })[0] || null;
  },
  notice: function (message, retry) {
    $('#arabic-status').remove();
    if (!message) return;
    var el = $('<div id="arabic-status" role="status"></div>').text(message);
    if (retry) $('<button type="button">Retry</button>').appendTo(el).on('click', function () {
      ArabicLearning.skipped = 0;
      ArabicLearning.get();
    });
    el.appendTo('body');
  },
  reset: function () {
    this.generation++;
    this.pending = null;
    this.skipped = 0;
    this.notice('');
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  },
  translate: function (words, done, fail) {
    var self = this;
    var missing = words.filter(function (word, i) {
      return !self.cache[word] && words.indexOf(word) == i;
    });
    function finish() { done(words.map(function (word) { return self.cache[word]; })); }
    if (!missing.length) return finish();
    $.ajax({
      url: '/api/deepl/translate', method: 'POST', contentType: 'application/json', timeout: 25000,
      data: JSON.stringify({text: missing, source_lang: 'EN', target_lang: 'AR', auth_key: DeepLTranscription.getApiKey()}),
      success: function (response) {
        if (!response || !response.translations || response.translations.length != missing.length) return fail();
        var translated = response.translations.map(function (t) { return t.text && t.text.trim(); });
        if (translated.some(function (t) { return !t || !/[\u0600-\u06ff]/.test(t); })) return fail();
        missing.forEach(function (word, i) { self.cache[word] = translated[i]; });
        try { localStorage.setItem('arabicTranslations-v1', JSON.stringify(self.cache)); } catch (e) {}
        finish();
      }, error: fail
    });
  },
  get: function () {
    if (Game.langID != this.id || !Game.gameType || Words.arr.length >= Words.min_loaded || this.pending) return;
    var self = this, generation = this.generation, requestedGame = Game.gameType;
    var game = requestedGame;
    // Arabic spelling requires a separate joined-letter interaction.
    if (game == 'setLetters' || game == 'kana') game = 'chooseImage';
    if (game == 'shuffleGames') {
      var games = this.voice() ? ['chooseImage', 'oneImage', 'chooseImageSound'] : ['chooseImage', 'oneImage'];
      game = games[Math.floor(Math.random() * games.length)];
    }
    if (game == 'chooseImageSound' && !this.voice()) game = 'chooseImage';
    this.pending = true;
    function current() { return generation == self.generation && Game.langID == self.id && Game.gameType == requestedGame; }
    function fail() {
      if (!current()) return;
      self.pending = null;
      self.notice('Arabic translation could not load. Check the DeepL API key or connection.', true);
    }
    if (!Words.arr.length && !Words.current) this.notice('Preparing Arabic words…');
    $.ajax({
      url: '/api/game', method: 'POST', dataType: 'json', timeout: 20000,
      data: {type: 'getWord', category: 'words', onReceiveLocation: 'Words', lang: 1, game: game, random: Date.now()},
      success: function (response) {
        if (!current()) return;
        var round = response && response.data;
        if (!round || !Array.isArray(round.words) || !round.words.length || !round.words.some(function (w) { return w.word_key == round.id; })) return fail();
        BabadumRecordings.remember(round);
        round.localImagesReady = false;
        BabadumLibrary.loadImages(round, function () {
          round.localImagesReady = true;
          Words.ready();
        });
        self.translate(round.words.map(function (w) { return w.word; }), function (translated) {
          if (!current()) return;
          self.pending = null;
          // Different pictures must have distinct labels after translation.
          var labels = {};
          var ambiguous = translated.some(function (word, i) {
            var key = word.replace(/[\u064b-\u065f\u0670\u0640]/g, '').trim();
            if (labels[key] !== undefined && labels[key] != round.words[i].word_key) return true;
            labels[key] = round.words[i].word_key;
            return false;
          });
          if (ambiguous) {
            if (++self.skipped >= 5) return fail();
            return self.get();
          }
          self.skipped = 0;
          round.arabic = true;
          round.lang_key = self.id;
          round.game = game;
          round.words.forEach(function (w, i) {
            w.sourceWord = w.word;
            w.word = translated[i];
            w.lang_key = self.id;
          });
          var answer = round.words.filter(function (w) { return w.word_key == round.id; })[0];
          TranslationAudio.prepare(round);
          round.sound = {
            _loaded: true, fake: !window.speechSynthesis,
            play: function () {
              var voice = self.voice();
              if (!voice) { self.notice('Install an Arabic speech voice in your device settings to hear pronunciation.'); return; }
              window.speechSynthesis.cancel();
              var speech = new SpeechSynthesisUtterance(answer.word);
              speech.lang = voice.lang;
              speech.voice = voice;
              speech.rate = 0.85;
              speech.onend = speech.onerror = function () { if (Words.current == round) Sounds.onWordEnd(); };
              window.speechSynthesis.speak(speech);
            }
          };
          Words.arr.push(round);
          self.notice(requestedGame == 'setLetters' ? 'Arabic spelling is not available yet. Playing picture choice instead.' : requestedGame == 'chooseImageSound' && game != requestedGame ? 'Install an Arabic speech voice to play listening games. Playing picture choice instead.' : '');
          Words.ready();
          self.get();
        }, fail);
      }, error: fail
    });
  }
};
try {
  var savedArabic = JSON.parse(localStorage.getItem('arabicTranslations-v1') || '{}');
  if (savedArabic && typeof savedArabic == 'object' && !Array.isArray(savedArabic)) {
    Object.keys(savedArabic).forEach(function (key) {
      if (typeof savedArabic[key] == 'string' && /[\u0600-\u06ff]/.test(savedArabic[key])) ArabicLearning.cache[key] = savedArabic[key];
    });
  }
} catch (e) {}
