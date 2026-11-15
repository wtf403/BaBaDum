const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app.js', 'utf8').split('// Optional audio')[1].split('// HanziWriter integration')[0];
function setup(saved, supported = true) {
  const spoken = [], storage = {}, timers = new Map();
  let canceled = 0;
  const speechSynthesis = {getVoices: () => [{lang: 'en-US'}, {lang: 'ru-RU'}],
    speak: speech => spoken.push(speech), cancel: () => canceled++};
  const translations = [];
  const context = {Sounds: {active: true}, Game: {speed: 1},
    InterfaceData: {data: {lang_code: 'us'}},
    BabadumLibrary: {get: () => null},
    BabadumRecordings: {get: () => null, getByText: () => null, normalizeLanguage: code => code},
    DeepLTranscription: {getTranscription: (...args) => translations.push(args)},
    localStorage: {
    getItem: () => saved, setItem: (key, value) => storage[key] = value},
    window: supported ? {speechSynthesis, SpeechSynthesisUtterance: function () {}} : {},
    SpeechSynthesisUtterance: function (text) { this.text = text; },
    setTimeout: (callback, delay) => { timers.set(timers.size + 1, {callback, delay}); return timers.size; },
    clearTimeout: id => timers.delete(id)};
  vm.createContext(context);
  vm.runInContext('// Optional audio' + source, context);
  return {audio: context.TranslationAudio, spoken, storage, timers, context, translations, canceled: () => canceled};
}
test('translation audio defaults off and persists explicit opt-in', () => {
  const {audio, spoken, storage} = setup();
  audio.play({translationText: 'cat'});
  assert.equal(spoken.length, 0);
  audio.setEnabled(true);
  assert.equal(storage.playTranslation, 'true');
  audio.play({translationText: 'кошка', translationLang: 'RU'});
  assert.equal(spoken[0].text, 'кошка');
  assert.equal(spoken[0].voice.lang, 'ru-RU');
  spoken[0].onend();
  assert.equal(audio.speech, null);
});
test('saved opt-in restores; disabling cancels outstanding speech', () => {
  const {audio, spoken, canceled, storage} = setup('true');
  audio.play({translationText: 'cat', translationLang: 'en'});
  assert.equal(spoken.length, 1);
  audio.setEnabled(false);
  assert.equal(canceled(), 1);
  assert.equal(audio.speech, null);
  assert.equal(storage.playTranslation, 'false');
});
test('missing speech support, missing translation and inactive sounds do not block a round', () => {
  const unsupported = setup('true', false);
  unsupported.audio.play({translationText: 'cat'});
  assert.equal(unsupported.audio.speech, null);
  const {audio, context, spoken} = setup('true');
  audio.play({});
  context.Sounds.active = false;
  audio.play({translationText: 'cat'});
  assert.equal(spoken.length, 0);
});
test('speech errors and missing completion callbacks release the round', () => {
  const {audio, spoken, timers} = setup('true');
  audio.play({translationText: 'cat'});
  spoken[0].onerror();
  assert.equal(audio.speech, null);
  assert.equal(timers.size, 0);
  audio.play({translationText: 'dog'});
  [...timers.values()][0].callback();
  assert.equal(audio.speech, null);
});

test('Arabic translation is prepared in Spanish when the menu is Spanish', () => {
  const {audio, context, translations} = setup('true');
  context.InterfaceData.data.lang_code = 'es';
  const round = {id: 10, arabic: true, words: [{word_key: 10, word: 'قطة', sourceWord: 'cat'}]};
  audio.prepare(round);
  assert.equal(round.translationLang, 'es');
  assert.equal(round.translationText, null);
  assert.deepEqual(translations[0].slice(0, 3), ['cat', 'EN', 'ES']);
  translations[0][3]('el gato');
  assert.equal(round.translationText, 'el gato');
});
test('menu-language changes discard the previous translation response', () => {
  const {audio, context, translations} = setup();
  const round = {id: 10, lang: 'fr', words: [{word_key: 10, word: 'le chat'}]};
  context.InterfaceData.data.lang_code = 'es';
  audio.prepare(round);
  context.InterfaceData.data.lang_code = 'ru';
  audio.prepare(round);
  translations[0][3]('el gato');
  assert.equal(round.translationText, null);
  translations[1][3]('кот');
  assert.equal(round.translationText, 'кот');
  assert.equal(round.translationLang, 'ru');
});
test('cached Spanish recording is preferred and uses its local filename', () => {
  const {audio, context, spoken} = setup('true');
  context.InterfaceData.data.lang_code = 'es';
  context.BabadumRecordings.get = (lang, id) => lang === 'es' && id === 10
    ? {word: 'el gato', audio_file: 'gato_3210', audioUrl: '/data/library/media/audio/es/gato_3210.ogg'} : null;
  const played = [];
  context.Howl = function (options) {
    this.play = () => played.push(options);
    this.unload = () => {};
  };
  const round = {id: 10, lang: 'fr', words: [{word_key: 10, word: 'le chat'}]};
  audio.prepare(round);
  assert.equal(round.translationText, 'el gato');
  audio.play(round);
  assert.equal(played.length, 1);
  assert.equal(played[0].src[0], '/data/library/media/audio/es/gato_3210.ogg');
  assert.equal(played[0].rate, 1);
  assert.equal(played[0].html5, true);
  assert.equal(spoken.length, 0);
  played[0].onend();
  assert.equal(audio.recording, null);
});
test('new and replacement translation recordings use the currently selected speed', () => {
  const {audio, context, spoken} = setup('true');
  context.InterfaceData.data.lang_code = 'es';
  context.BabadumRecordings.get = () => ({word: 'el gato',
    audioUrl: '/data/library/media/audio/es/gato_3210.ogg'});
  const recordings = [];
  context.Howl = function (options) {
    this.options = options;
    this.played = false;
    this.unloaded = false;
    this.play = () => { this.played = true; };
    this.unload = () => { this.unloaded = true; };
    recordings.push(this);
  };
  const round = {id: 10, translationText: 'el gato', translationLang: 'es'};
  for (const speed of [0.5, 1, 1.5, 2]) {
    const previous = audio.recording;
    const count = recordings.length;
    context.Game.speed = speed;
    audio.play(round);
    assert.equal(recordings.length, count + 1);
    assert.equal(audio.recording, recordings.at(-1));
    assert.equal(audio.recording.options.rate, speed);
    assert.equal(audio.recording.options.html5, true);
    assert.equal(audio.recording.played, true);
    assert.equal(audio.recording.unloaded, false);
    if (previous) {
      assert.notEqual(audio.recording, previous);
      assert.equal(previous.unloaded, true);
    }
  }
  assert.equal(spoken.length, 0);
});

