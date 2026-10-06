/* Desktop pinches use the transform path of the vendored Leaflet touch handler.
 * Only settling the gesture projects and redraws the saved polygon geometry. */
(() => {
  'use strict';
  function trackpadZoom(map, {
    requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame,
    setTimer = setTimeout, clearTimer = clearTimeout,
    touchPoints = navigator.maxTouchPoints,
  } = {}) {
    const container = map.getContainer();
    let pinch = null, frame = null, timer = null, safari = false;
    const limit = zoom => Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), zoom));
    function centerAt(zoom) {
      const offset = map.mouseEventToContainerPoint(pinch.event).subtract(map.getSize().divideBy(2));
      return map.unproject(map.project(pinch.anchor, zoom).subtract(offset), zoom);
    }
    function draw() {
      frame = null;
      if (pinch) map._move(centerAt(pinch.zoom), pinch.zoom, {pinch: true, round: false});
    }
    function begin(event) {
      if (pinch) return;
      if (map._animatingZoom) map._onZoomTransitionEnd();
      map.stop();
      pinch = {start: map.getZoom(), zoom: map.getZoom(), event,
        anchor: map.containerPointToLatLng(map.mouseEventToContainerPoint(event))};
      map._moveStart(true, false);
    }
    function queue(event, zoom) {
      pinch.event = event;
      pinch.zoom = limit(zoom);
      if (frame === null) frame = requestFrame(draw);
    }
    function finish() {
      clearTimer(timer);
      timer = null;
      safari = false;
      if (!pinch) return;
      if (frame !== null) cancelFrame(frame);
      frame = null;
      const zoom = map._limitZoom(pinch.zoom), center = centerAt(zoom);
      pinch = null;
      // Snap once at release, retaining the geographic point under the cursor.
      map._resetView(center, zoom);
    }
    function wheel(event) {
      if (!event.ctrlKey) { finish(); return; }
      event.preventDefault();
      if (safari) return;
      begin(event);
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? map.getSize().y : 1);
      queue(event, pinch.zoom - delta / 60);
      clearTimer(timer);
      timer = setTimer(finish, 250);
    }
    function gestureStart(event) {
      event.preventDefault();
      finish();
      begin(event);
      safari = true;
    }
    function gestureChange(event) {
      if (!safari || !pinch) return;
      event.preventDefault();
      if (event.scale > 0) queue(event, pinch.start + Math.log2(event.scale));
    }
    function gestureEnd(event) { event.preventDefault(); finish(); }
    const listeners = [[container, 'wheel', wheel, {passive: false}],
      [document, 'pointerdown', finish, {capture: true, passive: true}],
      [window, 'blur', finish]];
    if (!touchPoints) listeners.push([container, 'gesturestart', gestureStart],
      [container, 'gesturechange', gestureChange], [container, 'gestureend', gestureEnd]);
    listeners.forEach(([target, event, handler, options]) => target.addEventListener(event, handler, options));
    return {isActive: () => pinch !== null, finish, destroy() {
      finish();
      listeners.forEach(([target, event, handler, options]) => target.removeEventListener(event, handler, options));
    }};
  }
  function pointerHover(map, followPointer, clearHover) {
    const container = map.getContainer();
    // Leaflet emits click only for a tap, after rejecting drags. Touch pointerleave
    // also fires on finger release, so it must not dismiss the resulting card.
    const click = event => followPointer(event.originalEvent);
    const listeners = [
      [container, 'pointermove', event => event.pointerType === 'touch' ? clearHover() : followPointer(event)],
      [container, 'pointerdown', clearHover],
      [container, 'pointerleave', event => { if (event.pointerType !== 'touch') clearHover(); }],
      [window, 'blur', clearHover],
    ];
    map.on('click', click);
    listeners.forEach(([target, event, handler]) => target.addEventListener(event, handler));
    return {destroy() {
      map.off('click', click);
      listeners.forEach(([target, event, handler]) => target.removeEventListener(event, handler));
    }};
  }
  window.MapInteractions = {trackpadZoom, pointerHover};
})();
