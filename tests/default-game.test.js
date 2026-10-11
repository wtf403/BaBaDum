const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
const gameSource = source.slice(source.indexOf('\nGame = {'));
const init = gameSource.slice(gameSource.indexOf('  init: function () {') + '  init: function () {'.length, gameSource.indexOf('    Game.b_canvas ='));
function selectedGame(saved, query = null, storageAvailable = true) {
  const context = {
    Game: {defaultLangID: 7, defaultGameType: 'chooseImage', getLangCode: () => 'gb',
      getGameName: id => ({1:'chooseImage', 2:'chooseImageSound', 5:'shuffleGames'}[id] || 'chooseImage')},
    GameTypes: {chooseImage: {}, chooseImageSound: {}, shuffleGames: {}},
    Address: {getParam: name => name === 'game' ? query : null},
    Modernizr: {localstorage: storageAvailable}, localStorage: saved,
  };
  vm.runInNewContext(init, context);
  return context.Game.gameType;
}
test('new visitors always start with game A', () => {
  assert.equal(selectedGame({}), 'chooseImage');
  assert.equal(selectedGame({}, null, false), 'chooseImage');
});
test('explicit game choices remain selected', () => {
  assert.equal(selectedGame({gameType:'chooseImageSound'}), 'chooseImageSound');
  assert.equal(selectedGame({gameType:'shuffleGames'}), 'shuffleGames');
  assert.equal(selectedGame({}, '2'), 'chooseImageSound');
  assert.equal(selectedGame({gameType:'chooseImageSound'}, '1'), 'chooseImage');
});
test('invalid or inaccessible saved settings fall back to game A', () => {
  assert.equal(selectedGame({gameType:'invalid'}), 'chooseImage');
  assert.equal(selectedGame({gameType:'toString'}), 'chooseImage');
  assert.equal(selectedGame({get gameType() {throw Error('Storage denied');}}), 'chooseImage');
});