test('half-speed translation recordings get a 20-second safety timer that releases playback', () => {
  const {audio, context, timers} = setup('true');
  context.Game.speed = 0.5;
  context.BabadumRecordings.get = () => ({word: 'cat', audioUrl: '/data/library/media/audio/en/cat.ogg'});
  let unloaded = 0;
  context.Howl = function (options) {
    assert.equal(options.html5, true);
    assert.equal(options.rate, 0.5);
    this.play = () => {};
    this.unload = () => unloaded++;
  };
  audio.play({id: 10, translationText: 'cat', translationLang: 'en'});
  assert.ok(audio.recording);
  assert.equal(timers.size, 1);
  const timer = timers.get(audio.timer);
  assert.equal(timer.delay, 20000);
  timer.callback();
  assert.equal(unloaded, 1);
  assert.equal(audio.recording, null);
  assert.equal(timers.size, 0);
});

test('failed original recording falls back to Spanish speech and disabling stops playback', () => {
  const {audio, context, spoken} = setup('true');
  context.InterfaceData.data.lang_code = 'es';
  context.BabadumRecordings.get = () => ({word:'el gato', audio_file:'gato_3210', audioUrl:'/data/library/media/audio/es/gato_3210.ogg'});
  let options, unloaded = 0;
  context.Howl = function (value) { options = value; this.play = () => {}; this.unload = () => unloaded++; };
  const round = {id: 10, translationText:'el gato', translationLang:'es'};
  audio.play(round);
  assert.equal(options.html5, true);
  options.onloaderror();
  assert.equal(unloaded, 1);
  assert.equal(spoken[0].lang, 'es');
  spoken[0].onend();
  audio.play(round);
  assert.equal(options.html5, true);
  audio.setEnabled(false);
  assert.equal(unloaded, 2);
  assert.equal(audio.recording, null);
});

test('downloaded Spanish recording is served from the local library', () => {
  const {audio, context} = setup('true');
  context.InterfaceData.data.lang_code = 'es';
  context.BabadumLibrary.get = () => ({word: 'el gato', audio_file: 'gato_3210',
    audioUrl: '/data/library/media/audio/es/gato_3210.ogg',
    audioUrls: ['/data/library/media/audio/es/gato_3210.ogg', '/data/library/media/audio/es/gato_3210.m4a']});
  let options;
  context.Howl = function (value) { options = value; this.play = () => {}; this.unload = () => {}; };
  audio.play({id:10, translationText:'el gato', translationLang:'es'});
  assert.equal(options.html5, true);
  assert.equal(options.src.length, 2);
  assert.equal(options.src[0], '/data/library/media/audio/es/gato_3210.ogg');
  assert.equal(options.src[1], '/data/library/media/audio/es/gato_3210.m4a');
});

test('old observed recording metadata never causes an upstream audio request', () => {
  const {audio, context, spoken} = setup('true');
  context.InterfaceData.data.lang_code = 'es';
  context.BabadumRecordings.get = () => ({word: 'el gato', audio_file: 'gato_3210'});
  context.Howl = function () { throw new Error('Remote audio must not be constructed'); };
  audio.play({id: 10, translationText: 'el gato', translationLang: 'es'});
  assert.equal(spoken.length, 1);
});

test('round-supplied native translation works with an older browser catalog', () => {
  const {audio, context, translations, spoken} = setup('true');
  context.InterfaceData.data.lang_code = 'fr';
  let options;
  context.Howl = function (value) { options = value; this.play = () => {}; this.unload = () => {}; };
  const round = {id: 10, lang: 'es', words: [{word_key: 10, word: 'el gato'}],
    nativeTranslation: {lang: 'fr', word: 'le chat', audioUrls: ['/data/library/media/audio/fr/chat_123.ogg']}};
  audio.prepare(round);
  audio.play(round);
  assert.equal(round.translationText, 'le chat');
  assert.equal(options.html5, true);
  assert.equal(options.src[0], '/data/library/media/audio/fr/chat_123.ogg');
  assert.equal(translations.length, 0);
  assert.equal(spoken.length, 0);
});
