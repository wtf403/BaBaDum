const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('library.js', 'utf8');
function setup() {
  const requests = [];
  const context = {XMLHttpRequest: function () {
    requests.push(this);
    this.open = (method, url, async) => Object.assign(this, {method, url, async});
    this.send = () => {};
  }};
  vm.createContext(context); vm.runInContext(source, context);
  return {library: context.BabadumLibrary, requests};
}
function manifest() {
  return {version:1, languages:{es:{id:4,words:{1253:{
    id:'3141', word:'volar', audio_file:'volar_3141',
    image:'media/images/1253.svg', audio:'media/audio/es/volar_3141.ogg'
  }}}, us:{id:1,words:{1253:{
    id:'1',word:'fly',audio_file:'fly_1',audio:'media/audio/us/fly_1.ogg'
  }}}}};
}
function respond(request, value, status = 200) {
  request.status = status;
  request.responseText = typeof value === 'string' ? value : JSON.stringify(value);
  request.onload();
}
test('one asynchronous local manifest request serves concurrent and later callers', () => {
  const {library, requests} = setup();
  const completions = [];
  assert.equal(library.get('es',1253),null);
  library.load(ok => completions.push(ok)); library.load(ok => completions.push(ok));
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,'/data/library/vocabulary.json');
  assert.equal(requests[0].method,'GET'); assert.equal(requests[0].async,true);
  respond(requests[0],manifest());
  library.load(ok => completions.push(ok));
  assert.deepEqual(completions,[true,true,true]);
  assert.equal(requests.length,1);
  assert.equal(library.get('es',1253).audioUrl,'/data/library/media/audio/es/volar_3141.ogg');
  assert.equal(library.get('es',1253).imageUrl,'/data/library/media/images/1253.svg');
  assert.equal(library.get('en',1253).word,'fly');
  assert.equal(library.get('es',3141),null);
  assert.equal(library.get('fr',1253),null);
});
test('missing, malformed, failed or timed out manifests return graceful misses', () => {
  for (const failure of ['missing','json','version','error','timeout']) {
    const {library, requests} = setup(); const completions = [];
    library.load(ok => completions.push(ok));
    if (failure === 'missing') respond(requests[0],{},404);
    if (failure === 'json') respond(requests[0],'invalid JSON');
    if (failure === 'version') respond(requests[0],{version:2,languages:{}});
    if (failure === 'error') requests[0].onerror();
    if (failure === 'timeout') requests[0].ontimeout();
    assert.deepEqual(completions,[false]);
    assert.equal(library.get('es',1253),null);
    library.load(); assert.equal(requests.length,1);
  }
});
test('local audio paths cannot traverse directories, switch language or point upstream', () => {
  for (const audio of ['../volar_3141.ogg','media/audio/es/../volar_3141.ogg',
    'media/audio/es/%2e%2e%2fvolar_3141.ogg','media/audio/fr/volar_3141.ogg',
    'https://babadum.com/audio/es/volar_3141.ogg','media/audio/es/volar_3141.ogg?x',
    'media/audio/es/other_3141.ogg','media/audio/es/volar_3141.html']) {
    const {library,requests} = setup(); const value = manifest();
    value.languages.es.words[1253].audio = audio;
    library.load(); respond(requests[0],value);
    assert.equal(library.get('es',1253).audioUrl,null,audio);
  }
});
test('metadata-only records retain the exact remote filename without claiming a local download', () => {
  const {library,requests} = setup(); const value = manifest();
  delete value.languages.es.words[1253].audio;
  library.load(); respond(requests[0],value);
  const record = library.get('es',1253);
  assert.equal(record.word,'volar');
  assert.equal(record.audio_file,'volar_3141');
  assert.equal(record.audioUrl,null);
});
test('invalid record IDs and filenames are rejected and results cannot mutate the index', () => {
  for (const field of ['id','audio_file']) {
    const {library,requests} = setup(); const value = manifest();
    value.languages.es.words[1253][field] = '../bad';
    library.load(); respond(requests[0],value);
    assert.equal(library.get('es',1253),null);
  }
  const {library,requests} = setup(); library.load(); respond(requests[0],manifest());
  library.get('es',1253).word = 'changed';
  assert.equal(library.get('es',1253).word,'volar');
  assert.equal(library.get('es','bad'),null);
});
test('local m4a fallback recordings are usable', () => {
  const {library, requests} = setup(); const value = manifest();
  value.languages.es.words[1253].audio = 'media/audio/es/volar_3141.m4a';
  library.load(); respond(requests[0],value);
  assert.equal(library.get('es',1253).audioUrl,'/data/library/media/audio/es/volar_3141.m4a');
});
test('local primary and alternate audio provide validated sources for browser format selection', () => {
  const {library, requests} = setup(); const value = manifest();
  value.languages.es.words[1253].audio_alt = 'media/audio/es/volar_3141.m4a';
  library.load(); respond(requests[0],value);
  assert.deepEqual(Array.from(library.get('es',1253).audioUrls),[
    '/data/library/media/audio/es/volar_3141.ogg',
    '/data/library/media/audio/es/volar_3141.m4a'
  ]);
  assert.equal(library.get('es',1253).audioUrl,'/data/library/media/audio/es/volar_3141.ogg');
});
test('malicious or unrelated alternate paths cannot become audio sources', () => {
  for (const alternate of ['media/audio/es/../volar_3141.m4a',
    'https://elsewhere.test/volar_3141.m4a', 'media/audio/fr/volar_3141.m4a',
    'media/audio/es/%2e%2e%2fvolar_3141.m4a','media/audio/es/other_3141.m4a',
    'media/audio/es/volar_3141.m4a?x']) {
    const {library, requests} = setup(); const value = manifest();
    value.languages.es.words[1253].audio_alt = alternate;
    library.load(); respond(requests[0],value);
    assert.deepEqual(Array.from(library.get('es',1253).audioUrls),[
      '/data/library/media/audio/es/volar_3141.ogg'
    ],alternate);
  }
});
test('local SVG images hydrate asynchronously and shared image requests are cached', () => {
  const {library, requests} = setup(); library.load(); respond(requests[0],manifest());
  const round = {lang:'es',words:[{word_key:1253,img:'upstream'},{word_key:1253,img:'upstream'}]};
  let finished = 0;
  library.loadImages(round,() => finished++);
  assert.equal(finished,0); assert.equal(requests.length,2);
  assert.equal(requests[1].url,'/data/library/media/images/1253.svg');
  respond(requests[1],'<svg xmlns="http://www.w3.org/2000/svg"><path/></svg>');
  assert.equal(finished,1);
  assert.match(round.words[0].img, /^<svg/);
  assert.equal(round.words[0].img,round.words[1].img);
  const again = {lang:'es',words:[{word_key:1253,img:'upstream'}]};
  library.loadImages(again,() => finished++);
  assert.equal(finished,2); assert.equal(requests.length,2);
  assert.equal(again.words[0].img,round.words[0].img);
});
test('failed, invalid or absent local images preserve upstream images and finish once', () => {
  for (const failure of ['http','invalid','network']) {
    const {library, requests} = setup(); library.load(); respond(requests[0],manifest());
    const round = {lang:'es',words:[{word_key:1253,img:'upstream'},{word_key:99,img:'other'}]};
    let finished = 0;
    library.loadImages(round,() => finished++);
    if (failure === 'http') respond(requests[1],'missing',404);
    if (failure === 'invalid') respond(requests[1],'<html>not svg</html>');
    if (failure === 'network') requests[1].onerror();
    requests[1].onerror();
    assert.equal(finished,1);
    assert.equal(round.words[0].img,'upstream'); assert.equal(round.words[1].img,'other');
  }
  const {library} = setup(); let finished = 0;
  library.loadImages({words:[]},() => finished++);
  library.loadImages(null,() => finished++);
  assert.equal(finished,2);
});
