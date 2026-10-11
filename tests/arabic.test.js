const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function setup(game = 'chooseImage') {
  const requests = [], notices = [], storage = {};
  const context = {console, Date, JSON, Math, Array, Object,
    Game: {langID: 100, gameType: game}, Words: {arr: [], min_loaded: 1, ready() {}},
    BabadumRecordings: {remember() {}},
    BabadumLibrary: {loadImages(round, done) {done();}},
    TranslationAudio: {enabled: false, menuLanguage: () => "us", prepare(round) {
      round.translationText = round.words.find(w => w.word_key == round.id).sourceWord;
      round.translationLang = 'en';
    }},
    Sounds: {onWordEnd() {}}, DeepLTranscription: {getApiKey: () => 'test'},
    localStorage: {getItem: k => storage[k], setItem: (k,v) => storage[k]=v},
    window: {}, $: () => ({remove() {}})};
  context.$.ajax = r => requests.push(r);
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('arabic.js', 'utf8'), context);
  context.ArabicLearning.notice = (message, retry) => notices.push({message,retry});
  return {context, requests, notices, learning: context.ArabicLearning};
}
function round() {
  return {data: {id: 10, game: 'chooseImage', lang_key: 1, words: [
    {word: 'cat', id: 51, word_key: 10}, {word: 'dog', id: 52, word_key: 11}
  ]}};
}
test('English round is not playable until all Arabic choices are translated; IDs survive', () => {
  const {learning, requests, context} = setup();
  learning.get(); learning.get();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].data.lang, 1);
  requests.shift().success(round());
  assert.equal(context.Words.arr.length, 0);
  assert.deepEqual(JSON.parse(requests[0].data).text, ['cat','dog']);
  requests.shift().success({translations: [{text:'قطة'}, {text:'كلب'}]});
  assert.equal(context.Words.arr[0].words[0].word, 'قطة');
  assert.equal(context.Words.arr[0].words[0].id, 51);
  assert.equal(context.Words.arr[0].lang_key, 100);
  assert.equal(context.Words.arr[0].sound.fake, true);
});
test('cached translations avoid API requests', () => {
  const {learning, requests, context} = setup();
  learning.cache.cat = 'قطة'; learning.cache.dog = 'كلب';
  learning.get(); requests.shift().success(round());
  assert.equal(requests.length, 0);
  assert.equal(context.Words.arr.length, 1);
});
test('switching language discards an in-flight translation', () => {
  const {learning, requests, context} = setup();
  learning.get(); requests.shift().success(round());
  const translation = requests.shift();
  learning.reset(); context.Game.langID = 1;
  translation.success({translations:[{text:'قطة'}, {text:'كلب'}]});
  assert.equal(context.Words.arr.length, 0);
  assert.equal(learning.pending, null);
});
test('duplicate Arabic labels skip ambiguous rounds with a finite retry limit', () => {
  const {learning, requests, context, notices} = setup();
  learning.cache.cat = learning.cache.dog = 'حيوان';
  learning.get();
  for (let i=0;i<5;i++) requests.shift().success(round());
  assert.equal(requests.length, 0);
  assert.equal(context.Words.arr.length, 0);
  assert.equal(notices.at(-1).retry, true);
});
test('API failure unlocks retry without exposing an English round', () => {
  const {learning, requests, context, notices} = setup();
  learning.get(); requests.shift().success(round()); requests.shift().error();
  assert.equal(learning.pending, null);
  assert.equal(context.Words.arr.length, 0);
  assert.equal(notices.at(-1).retry, true);
  learning.get(); assert.equal(requests.length, 1);
});
test('spelling and unavailable Arabic audio request picture games instead', () => {
  for (const game of ['setLetters', 'chooseImageSound']) {
    const {learning, requests} = setup(game);
    learning.get(); assert.equal(requests[0].data.game, 'chooseImage');
  }
});
test('pronunciation uses the correct Arabic word and voice', () => {
  const {learning, requests, context} = setup('chooseImageSound');
  const spoken = [];
  context.window.speechSynthesis = {getVoices: () => [{lang:'ar-SA'}], cancel() {}, speak: s => spoken.push(s)};
  context.SpeechSynthesisUtterance = function(text) {this.text=text;};
  learning.cache.cat='قطة'; learning.cache.dog='كلب';
  learning.get(); assert.equal(requests[0].data.game, 'chooseImageSound');
  requests.shift().success(round()); context.Words.arr[0].sound.play();
  assert.equal(spoken[0].text, 'قطة'); assert.equal(spoken[0].lang, 'ar-SA');
});
