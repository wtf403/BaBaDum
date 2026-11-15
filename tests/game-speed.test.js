const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
const gameSource = source.slice(source.indexOf('\nGame = {'), source.indexOf('  init: function () {', source.indexOf('\nGame = {'))) + '};';
const wordsSource = source.slice(source.indexOf('\nWords = {'), source.indexOf('\nAJAX = {'));
const menuSource = source.slice(source.indexOf('UserMenu.btn_state = {'), source.indexOf('UserMenu.prototype.onReceive ='));

function setup(localStorage = {}) {
  const context = {localStorage, TranslationAudio: {enabled: false, recording: null},
    BabadumLibrary: {get: () => null}, Sounds: {onWordEnd() {}}, window: {}, log() {}};
  vm.createContext(context);
  vm.runInContext(gameSource + wordsSource, context);
  return context;
}

function setupMenu() {
  const context = setup();
  const span = {0: {style: {}}, html() { return this; }};
  context.InterfaceData = {data: {lang_code: 'en'}, get: key => key, getUserName: () => 'Player'};
  context.$ = target => target;
  context.BumButton = function (label, onClick) {
    this.label = label;
    this.onClick = onClick;
    this.W = label.length;
    const attrs = {name: label + '_btn'};
    this.btn = {attr(name, value) {
      if (typeof name === 'object') Object.assign(attrs, name);
      else if (arguments.length === 1) return attrs[name];
      else attrs[name] = value;
      return this;
    }};
    this.el = {css() { return this; }, insertAfter() { return this; }};
    this.remove = () => { this.removed = true; };
  };
  vm.runInContext(menuSource, context);
  const Menu = context.UserMenu;
  const menu = Object.assign(Object.create(Menu.prototype), {
    btn_state: Menu.btn_state, btns: [], enabled: true,
    label: {find: () => span}, setBG() {},
  });
  context.UserMenu = menu;
  return context;
}

