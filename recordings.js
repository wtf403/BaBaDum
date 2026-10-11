// Exact recording metadata observed in native Ba Ba Dum rounds.
var BabadumRecordings = (function () {
  var storageKey = 'babadumRecordings-v1';
  var records = Object.create(null);
  var aliases = {en: 'us', zh: 'cn', ja: 'jp', sv: 'se', cs: 'cz', el: 'gr'};

  function normalizeLanguage(code) {
    if (typeof code !== 'string') return null;
    code = code.toLowerCase().trim();
    return /^[a-z]{2}$/.test(code) ? aliases[code] || code : null;
  }

  function numericID(value) {
    return (typeof value === 'number' || typeof value === 'string') &&
      /^\d+$/.test(String(value)) ? String(value) : null;
  }

  function validRecord(record) {
    return record && typeof record.word === 'string' && record.word.trim() &&
      typeof record.audio_file === 'string' && record.audio_file.trim() &&
      record.audio_file !== '.' && record.audio_file !== '..' &&
      !/[\/\\?#\x00-\x1f\x7f]/.test(record.audio_file);
  }

  function store(language, id, record) {
    language = normalizeLanguage(language);
    id = numericID(id);
    if (!language || id === null || !validRecord(record)) return false;
    records[language + ':' + id] = {
      word: record.word, audio_file: record.audio_file, lang: language
    };
    return true;
  }

  function languageForID(id) {
    if (typeof Langs === 'undefined' || numericID(id) === null) return null;
    for (var i = 0; i < Langs.length; i++) {
      if (String(Langs[i].id) === String(id)) return normalizeLanguage(Langs[i].code);
    }
    return null;
  }

  try {
    var saved = JSON.parse(localStorage.getItem(storageKey));
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      Object.keys(saved).forEach(function (key) {
        var parts = key.split(':');
        if (parts.length === 2) store(parts[0], parts[1], saved[key]);
      });
    }
  } catch (error) { /* Storage can be unavailable or contain old/corrupt data. */ }

  function copy(record) {
    return record ? {word: record.word, audio_file: record.audio_file, lang: record.lang} : null;
  }

  return {
    normalizeLanguage: normalizeLanguage,
    remember: function (round) {
      round = round && (round.data || round);
      if (!round || !Array.isArray(round.words)) return;
      var changed = false;
      round.words.forEach(function (word) {
        if (!word || numericID(word.id) === null) return;
        var language = languageForID(word.lang_key) ||
          normalizeLanguage(round.lang) || languageForID(round.lang_key);
        if (store(language, word.word_key, word)) changed = true;
      });
      if (changed) {
        try { localStorage.setItem(storageKey, JSON.stringify(records)); }
        catch (error) { /* Playback still uses the in-memory index. */ }
      }
    },
    get: function (language, wordKey) {
      language = normalizeLanguage(language);
      var id = numericID(wordKey);
      return language && id !== null ? copy(records[language + ':' + id]) : null;
    },
    getByText: function (language, text) {
      language = normalizeLanguage(language);
      if (!language || typeof text !== 'string' || !text.trim()) return null;
      var match = null;
      var keys = Object.keys(records);
      for (var i = 0; i < keys.length; i++) {
        var record = records[keys[i]];
        if (record.lang === language && record.word.trim() === text.trim()) {
          if (match && match.audio_file !== record.audio_file) return null;
          match = record;
        }
      }
      return copy(match);
    }
  };
})();
