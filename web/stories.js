// Publication setting: only this enabled story is mounted. No URL override.
window.MapStories = (() => {
  const active = 'saved-map-overview';
  const stories = new Map();
  return {
    register(story) {
      if (!story.id || stories.has(story.id)) throw new Error('Duplicate or missing story ID');
      stories.set(story.id, story);
    },
    create(context, id = active) {
      const story = stories.get(id);
      if (!story?.enabled) throw new Error(`Story is unavailable: ${id}`);
      const result = story.create(context);
      if (result.steps.length < 2 || result.groups.length !== result.steps.length - 1 ||
          result.groups.some(group => !group.length)) {
        throw new Error(`Story needs at least two chapters and a nonempty transition between each: ${id}`);
      }
      return result;
    },
  };
})();
