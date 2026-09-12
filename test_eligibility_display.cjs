const {test} = require('node:test');
const assert = require('node:assert/strict');
const display = require('./web/eligibility-display.js');

test('infrastructure uses three-valued OR without changing publisher status', () => {
  for (const a of [true, false, null]) for (const b of [true, false, null]) for (const c of [true, false, null]) {
    const area = {drinking_water:a, sewer_wastewater:b, adequate_soils:c, likely_eligible:false};
    const expected = [a,b,c].includes(true) ? true : [a,b,c].includes(null) ? null : false;
    assert.equal(display.infrastructure(area), expected);
    assert.equal(area.likely_eligible, false);
  }
});
test('only the development category omits separate zoning', () => {
  assert.equal(display.zoningApplies({category:'town_growth_development'}), false);
  for (const category of ['downtown_district','village_center_buffer',undefined]) {
    assert.equal(display.zoningApplies({category}), true);
  }
});