function clickSpeed(menu, target = {attr: () => 'gameSpeed_btn'}) {
  let prevented = false;
  menu.onClick({target, preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
}

test('game speed defaults to 1 and restores every supported saved speed', () => {
  assert.deepEqual(Array.from(setup().Game.speedOptions), [0.5, 1, 1.5, 2]);
  for (const speed of [0.5, 1, 1.5, 2]) {
    const {Game} = setup({gameSpeed: String(speed)});
    assert.equal(Game.speed, 1);
    Game.initSpeed();
    assert.equal(Game.speed, speed);
  }
});

test('missing, invalid and unsupported saved speeds keep the default', () => {
  for (const saved of [undefined, null, '', 'invalid', 'NaN', 'Infinity', '0', '-1', '1.25', '3', '4']) {
    const {Game} = setup({gameSpeed: saved});
    Game.initSpeed();
    assert.equal(Game.speed, 1, String(saved));
  }
});

test('denied or unavailable storage does not prevent speed initialization', () => {
  const denied = setup({get gameSpeed() { throw Error('Storage denied'); }});
  assert.doesNotThrow(() => denied.Game.initSpeed());
  assert.equal(denied.Game.speed, 1);
  const unavailable = setup();
  delete unavailable.localStorage;
  assert.doesNotThrow(() => unavailable.Game.initSpeed());
  assert.equal(unavailable.Game.speed, 1);
});

test('setSpeed accepts supported numbers and numeric strings and persists strings', () => {
  const {Game, localStorage} = setup();
  for (const speed of [0.5, '0.5', 1.5, '2', '1']) {
    Game.setSpeed(speed);
    assert.equal(Game.speed, Number(speed));
    assert.equal(localStorage.gameSpeed, String(speed));
  }
});

test('setSpeed rejects invalid values without persistence or audio changes', () => {
  const writes = [], rates = [];
  const context = setup({set gameSpeed(value) { writes.push(value); }});
  const {Game, Words, TranslationAudio} = context;
  Game.speed = 1.5;
  Words.arr = [{sound: {rate: value => rates.push(value)}}];
  Words.current = {sound: {rate: value => rates.push(value)}};
  TranslationAudio.recording = {rate: value => rates.push(value)};
  for (const invalid of [undefined, null, '', false, {}, 'invalid', NaN, Infinity, 0, -1, 1.25, 3, '3', 4]) {
    Game.setSpeed(invalid);
    assert.equal(Game.speed, 1.5, String(invalid));
  }
  assert.deepEqual(writes, []);
  assert.deepEqual(rates, []);
});

test('setSpeed updates queued and active sounds while skipping fake or non-rate sounds', () => {
  const {Game, Words, TranslationAudio} = setup();
  function sound() {
    return {rates: [], rate(value) { this.rates.push(value); }};
  }
  const queued = [sound(), sound()], active = sound(), translation = sound();
  TranslationAudio.recording = translation;
  Words.arr = [...queued.map(sound => ({sound})), {}, {sound: null},
    {sound: {fake: true, _loaded: true}}, {sound: {rate: 2}}];
  Words.current = {sound: active};
  Game.setSpeed(2);
  Game.setSpeed(0.5);
  for (const recording of [...queued, active, translation]) assert.deepEqual(recording.rates, [2, 0.5]);
});

test('setSpeed works without an active round', () => {
  const {Game, Words} = setup();
  const rates = [];
  Words.arr = [{sound: {rate: value => rates.push(value)}}];
  for (const current of [undefined, null]) {
    Words.current = current;
    assert.doesNotThrow(() => Game.setSpeed(1.5));
  }
  assert.deepEqual(rates, [1.5, 1.5]);
});

test('storage write failures still update the speed, round sounds and active translation', () => {
  let writes = 0;
  const rates = [];
  const {Game, Words, TranslationAudio} = setup({set gameSpeed(value) {
    writes++;
    assert.equal(value, '2');
    throw Error('Storage denied');
  }});
  Words.arr = [{sound: {rate: value => rates.push(['queued', value])}}];
  Words.current = {sound: {rate: value => rates.push(['active', value])}};
  TranslationAudio.recording = {rate(value) {
    assert.equal(this, TranslationAudio.recording);
    rates.push(['translation', value]);
  }};
  assert.doesNotThrow(() => Game.setSpeed(2));
  assert.equal(writes, 1);
  assert.equal(Game.speed, 2);
  assert.deepEqual(rates, [['queued', 2], ['active', 2], ['translation', 2]]);
});

test('speed menu action closes, cycles every option, wraps and refreshes in order', () => {
  const {Game, UserMenu: menu, localStorage} = setupMenu();
  const calls = [];
  const setSpeed = Game.setSpeed;
  menu.showMenu = close => calls.push(['close', close]);
  Game.setSpeed = speed => { calls.push(['speed', speed]); setSpeed(speed); };
  menu.set = force => calls.push(['refresh', force]);
  for (const speed of [1.5, 2, 0.5, 1]) {
    clickSpeed(menu);
    assert.equal(Game.speed, speed);
    assert.equal(localStorage.gameSpeed, String(speed));
    assert.deepEqual(calls.splice(0), [['close', true], ['speed', speed], ['refresh', true]]);
  }
});

test('disabled speed menu action prevents the event but does not change anything', () => {
  const {Game, UserMenu: menu, localStorage} = setupMenu();
  menu.enabled = false;
  const unexpected = () => assert.fail('Disabled menu must not act');
  menu.showMenu = menu.set = Game.setSpeed = unexpected;
  clickSpeed(menu, {attr: unexpected});
  assert.equal(Game.speed, 1);
  assert.equal(localStorage.gameSpeed, undefined);
});

test('speed menu renders accurate labels and a stable action name in both auth states', () => {
  const context = setupMenu();
  const {Game, UserMenu: menu} = context;
  for (const user of [null, {options: {lang_code: 'en', progress_enabled: false}},
    {options: {lang_code: 'en', progress_enabled: true}}]) {
    context.window.UserData = context.UserData = user;
    for (const speed of [0.5, 1, 1.5, 2]) {
      Game.setSpeed(speed);
      const oldButtons = menu.btns.slice();
      menu.set(true);
      assert.equal(menu.state, user ? 'in' : 'out');
      assert.equal(menu.btn_state[menu.state].filter(button => button.l === 'gameSpeed').length, 1);
      const buttons = menu.btns.filter(button => button.btn.attr('name') === 'gameSpeed_btn');
      assert.equal(buttons.length, 1);
      assert.equal(buttons[0].label, 'Game speed: ' + speed + '×');
      assert.equal(buttons[0].onClick, menu.onClick);
      assert.ok(oldButtons.every(button => button.removed));
    }
  }
});

test('rendered speed button cycles and rebuilds its label', () => {
  const {UserMenu: menu, Game} = setupMenu();
  const closes = [];
  menu.showMenu = close => closes.push(close);
  menu.set(true);
  const button = menu.btns.find(button => button.btn.attr('name') === 'gameSpeed_btn');
  clickSpeed(menu, button.btn);
  assert.deepEqual(closes, [true]);
  assert.equal(Game.speed, 1.5);
  assert.equal(button.removed, true);
  assert.equal(menu.btns.find(button => button.btn.attr('name') === 'gameSpeed_btn').label, 'Game speed: 1.5×');
});

test('round audio constructors use the selected speed for round and library URLs', () => {
  const context = setup();
  const {Game, Words, BabadumLibrary, Sounds} = context;
  const options = [];
  context.Howl = function (value) { options.push(value); };
  const url = '/data/library/media/audio/en/cat.ogg';
  for (const speed of [0.5, 1, 1.5, 2]) {
    for (const entry of [null, {audioUrls: [url]}, {audioUrl: url}]) {
      BabadumLibrary.get = (lang, id) => {
        assert.equal(lang, 'en');
        assert.equal(id, 10);
        return entry;
      };
      Game.setSpeed(speed);
      const round = {id: 10, lang: 'en', game: 'chooseImageSound'};
      if (!entry) round.audioUrls = [url];
      Words.loadRoundAudio(round);
      const value = options.at(-1);
      assert.ok(round.sound instanceof context.Howl);
      assert.equal(value.rate, speed);
      assert.equal(value.html5, true);
      assert.deepEqual(Array.from(value.src), [url]);
      assert.equal(value.onload, Words.onAudioLoad);
      assert.equal(value.onloaderror, Words.onAudioError);
      assert.equal(value.onend, Sounds.onWordEnd);
    }
  }
});

test('bundled HTML5 playback enables native pitch preservation before setting the rate', () => {
  assert.match(source, /k\.preservesPitch\s*=\s*k\.mozPreservesPitch\s*=\s*k\.webkitPreservesPitch\s*=\s*!0;\s*k\.playbackRate\s*=\s*g\._rate/);
});

test('sound effects do not opt into HTML5 playback or game speed', () => {
  const soundsStart = source.indexOf('\nSounds = {');
  const soundsEnd = source.indexOf('\nfunction Thumb(', soundsStart);
  assert.ok(soundsStart >= 0 && soundsEnd > soundsStart);
  const soundsSource = source.slice(soundsStart, soundsEnd);
  assert.match(soundsSource, /new Howl\(/);
  assert.doesNotMatch(soundsSource, /\bhtml5\s*:\s*(?:true|!0)\b/);
  assert.doesNotMatch(soundsSource, /\brate\s*:\s*Game\.speed/);
});

test('rounds without audio or browser audio support stay ready and accept speed changes', () => {
  for (const unsupported of [false, true]) {
    const context = setup();
    const {Game, Words} = context;
    let loaded = 0;
    context.window.audioNotImplemented = unsupported;
    context.Howl = function () { assert.fail('No audio should be constructed'); };
    Words.onAudioLoad = () => loaded++;
    const round = {id: 10, lang: 'en'};
    if (unsupported) round.audioUrls = ['/data/library/media/audio/en/cat.ogg'];
    Words.loadRoundAudio(round);
    assert.equal(round.sound.fake, true);
    assert.equal(round.sound._loaded, true);
    assert.equal(loaded, 1);
    Words.arr = [round];
    assert.doesNotThrow(() => Game.setSpeed(0.5));
    assert.equal(Game.speed, 0.5);
  }
});
