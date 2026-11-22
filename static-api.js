(function () {
  "use strict";

  var LANGUAGES = {
    es: 4, gb: 7, us: 1, pl: 2, de: 3, fr: 5, it: 6, ru: 8, jp: 9, se: 10,
    gr: 11, cz: 14, lt: 15, pt: 16, ro: 18, hu: 23, da: 12, cn: 13, eo: 24, tr: 25, uk: 26,
  };
  var MODES = {
    chooseImage: ["1", 1],
    chooseImageSound: ["2", 2],
    setLetters: ["3", 6],
    oneImage: ["4", 3],
  };
  var COLORS = {};
  [1].concat(range(3, 23), range(26, 35)).forEach(function (n) { COLORS[String(n)] = true; });
  var PLACEHOLDER =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><circle class="fill" cx="100" cy="100" r="80"/><path class="stroke" fill="none" stroke-width="8" d="M60 115Q100 155 140 115"/></svg>';
  var state = { vocabulary: null, vocabularyPromise: null, interfaces: {}, rounds: {}, answers: {}, correct: {} };

  function range(a, b) { var out = []; for (var i = a; i <= b; i++) out.push(i); return out; }
  function choice(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
  function sample(arr, n) {
    var copy = arr.slice(), out = [];
    while (out.length < n && copy.length) out.push(copy.splice(Math.floor(Math.random() * copy.length), 1)[0]);
    return out;
  }
  function shuffle(arr) {
    for (var i = arr.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }
  function token() { return Math.random().toString(36).slice(2) + Date.now().toString(36) + Math.random().toString(36).slice(2); }

  function fetchJSON(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }
  function fetchText(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.text();
    });
  }

  function basePath() {
    return location.pathname.indexOf("/BaBaDum/") === 0 ? "/BaBaDum/" : "/";
  }

  function loadVocabulary() {
    if (state.vocabulary) return Promise.resolve(state.vocabulary);
    if (state.vocabularyPromise) return state.vocabularyPromise;
    var url = basePath() + "data/library/vocabulary.json";
    state.vocabularyPromise = fetchJSON(url).then(function (manifest) {
      var languages = {};
      var langs = manifest && manifest.languages ? manifest.languages : {};
      Object.keys(langs).forEach(function (code) {
        if (!LANGUAGES[code]) return;
        var words = langs[code].words || {};
        var records = [];
        Object.keys(words).forEach(function (concept) {
          var entry = words[concept];
          if (!entry || !entry.word || !entry.audio_file) return;
          var image = entry.image || ("media/images/" + concept + ".svg");
          if (image !== "media/images/" + concept + ".svg") return;
          var audio = [];
          ["audio", "audio_alt"].forEach(function (name) {
            var rel = entry[name];
            var ogg = "media/audio/" + code + "/" + entry.audio_file + ".ogg";
            var m4a = "media/audio/" + code + "/" + entry.audio_file + ".m4a";
            if (rel === ogg || rel === m4a) audio.push("https://raw.githubusercontent.com/wtf403/BaBaDum/main/data/library/" + rel);
          });
          if (!audio.length) return;
          var color = String(entry.color_key || "12");
          records.push({
            word_key: String(concept),
            id: String(entry.id),
            word: entry.word,
            lang_key: LANGUAGES[code],
            audio_file: entry.audio_file,
            audioUrls: audio.filter(function (v, i, a) { return a.indexOf(v) === i; }),
            color_key: COLORS[color] ? color : "12",
            level: "0",
            image: image,
          });
        });
        languages[code] = records;
      });
      state.vocabulary = languages;
      return languages;
    }).catch(function (e) {
      state.vocabularyPromise = null;
      throw e;
    });
    return state.vocabularyPromise;
  }

  function loadInterface(code) {
    code = /^[a-z]{2}$/.test(code || "") ? code : "us";
    if (state.interfaces[code]) return Promise.resolve(state.interfaces[code]);
    return fetchJSON(basePath() + "data/local-api/interfaces/" + code + ".json").then(function (value) {
      var iface = value && value.interface ? value.interface : value || {};
      iface = JSON.parse(JSON.stringify(iface));
      iface.lang_code = code;
      state.interfaces[code] = iface;
      return iface;
    }).catch(function () {
      if (code === "us") return {};
      return loadInterface("us");
    });
  }

  function imageSvg(relative) {
    if (typeof relative !== "string" || relative.indexOf("media/") !== 0) return Promise.resolve(PLACEHOLDER);
    return fetchText(basePath() + "data/library/" + relative).then(function (svg) {
      return svg.indexOf("<svg") !== -1 ? svg : PLACEHOLDER;
    }).catch(function () { return PLACEHOLDER; });
  }

  function getWord(params) {
    return loadVocabulary().then(function (languages) {
      var requested = String(params.lang == null ? "1" : params.lang);
      var code = null;
      Object.keys(LANGUAGES).forEach(function (c) { if (requested === c || requested === String(LANGUAGES[c])) code = c; });
      if (requested === "0" || requested === "shuffleLang") {
        var available = Object.keys(languages).filter(function (c) { return (languages[c] || []).length >= 4; });
        code = available.length ? choice(available) : null;
      }
      if (!code) throw { code: "language_unavailable", message: "This language has no local native library." };
      var records = languages[code] || [];
      var uniqueMap = {};
      records.forEach(function (r) { var k = String(r.word).toLowerCase().trim(); if (!uniqueMap[k]) uniqueMap[k] = r; });
      var unique = Object.keys(uniqueMap).map(function (k) { return uniqueMap[k]; });
      if (unique.length < 4) throw { code: "language_incomplete", message: "This language needs at least four downloaded words, pictures, and recordings." };
      var game = String(params.game || "chooseImage");
      var aliases = { "1": "chooseImage", "2": "chooseImageSound", "3": "setLetters", "4": "oneImage", "5": "shuffleGames", chooseWord: "oneImage", shuffle: "shuffleGames" };
      game = aliases[game] || game;
      if (game === "shuffleGames") game = choice(Object.keys(MODES));
      if (!MODES[game]) throw { code: "unsupported_game", message: "This game is not available in the local library." };
      var target = String(params.translation_lang || "").toLowerCase();
      var translations = {};
      (languages[target] || []).forEach(function (r) { translations[r.word_key] = r; });
      var paired = unique.filter(function (r) { return translations[r.word_key]; });
      var requireTranslation = String(params.play_translation || "false").toLowerCase() === "true";
      var answer = choice(requireTranslation && paired.length ? paired : unique);
      var chosen = [answer].concat(sample(unique.filter(function (r) { return r.word_key !== answer.word_key; }), 3));
      if (game !== "setLetters") shuffle(chosen);
      return Promise.all(chosen.map(function (r) { return imageSvg(r.image).then(function (svg) { var w = JSON.parse(JSON.stringify(r)); w.img = svg; delete w.image; return w; }); })).then(function (words) {
        var tkn = token();
        state.rounds[tkn] = { answer: answer.id, word: answer.word, lang: code, game: game, time: Date.now() };
        var keys = Object.keys(state.rounds);
        if (keys.length > 10000) keys.slice(0, keys.length - 10000).forEach(function (k) { delete state.rounds[k]; });
        var result = {
          id: answer.word_key, audio: answer.audio_file, pairingMenuCode: target,
          pairedAudioRequired: requireTranslation, audioUrls: answer.audioUrls, lang: code,
          lang_key: LANGUAGES[code], color: answer.color_key, game: game, words: words,
          real_m: MODES[game][1], p_id: tkn, local: true,
        };
        var tr = translations[answer.word_key];
        if (tr) result.nativeTranslation = { lang: target, word: tr.word, audioUrls: tr.audioUrls };
        if (game === "setLetters") {
          var letters = answer.word.split("");
          shuffle(letters);
          if (letters.join("") === answer.word && letters.length > 1) letters = letters.slice(1).concat(letters.slice(0, 1));
          result.shuffle = letters.join("");
        }
        return result;
      });
    });
  }

  function answer(params) {
    var saved = state.rounds[String(params.p_id || "")];
    delete state.rounds[String(params.p_id || "")];
    if (!saved || Date.now() - saved.time > 7200000) return Promise.resolve({ accepted: false, reason: "round_expired" });
    if (String(params.lang_id) !== String(LANGUAGES[saved.lang]) || String(params.game_id) !== String(MODES[saved.game][0])) {
      return Promise.resolve({ accepted: false, reason: "round_mismatch" });
    }
    var expected = saved.game === "setLetters" ? saved.word : saved.answer;
    var correct = String(params.a || "") === String(expected);
    var key = saved.lang + "|" + saved.game;
    state.answers[key] = (state.answers[key] || 0) + 1;
    state.correct[key] = (state.correct[key] || 0) + (correct ? 1 : 0);
    return Promise.resolve({ accepted: true, correct: correct });
  }

  function countsFor(keys) {
    var total = 0, ok = 0;
    keys.forEach(function (k) { total += state.answers[k] || 0; ok += state.correct[k] || 0; });
    return { OK: String(ok), KO: String(total - ok) };
  }

  function stats() {
    var keys = Object.keys(state.answers);
    var local = [{ code: "lo", country: "This server", percent: 100 }];
    return Promise.resolve({
      h: { stats_h1: "Local statistics", stats_h2_num: "Answers on this device", stats_h2_langs: "Languages", stats_h2_games: "Games", stats_total: "Total", stats_h2_easy: "", stats_h2_hard: "", stats_h2_cAllTime: "Local play", stats_others: "Other" },
      count: countsFor(keys),
      langCount: Object.keys(LANGUAGES).filter(function (c) { return keys.some(function (k) { return k.indexOf(c + "|") === 0; }); }).map(function (c) { var k2 = keys.filter(function (k) { return k.indexOf(c + "|") === 0; }); var o = countsFor(k2); o.code = c; return o; }),
      gameCount: Object.keys(MODES).filter(function (g) { return keys.some(function (k) { return k.slice(k.indexOf("|") + 1) === g; }); }).map(function (g) { var k2 = keys.filter(function (k) { return k.slice(k.indexOf("|") + 1) === g; }); var o = countsFor(k2); o.type = g; return o; }),
      words: { easy: [], hard: [] }, cTime: local, cWeekTime: local,
    });
  }

  function handle(params) {
    var response = { type: String(params.type || ""), local: true };
    ["onReceiveLocation", "connectId"].forEach(function (n) { if (params[n] !== undefined) response[n] = params[n]; });
    var kind = response.type;
    var category = params.category || "words";
    var promise;
    try {
      if (category === "words" && kind === "getWord") {
        promise = getWord(params).then(function (data) { response.data = data; return response; });
      } else if (category === "words" && (kind === "anwser" || kind === "answer")) {
        promise = answer(params).then(function (r) { Object.keys(r).forEach(function (k) { response[k] = r[k]; }); return response; });
      } else if (category === "utils" && kind === "changeLang") {
        var code = String(params.lang_code || "us").toLowerCase();
        if (!/^[a-z]{2}$/.test(code)) code = "us";
        promise = loadInterface(code).then(function (iface) { response.interface = iface; return response; });
      } else if (category === "utils" && kind === "getHomeImage") {
        promise = loadVocabulary().then(function (languages) {
          var all = [];
          Object.keys(languages).forEach(function (c) { all = all.concat(languages[c]); });
          var record = all.length ? choice(all) : null;
          if (!record) { response.svg = PLACEHOLDER; response.color_id = "12"; return response; }
          return imageSvg(record.image).then(function (svg) { response.svg = svg; response.color_id = record.color_key; return response; });
        });
      } else if (category === "utils" && kind === "getStats") {
        promise = stats().then(function (s) { Object.keys(s).forEach(function (k) { response[k] = s[k]; }); return response; });
      } else if (category === "utils" && kind === "getStatsFlags") {
        response.svg = { lo: PLACEHOLDER }; promise = Promise.resolve(response);
      } else if (category === "utils" && kind === "getStatsImg") {
        var img = String(params.img || "");
        var m = img.match(/^([0-9]+)(?:_|\.svg$)/);
        if (!m) { response.type = "error"; response.code = "invalid_image"; response.message = "Invalid picture identifier."; promise = Promise.resolve(response); }
        else promise = imageSvg("media/images/" + m[1] + ".svg").then(function (svg) { response.img = img; response.svg = svg; return response; });
      } else if (category === "utils" && kind === "getScores") {
        response.scores = []; response.total = 0; response.time = params.time || "all"; response.lang = params.lang || "all"; response.startLimit = 0; response.countLimit = 20; response.message = "Online accounts and leaderboards are unavailable. Progress stays on this device."; promise = Promise.resolve(response);
      } else if (category === "utils" && kind === "getProgress") {
        promise = loadVocabulary().then(function (languages) { var max = {}; Object.keys(languages).forEach(function (c) { max[c] = languages[c].length; }); response.progress = []; response.max_number = max; return response; });
      } else if (category === "utils" && ["getCredits", "getDonate", "getProgressdemo", "getThankyou"].indexOf(kind) !== -1) {
        var ic = /^[a-z]{2}$/.test(String(params.interface_code || "us")) ? String(params.interface_code || "us") : "us";
        promise = fetchJSON(basePath() + "data/local-api/pages/" + kind + "." + ic + ".json").catch(function () { return fetchJSON(basePath() + "data/local-api/pages/" + kind + ".json"); }).then(function (saved) {
          response.html = saved && saved.html ? saved.html : '<article><h1>Local game</h1><p>Words, pictures, and native recordings are served from this host. Your points stay on this device.</p></article>';
          return response;
        }).catch(function () { response.html = '<article><h1>Local game</h1><p>Words, pictures, and native recordings are served from this host. Your points stay on this device.</p></article>'; return response; });
      } else if (category === "user" && kind === "signOut") {
        response.user = null; promise = Promise.resolve(response);
      } else if (category === "user" && kind === "checkUnique") {
        response.unique = false; response.input_id = params.input_id; response.str = params.str || ""; response.message = "Online accounts are unavailable."; promise = Promise.resolve(response);
      } else if (category === "user") {
        response.error = "error_server"; response.code = "local_accounts_only"; response.message = "Online accounts are unavailable. Your game progress stays on this device."; promise = Promise.resolve(response);
      } else {
        response.type = "error"; response.requestType = kind; response.code = "unsupported_request"; response.message = "Unsupported local API request."; promise = Promise.resolve(response);
      }
    } catch (e) {
      response.type = "error"; response.requestType = kind; response.code = e.code || "library_unavailable"; response.message = e.message || String(e);
      promise = Promise.resolve(response);
    }
    return promise.catch(function (e) {
      response.type = "error"; response.requestType = kind; response.code = e.code || "library_unavailable"; response.message = e.message || String(e);
      return response;
    });
  }

  window.StaticGameAPI = { handle: handle, _state: state };
})();
