const LANGUAGES = {
  es: 4, gb: 7, us: 1, pl: 2, de: 3, fr: 5, it: 6, ru: 8, jp: 9, se: 10,
  gr: 11, cz: 14, lt: 15, pt: 16, ro: 18, hu: 23, da: 12, cn: 13, eo: 24, tr: 25, uk: 26,
};
const MODES = { chooseImage: ["1", 1], chooseImageSound: ["2", 2], setLetters: ["3", 6], oneImage: ["4", 3] };
const COLORS = new Set(["1", ...Array.from({ length: 21 }, (_, i) => String(i + 3)), ...Array.from({ length: 10 }, (_, i) => String(i + 26))]);
const PLACEHOLDER = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><circle class="fill" cx="100" cy="100" r="80"/><path class="stroke" fill="none" stroke-width="8" d="M60 115Q100 155 140 115"/></svg>';

function choice(rng, arr) { return arr[Math.floor(rng() * arr.length)]; }
function sample(rng, arr, n) { const copy = [...arr]; const out = []; while (out.length < n && copy.length) out.push(copy.splice(Math.floor(rng() * copy.length), 1)[0]); return out; }
function shuffle(rng, arr) { for (let i = arr.length - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); [arr[i], arr[j]] = [arr[j], arr[i]]; } return arr; }
function rng() { return Math.random(); }

async function readJSON(env, path) {
  const res = await env.ASSETS.fetch(new URL(path, "https://assets.local"));
  if (!res.ok) return null;
  return res.json();
}
async function readText(env, path) {
  const res = await env.ASSETS.fetch(new URL(path, "https://assets.local"));
  if (!res.ok) return null;
  return res.text();
}

