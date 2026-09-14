/* Display-only grouping. Never replaces the publisher's eligibility status. */
const EligibilityDisplay = {
  zoningApplies: area => area.category !== 'town_growth_development',
  infrastructure: area => {
    const values = [area.drinking_water, area.sewer_wastewater, area.adequate_soils];
    return values.some(value => value === true) ? true
      : values.every(value => value === false) ? false : null;
  },
};
