// The optional local library never asks the upstream game for random rounds.
// Loads library data from the public GitHub repository (raw content) by default.
var BabadumLibrary = (function () {
  var base = window.BABADUM_LIBRARY_BASE || 'https://raw.githubusercontent.com/wtf403/BaBaDum/main/data/library/';
  var manifest = null;
  var state = 'idle';
  var callbacks = [];
  var images = Object.create(null);
  var aliases = {en: 'us', zh: 'cn', ja: 'jp', sv: 'se', cs: 'cz', el: 'gr'};

  function normalizeLanguage(code) {
    if (typeof code !== 'string') return null;
    code = code.toLowerCase().trim();
    return /^[a-z]{2}$/.test(code) ? aliases[code] || code : null;
  }

  function numericID(id) {
    return (typeof id === 'number' || typeof id === 'string') && /^\d+$/.test(String(id));
  }

  function safePath(path, prefix) {
    if (typeof path !== 'string' || path.indexOf(prefix) !== 0 ||
        /[\\%?#\x00-\x1f\x7f]/.test(path)) return false;
    var filename = path.slice(prefix.length);
    return filename && filename !== '.' && filename !== '..' && filename.indexOf('/') === -1;
  }

  function finish(value) {
    if (state !== 'loading') return;
    manifest = value && value.version === 1 && value.languages &&
      typeof value.languages === 'object' && !Array.isArray(value.languages) ? value : null;
    state = 'done';
    var waiting = callbacks;
    callbacks = [];
    waiting.forEach(function (callback) { callback(!!manifest); });
  }

  function loadImage(url, done) {
    var cached = images[url];
    if (cached) {
      if (cached.finished) done(cached.svg);
      else cached.callbacks.push(done);
      return;
    }
    cached = images[url] = {callbacks: [done], finished: false, svg: null};
    function finishImage(svg) {
      if (cached.finished) return;
      cached.finished = true;
      cached.svg = svg;
      var waiting = cached.callbacks;
      cached.callbacks = [];
      waiting.forEach(function (callback) { callback(svg); });
    }
    try {
      var request = new XMLHttpRequest();
      request.open('GET', url, true);
      request.timeout = 20000;
      request.onload = function () {
        var svg = request.responseText;
        var valid = typeof svg === 'string' && /^\s*(?:<\?xml[^>]*>\s*)?(?:<!--[\s\S]*?-->\s*)*<svg[\s>]/i.test(svg) && /<\/svg>\s*$/i.test(svg);
        finishImage(request.status === 200 && valid ? svg : null);
      };
      request.onerror = request.ontimeout = request.onabort = function () { finishImage(null); };
      request.send();
    } catch (error) { finishImage(null); }
  }

  return {
    normalizeLanguage: normalizeLanguage,
    load: function (done) {
      if (typeof done === 'function') {
        if (state === 'done') { done(!!manifest); return; }
        callbacks.push(done);
      }
      if (state !== 'idle') return;
      state = 'loading';
      try {
        var request = new XMLHttpRequest();
        request.open('GET', base + 'vocabulary.json', true);
        request.timeout = 20000;
        request.onload = function () {
          var value = null;
          if (request.status === 200) {
            try { value = JSON.parse(request.responseText); } catch (error) {}
          }
          finish(value);
        };
        request.onerror = request.ontimeout = request.onabort = function () { finish(null); };
        request.send();
      } catch (error) { finish(null); }
    },
    get: function (language, wordKey) {
      language = normalizeLanguage(language);
      if (!manifest || !language || !numericID(wordKey)) return null;
      var localized = manifest.languages[language];
      var record = localized && localized.words && localized.words[String(wordKey)];
      if (!record || !numericID(record.id) || typeof record.word !== 'string' || !record.word.trim() ||
          typeof record.audio_file !== 'string' || !record.audio_file.trim() ||
          record.audio_file === '.' || record.audio_file === '..' ||
          /[\/\\%?#\x00-\x1f\x7f]/.test(record.audio_file)) return null;
      var audioUrls = [];
      [record.audio, record.audio_alt].forEach(function (path) {
        if (safePath(path, 'media/audio/' + language + '/') &&
            /\.(ogg|mp3|wav|m4a)$/.test(path) &&
            path.slice(path.lastIndexOf('/') + 1).replace(/\.(ogg|mp3|wav|m4a)$/, '') === record.audio_file &&
            audioUrls.indexOf(base + path) === -1) audioUrls.push(base + path);
      });
      return {
        word: record.word,
        id: String(record.id),
        audio_file: record.audio_file,
        lang: language,
        audioUrl: audioUrls[0] || null,
        audioUrls: audioUrls,
        imageUrl: safePath(record.image, 'media/images/') && /\.svg$/.test(record.image) ? base + record.image : null
      };
    },
    loadImages: function (round, done) {
      round = round && (round.data || round);
      done = typeof done === 'function' ? done : function () {};
      if (!round || !Array.isArray(round.words)) { done(); return; }
      var library = this;
      var remaining = round.words.length;
      if (!remaining) { done(); return; }
      round.words.forEach(function (word) {
        var record = word && library.get(round.lang, word.word_key);
        function complete(svg) {
          if (svg) word.img = svg;
          if (--remaining === 0) done();
        }
        if (record && record.imageUrl) loadImage(record.imageUrl, complete);
        else complete(null);
      });
    }
  };
})();
