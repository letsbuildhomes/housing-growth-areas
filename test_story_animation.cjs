const {test} = require('node:test');
const assert = require('node:assert/strict');
const {compile, player, timing} = require('./web/story-animation.js');

const initial = [{style: {opacity: 0, fillColor: '#000000'}}];
const timeline = () => compile(initial, [
  [() => ({opacity: 1}), () => ({fillColor: '#ffffff'}), () => ({opacity: 0.5})],
  [() => ({opacity: 0}), () => ({fillColor: '#000000'}), () => ({opacity: 1})],
]);
function harness(reduced = false, duration = timing.duration) {
  let time = 0, callback, id = 0, current;
  const controller = player(timeline(), (items, position) => {current = {items, position};}, {
    now: () => time, reduced: () => reduced, config: {...timing, duration},
    requestFrame: fn => {callback = fn; return ++id;},
    cancelFrame: () => {callback = null;},
  });
  return {go: controller.go, get current() {return current;},
    get pending() {return !!callback;},
    tick(ms) {time += ms; const fn = callback; callback = null; if (fn) fn(time);},
  };
}
test('three equal phases and half-length gaps produce exact endpoint and hold states', () => {
  const t = timeline();
  assert.deepEqual(t.stops, [0, 4, 8]);
  assert.equal(t.sample(0.5)[0].style.opacity, 0.5);
  assert.deepEqual(t.sample(1)[0].style, t.sample(1.4)[0].style);
  assert.equal(t.sample(2)[0].style.fillColor, '#808080');
  assert.deepEqual(t.sample(2.5)[0].style, t.sample(2.9)[0].style);
  assert.equal(t.sample(4)[0].style.opacity, 0.5);
});
test('reverse retraces phases and gaps at twice the forward speed', () => {
  const h = harness(); h.go(1); h.tick(3600);
  assert.equal(h.current.position, 4); assert.equal(h.pending, false);
  h.go(0); h.tick(225);
  assert.equal(h.current.position, 3.5);
  assert.deepEqual(h.current.items, timeline().sample(3.5));
  h.tick(1575); assert.equal(h.current.position, 0); assert.equal(h.pending, false);
});
test('rapid retargeting preserves the playhead and never applies a stale destination', () => {
  const h = harness(); h.go(1); h.tick(1800);
  const before = h.current; h.go(0); assert.deepEqual(h.current, before);
  h.tick(225); assert.equal(h.current.position, 1.5);
  h.go(2); h.tick(450); assert.equal(h.current.position, 2);
  h.go(0); h.tick(900); assert.equal(h.current.position, 0);
  h.tick(10000); assert.equal(h.current.position, 0); assert.equal(h.pending, false);
});
test('changing duration scales phases, gaps and reverse playback together', () => {
  const h = harness(false, 1800); h.go(2); h.tick(14400);
  assert.equal(h.current.position, 8);
  h.go(0); h.tick(7200); assert.equal(h.current.position, 0);
});
test('reduced motion goes directly to the requested chapter', () => {
  const h = harness(true); h.go(2); assert.equal(h.current.position, 8);
  h.go(0); assert.equal(h.current.position, 0); assert.equal(h.pending, false);
});
