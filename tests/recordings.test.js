const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('recordings.js', 'utf8');
function setup(storage = {}) {
  const context = {Langs: [{id: 1, code: 'us'}, {id: 4, code: 'es'}, {id: 5, code: 'fr'}],
    localStorage: {getItem: key => storage[key], setItem: (key, value) => storage[key] = value}};
  vm.createContext(context); vm.runInContext(source, context);
  return {index: context.BabadumRecordings, storage, context};
}
function spanish() {
  return {lang: 'es', words: [
    {word_key: '1253', id: '3141', word: 'volar', lang_key: 4, audio_file: 'volar_3141'}
  ]};
}
test('native metadata is indexed by shared concept and restored from storage', () => {
  const {index, storage} = setup();
  index.remember({data: spanish()});
  assert.equal(index.get('es', 1253).audio_file, 'volar_3141');
  assert.equal(index.get('es', 3141), null);
  assert.equal(setup(storage).index.get('es', '1253').word, 'volar');
  assert.equal(index.getByText('es', ' volar ').audio_file, 'volar_3141');
});
test('record language takes precedence and languages retain distinct recordings', () => {
  const {index} = setup();
  index.remember(spanish());
  index.remember({lang: 'es', words: [
    {word_key: 1253, id: 6508, word: 'voler', lang_key: 5, audio_file: 'voler_6508'}
  ]});
  assert.equal(index.get('fr', 1253).word, 'voler');
  assert.equal(index.get('es', 1253).word, 'volar');
  for (const [menu, native] of Object.entries({en:'us',zh:'cn',ja:'jp',sv:'se',cs:'cz',el:'gr'}))
    assert.equal(index.normalizeLanguage(menu), native);
});
test('invalid filenames and IDs cannot enter memory or restored storage', () => {
  const {index} = setup();
  for (const file of ['../word_1', 'folder/word', 'folder\\word', 'word?x', 'word#x', 'word\n']) {
    const round = spanish(); round.words[0].audio_file = file;
    index.remember(round); assert.equal(index.get('es', 1253), null);
  }
  for (const field of ['id', 'word_key']) {
    const round = spanish(); round.words[0][field] = 'bad';
    index.remember(round); assert.equal(index.get('es', 1253), null);
  }
  const restored = setup({'babadumRecordings-v1': JSON.stringify({'es:1253': {word:'bad',audio_file:'../bad'}})});
  assert.equal(restored.index.get('es', 1253), null);
});
test('unavailable and corrupt storage preserve safe in-memory playback', () => {
  const {index, context} = setup({'babadumRecordings-v1':'broken JSON'});
  context.localStorage.setItem = () => {throw Error('disabled');};
  index.remember(spanish());
  assert.equal(index.get('es', 1253).word, 'volar');
  const noStorage = {}; vm.createContext(noStorage); vm.runInContext(source, noStorage);
  noStorage.BabadumRecordings.remember(spanish());
  assert.equal(noStorage.BabadumRecordings.get('es',1253).word, 'volar');
});
test('remembering native round before Arabic mutation retains original English metadata', () => {
  const {index} = setup();
  const round = {lang:'us', lang_key:1, words:[
    {word_key:10,id:51,word:'cat',lang_key:1,audio_file:'cat_51'}
  ]};
  index.remember(round);
  round.lang = 'ar'; round.lang_key = 100; round.words[0].word = 'قطة';
  assert.equal(index.get('en',10).word, 'cat');
  const copy = index.get('en',10); copy.word = 'changed';
  assert.equal(index.get('en',10).word, 'cat');
  assert.equal(index.get('ar',10), null);
});
