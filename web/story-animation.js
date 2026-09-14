/* A reversible playhead: phase lengths are 1 unit, gaps are proportional.
 * Navigation changes the destination, never the rendered starting state. */
(() => {
  'use strict';
  const timing = {duration: 900, gapRatio: 0.5, reverseSpeed: 2};
  const ease = t => t * t * (3 - 2 * t);
  function mix(from, to, amount) {
    if (amount === 0) return from;
    if (amount === 1) return to;
    if (typeof from === 'number') return from + (to - from) * amount;
    const rgb = hex => hex.slice(1).match(/../g).map(v => parseInt(v, 16));
    return '#' + rgb(from).map((v, i) => Math.round(v + (rgb(to)[i] - v) * amount)
      .toString(16).padStart(2, '0')).join('');
  }
  function compile(initial, groups, gapRatio = timing.gapRatio) {
    let state = initial, position = 0;
    const segments = [], stops = [0];
    groups.forEach(group => {
      group.forEach((phase, index) => {
        if (index) position += gapRatio;
        const next = state.map(item => ({...item, style: {...item.style, ...phase(item)}}));
        segments.push({start: position, end: position + 1, from: state, to: next});
        position += 1;
        state = next;
      });
      stops.push(position);
    });
    return {stops, sample(position) {
      const segment = segments.find(s => position <= s.end) || segments[segments.length - 1];
      const amount = ease(Math.max(0, Math.min(1, (position - segment.start) / (segment.end - segment.start))));
      return segment.from.map((item, i) => ({...item, style: Object.fromEntries(
        Object.entries(segment.to[i].style).map(([key, value]) => [key, mix(item.style[key], value, amount)]))}));
    }};
  }
  function player(timeline, render, {
    requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame,
    now = () => performance.now(), reduced = () => false, config = timing,
  } = {}) {
    let position = 0, target = 0, frame = null, last = now();
    function advance(time) {
      const direction = Math.sign(target - position);
      const distance = Math.max(0, time - last) / config.duration * (direction < 0 ? config.reverseSpeed : 1);
      position += direction * Math.min(Math.abs(target - position), distance);
      last = time;
    }
    function draw() { render(timeline.sample(position), position); }
    function tick(time) {
      frame = null;
      if (reduced()) position = target;
      else advance(time);
      draw();
      if (position !== target) frame = requestFrame(tick);
    }
    draw();
    return {go(step) {
      if (step < 0 || step >= timeline.stops.length) return;
      // Account for elapsed time in the old direction before retargeting.
      advance(now());
      target = timeline.stops[step];
      if (frame !== null) cancelFrame(frame);
      frame = null;
      if (reduced()) position = target;
      draw();
      if (position !== target) frame = requestFrame(tick);
    }};
  }
  // Cards start after a quarter interval; map phases start halfway through.
  // Both arrive at the next stop exactly, independent of scroll speed.
  function scrollState(chapter, stops) {
    const value = Math.max(0, Math.min(stops.length - 1, chapter));
    const from = Math.min(stops.length - 2, Math.floor(value));
    const amount = Math.max(0, Math.min(1, (value - from - 0.25) / 0.75));
    const mapAmount = Math.max(0, Math.min(1, (value - from - 0.5) / 0.5));
    return {from, amount, position: stops[from] + (stops[from + 1] - stops[from]) * mapAmount};
  }
  function chapterAt(position, stops) {
    const value = Math.max(stops[0], Math.min(stops[stops.length - 1], position));
    const next = stops.findIndex(stop => stop > value);
    if (next === -1) return stops.length - 1;
    return next - 1 + (value - stops[next - 1]) / (stops[next] - stops[next - 1]);
  }
  const api = {timing, compile, player, scrollState, chapterAt};
  window.MapStoryAnimation = api;
})();
