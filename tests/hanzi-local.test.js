const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js','utf8').split('// HanziWriter integration for Chinese characters')[1].split('// Pinyin helper')[0];
function setup() {
  const requests = [], chars = [];
  function $(value) {
    if (typeof value !== 'string') return value;
    const node = {values:{}, handlers:{}, empty() {return this;}, append() {return this;},
      css() {return this;}, remove() {return this;}, text(value) {this.label=value;return this;},
      data(key,value) {if (arguments.length === 1) return this.values[key];this.values[key]=value;return this;},
      on(event,handler) {this.handlers[event]=handler;return this;}};
    node[0] = node;
    return node;
  }
  $.getJSON = url => {
    const request = {url,done(fn) {this.success=fn;return this;},fail(fn) {this.failure=fn;return this;}};
    requests.push(request);return request;
  };
  const context = {$,setTimeout() {},HanziWriter:{create(target,char,config) {
    const writer = {hideCharacter() {throw Error('disabled writer should not animate');},animateCharacter() {}};
    chars.push({target,char,config,writer});return writer;
  }}};
  vm.createContext(context);vm.runInContext(source,context);
  return {manager:context.HanziWriterManager,requests,chars};
}
test('Chinese stroke data loads only from the local character endpoint', () => {
  const {manager,requests,chars} = setup();manager.create('猫',{});
  let loaded = null;
  chars[0].config.charDataLoader('猫', data => loaded=data, () => assert.fail('unexpected failure'));
  assert.equal(requests[0].url,'/data/hanzi/%E7%8C%AB.json');
  requests[0].success({strokes:['path'],medians:[[]]});
  assert.equal(loaded.strokes[0],'path');
});
test('missing local strokes show the character and disable animation clicks without another request', () => {
  const {manager,requests,chars} = setup();manager.create('猫',{});
  let failures = 0;
  chars[0].config.charDataLoader('猫',() => assert.fail('unexpected success'),() => failures++);
  requests[0].failure();
  assert.equal(failures,1);assert.equal(chars[0].target.label,'猫');
  chars[0].target.handlers.click.call(chars[0].target,{preventDefault() {},stopPropagation() {}});
  assert.equal(requests.length,1);
});