export class GameState {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.rounds = new Map();
    this.answers = new Map();
    this.correct = new Map();
    this.vocabulary = null;
  }

  async loadVocabulary() {
    if (this.vocabulary) return this.vocabulary;
    const manifest = await readJSON(this.env, "/data/library/vocabulary.json");
    const languages = {};
    const langs = manifest?.languages || {};
    for (const [code, language] of Object.entries(langs)) {
      if (!LANGUAGES[code]) continue;
      const records = [];
      for (const [concept, entry] of Object.entries(language?.words || {})) {
        if (!entry || typeof entry.word !== "string" || !entry.word.trim() || !entry.audio_file) continue;
        const image = entry.image || `media/images/${concept}.svg`;
        if (image !== `media/images/${concept}.svg`) continue;
        const audio = [];
        for (const name of ["audio", "audio_alt"]) {
          const rel = entry[name];
          const ogg = `media/audio/${code}/${entry.audio_file}.ogg`;
          const m4a = `media/audio/${code}/${entry.audio_file}.m4a`;
          if (rel === ogg || rel === m4a) audio.push(`https://raw.githubusercontent.com/wtf403/BaBaDum/main/data/library/${rel}`);
        }
        if (!audio.length) continue;
        const color = String(entry.color_key || "12");
        records.push({ word_key: String(concept), id: String(entry.id), word: entry.word, lang_key: LANGUAGES[code], audio_file: entry.audio_file, audioUrls: [...new Set(audio)], color_key: COLORS.has(color) ? color : "12", level: "0", image });
      }
      languages[code] = records;
    }
    this.vocabulary = languages;
    return languages;
  }

  envelope(params) {
    const result = { type: String(params.type || ""), local: false, worker: true };
    for (const name of ["onReceiveLocation", "connectId"]) if (params[name] !== undefined) result[name] = params[name];
    return result;
  }

  async imageSvg(relative) {
    if (typeof relative !== "string" || !relative.startsWith("media/")) return PLACEHOLDER;
    const svg = await readText(this.env, `/data/library/${relative}`);
    return svg && svg.includes("<svg") ? svg : PLACEHOLDER;
  }

  async getWord(params) {
    const languages = await this.loadVocabulary();
    const requested = String(params.lang ?? "1");
    let code = Object.keys(LANGUAGES).find((c) => requested === c || requested === String(LANGUAGES[c]));
    if (requested === "0" || requested === "shuffleLang") {
      const available = Object.keys(languages).filter((c) => (languages[c] || []).length >= 4);
      code = available.length ? choice(rng, available) : null;
    }
    if (!code) return { error: { code: "language_unavailable", message: "This language has no local native library." } };
    const records = languages[code] || [];
    const uniqueMap = new Map();
    for (const r of records) { const k = String(r.word).toLowerCase().trim(); if (!uniqueMap.has(k)) uniqueMap.set(k, r); }
    const unique = [...uniqueMap.values()];
    if (unique.length < 4) return { error: { code: "language_incomplete", message: "This language needs at least four downloaded words, pictures, and recordings." } };
    let game = String(params.game || "chooseImage");
    const aliases = { "1": "chooseImage", "2": "chooseImageSound", "3": "setLetters", "4": "oneImage", "5": "shuffleGames", chooseWord: "oneImage", shuffle: "shuffleGames" };
    game = aliases[game] || game;
    if (game === "shuffleGames") game = choice(rng, Object.keys(MODES));
    if (!MODES[game]) return { error: { code: "unsupported_game", message: "This game is not available in the local library." } };
    const target = String(params.translation_lang || "").toLowerCase();
    const translations = new Map((languages[target] || []).map((r) => [r.word_key, r]));
    const paired = unique.filter((r) => translations.has(r.word_key));
    const requireTranslation = String(params.play_translation || "false").toLowerCase() === "true";
    const answer = choice(rng, requireTranslation && paired.length ? paired : unique);
    let chosen = [answer, ...sample(rng, unique.filter((r) => r.word_key !== answer.word_key), 3)];
    if (game !== "setLetters") shuffle(rng, chosen);
    const words = await Promise.all(chosen.map(async (r) => { const w = { ...r }; w.img = await this.imageSvg(w.image); delete w.image; return w; }));
    const tkn = crypto.randomUUID();
    this.rounds.set(tkn, { answer: answer.id, word: answer.word, lang: code, game, time: Date.now() });
    if (this.rounds.size > 10000) { const keys = [...this.rounds.keys()].slice(0, this.rounds.size - 10000); for (const k of keys) this.rounds.delete(k); }
    const result = { id: answer.word_key, audio: answer.audio_file, pairingMenuCode: target, pairedAudioRequired: requireTranslation, audioUrls: answer.audioUrls, lang: code, lang_key: LANGUAGES[code], color: answer.color_key, game, words, real_m: MODES[game][1], p_id: tkn, local: false, worker: true };
    const tr = translations.get(answer.word_key);
    if (tr) result.nativeTranslation = { lang: target, word: tr.word, audioUrls: tr.audioUrls };
    if (game === "setLetters") {
      let letters = answer.word.split(""); shuffle(rng, letters);
      if (letters.join("") === answer.word && letters.length > 1) letters = [...letters.slice(1), letters[0]];
      result.shuffle = letters.join("");
    }
    return { data: result };
  }

  answer(params) {
    const saved = this.rounds.get(String(params.p_id || ""));
    this.rounds.delete(String(params.p_id || ""));
    if (!saved || Date.now() - saved.time > 7200000) return { accepted: false, reason: "round_expired" };
    if (String(params.lang_id) !== String(LANGUAGES[saved.lang]) || String(params.game_id) !== String(MODES[saved.game][0])) return { accepted: false, reason: "round_mismatch" };
    const expected = saved.game === "setLetters" ? saved.word : saved.answer;
    const correct = String(params.a || "") === String(expected);
    const key = `${saved.lang}|${saved.game}`;
    this.answers.set(key, (this.answers.get(key) || 0) + 1);
    this.correct.set(key, (this.correct.get(key) || 0) + (correct ? 1 : 0));
    return { accepted: true, correct };
  }

  countsFor(keys) { let total = 0, ok = 0; for (const k of keys) { total += this.answers.get(k) || 0; ok += this.correct.get(k) || 0; } return { OK: String(ok), KO: String(total - ok) }; }

  async stats() {
    const keys = [...this.answers.keys()];
    const local = [{ code: "lo", country: "This server", percent: 100 }];
    return { h: { stats_h1: "Worker statistics", stats_h2_num: "Answers on this worker", stats_h2_langs: "Languages", stats_h2_games: "Games", stats_total: "Total", stats_h2_easy: "", stats_h2_hard: "", stats_h2_cAllTime: "Worker play", stats_others: "Other" }, count: this.countsFor(keys), langCount: Object.keys(LANGUAGES).filter((c) => keys.some((k) => k.startsWith(c + "|"))).map((c) => ({ code: c, ...this.countsFor(keys.filter((k) => k.startsWith(c + "|"))) })), gameCount: Object.keys(MODES).filter((g) => keys.some((k) => k.endsWith("|" + g))).map((g) => ({ type: g, ...this.countsFor(keys.filter((k) => k.endsWith("|" + g))) })), words: { easy: [], hard: [] }, cTime: local, cWeekTime: local };
  }

  async handle(params) {
    const response = this.envelope(params);
    const kind = response.type;
    const category = params.category || "words";
    try {
      if (category === "words" && kind === "getWord") {
        const r = await this.getWord(params);
        if (r.error) { response.type = "error"; response.requestType = kind; response.code = r.error.code; response.message = r.error.message; }
        else response.data = r.data;
      } else if (category === "words" && (kind === "anwser" || kind === "answer")) {
        Object.assign(response, this.answer(params));
      } else if (category === "utils" && kind === "changeLang") {
        const code = /^[a-z]{2}$/.test(String(params.lang_code || "")) ? String(params.lang_code).toLowerCase() : "us";
        const value = await readJSON(this.env, `/data/local-api/interfaces/${code}.json`) || await readJSON(this.env, `/data/local-api/interfaces/us.json`) || {};
        const iface = structuredClone(value.interface || value);
        iface.lang_code = code;
        response.interface = iface;
      } else if (category === "utils" && kind === "getHomeImage") {
        const languages = await this.loadVocabulary();
        const all = Object.values(languages).flat();
        const record = all.length ? choice(rng, all) : null;
        response.svg = record ? await this.imageSvg(record.image) : PLACEHOLDER;
        response.color_id = record ? record.color_key : "12";
      } else if (category === "utils" && kind === "getStats") {
        Object.assign(response, await this.stats());
      } else if (category === "utils" && kind === "getStatsFlags") {
        response.svg = { lo: PLACEHOLDER };
      } else if (category === "utils" && kind === "getStatsImg") {
        const img = String(params.img || "");
        const m = img.match(/^([0-9]+)(?:_|\.svg$)/);
        if (!m) { response.type = "error"; response.code = "invalid_image"; response.message = "Invalid picture identifier."; }
        else { response.img = img; response.svg = await this.imageSvg(`media/images/${m[1]}.svg`); }
      } else if (category === "utils" && kind === "getScores") {
        Object.assign(response, { scores: [], total: 0, time: params.time || "all", lang: params.lang || "all", startLimit: 0, countLimit: 20, message: "Online accounts and leaderboards are unavailable. Progress stays on this device." });
      } else if (category === "utils" && kind === "getProgress") {
        const languages = await this.loadVocabulary();
        const max = {}; for (const [c, words] of Object.entries(languages)) max[c] = words.length;
        response.progress = []; response.max_number = max;
      } else if (category === "utils" && ["getCredits", "getDonate", "getProgressdemo", "getThankyou"].includes(kind)) {
        const ic = /^[a-z]{2}$/.test(String(params.interface_code || "us")) ? String(params.interface_code) : "us";
        const saved = await readJSON(this.env, `/data/local-api/pages/${kind}.${ic}.json`) || await readJSON(this.env, `/data/local-api/pages/${kind}.json`);
        response.html = saved?.html || '<article><h1>Local game</h1><p>Words, pictures, and native recordings are served from this host. Your points stay on this device.</p></article>';
      } else if (category === "user" && kind === "signOut") {
        response.user = null;
      } else if (category === "user" && kind === "checkUnique") {
        Object.assign(response, { unique: false, input_id: params.input_id, str: params.str || "", message: "Online accounts are unavailable." });
      } else if (category === "user") {
        Object.assign(response, { error: "error_server", code: "local_accounts_only", message: "Online accounts are unavailable. Your game progress stays on this device." });
      } else {
        Object.assign(response, { type: "error", requestType: kind, code: "unsupported_request", message: "Unsupported local API request." });
      }
    } catch (e) {
      Object.assign(response, { type: "error", requestType: kind, code: e.code || "library_unavailable", message: e.message || String(e) });
    }
    return response;
  }

  async fetch(request) {
    if (request.method !== "POST") return new Response("Method Not Allowed", { status: 405 });
    let params;
    const ct = request.headers.get("content-type") || "";
    if (ct.includes("application/json")) params = await request.json();
    else { const body = await request.text(); params = Object.fromEntries(new URLSearchParams(body)); }
    const result = await this.handle(params);
    return Response.json(result);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/game" || url.pathname === "/get.php") {
      const id = env.GAME_STATE.idFromName("global");
      const stub = env.GAME_STATE.get(id);
      return stub.fetch(request);
    }
    if (url.pathname === "/config.js") {
      const key = env.DEEPL_API_KEY || "";
      const body = `var Config = {\n  deepl: {\n    apiKey: ${JSON.stringify(key)},\n    useFreeApi: true,\n  },\n};\n`;
      return new Response(body, { headers: { "Content-Type": "application/javascript; charset=utf-8", "Cache-Control": "no-store" } });
    }
    return env.ASSETS.fetch(request);
  },
};
