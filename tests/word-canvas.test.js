const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app.js', 'utf8');
const adjustCanvas = source.slice(source.indexOf('BumText.prototype.adjustCanvas ='), source.indexOf('BumText.prototype.setXY ='));
function label(retinaScale, wrapped = true, setId = null) {
  const context = {BumText: function () {}, $: () => ({closest: () => ({length: wrapped ? 1 : 0})})};
  vm.createContext(context);
  vm.runInContext(adjustCanvas, context);
  const text = new context.BumText();
  Object.assign(text, {wordLabel: true, retinaScale, setId, W: 352, H: 109,
    canvas: {width: 1, height: 1, style: {}}, setXY() {}});
  return text;
}
test('wrapped phone words display at logical size while retaining a sharp canvas', () => {
  const text = label(true);
  text.adjustCanvas();
  assert.equal(text.canvas.width, 352);
  assert.equal(text.canvas.style.width, '176px');
  assert.equal(text.canvas.style.height, '54.5px');
  text.W = 280;
  text.H = 100;
  text.adjustCanvas();
  assert.equal(text.canvas.style.width, '140px');
  assert.equal(text.canvas.style.height, '50px');
});
test('standard-density wrapped words retain their original display size', () => {
  const text = label(false);
  text.adjustCanvas();
  assert.equal(text.canvas.style.width, '352px');
  assert.equal(text.canvas.style.height, '109px');
});
test('positioned canvases and shared word-choice canvases retain transform-based sizing', () => {
  for (const text of [label(true, false), label(true, true, 'choices')]) {
    text.adjustCanvas();
    assert.equal(text.canvas.style.width, undefined);
    assert.equal(text.canvas.style.height, undefined);
  }
});
