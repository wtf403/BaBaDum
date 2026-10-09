const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app.js', 'utf8').split('// Optional speech')[1].split('// HanziWriter integration')[0];
function setup(saved, supported = true) {
  const spoken = [], storage = {}, timers = new Map();
  let canceled = 0;
  const speechSynthesis = {getVoices: () => [{lang: 'en-US'}, {lang: 'ru-RU'}],
    speak: speech => spoken.push(speech), cancel: () => canceled++};
  const context = {Sounds: {active: true}, localStorage: {
    getItem: () => saved, setItem: (key, value) => storage[key] = value},
    window: supported ? {speechSynthesis, SpeechSynthesisUtterance: function () {}} : {},
    SpeechSynthesisUtterance: function (text) { this.text = text; },
    setTimeout: callback => { timers.set(timers.size + 1, callback); return timers.size; },
    clearTimeout: id => timers.delete(id)};
  vm.createContext(context);
  vm.runInContext('// Optional speech' + source, context);
  return {audio: context.TranslationAudio, spoken, storage, timers, context, canceled: () => canceled};
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
  [...timers.values()][0]();
  assert.equal(audio.speech, null);
});
