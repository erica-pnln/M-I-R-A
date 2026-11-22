const liveSynonyms = [
  ["sports", "sport", "athletics", "game", "games", "match", "competition"],
  ["basketball", "nba", "hoops"],
  ["football", "soccer", "nfl", "fifa"],
  ["typhoon", "bagyo", "storm", "cyclone", "hurricane", "tropical"],
  ["weather", "forecast", "meteorology", "pagasa"],
  ["politics", "political", "election", "government", "senate", "parliament", "briefing", "policy"],
  ["disaster", "emergency", "calamity", "flood", "earthquake", "wildfire", "rescue"],
  ["olympics", "olympic"],
  ["traffic", "congestion", "commute", "road"],
];

const podcastSynonyms = [
  ["politics", "political", "election", "policy", "government"],
  ["technology", "tech", "digital", "innovation", "artificial", "intelligence", "ai"],
  ["sports", "sport", "athletics", "athlete", "game", "games"],
  ["education", "educational", "school", "university", "teaching", "learning", "campus"],
  ["environment", "environmental", "climate", "sustainability", "conservation", "ecology"],
  ["journalism", "journalist", "media", "reporting", "reporter", "newsroom"],
  ["investigation", "investigative", "investigations", "exposé", "expose"],
  ["economy", "economic", "finance", "financial", "inflation", "markets"],
];

const ignoredQueryWords = new Set(["a", "an", "and", "for", "from", "in", "of", "on", "the", "to", "with"]);

function normalizeText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function tokens(value) {
  const values = Array.isArray(value) ? value : [value];
  return values.flatMap((item) => {
    if (item && typeof item === "object") return tokens(item.name || item.label || "");
    return normalizeText(item).match(/[a-z0-9]+/g) || [];
  });
}

function getLiveCategories(channel) {
  if (Array.isArray(channel.categories)) return channel.categories;
  const publisher = normalizeText(channel.publisher);
  if (["abs-cbn", "gma news", "anc"].some((name) => publisher.includes(name))) {
    return ["National Broadcasters"];
  }
  if (["ptv", "radio television malacanang", "official gazette"].some((name) => publisher.includes(name))) {
    return ["Government & Official Channels"];
  }
  if (["bbc", "reuters", "al jazeera"].some((name) => publisher.includes(name))) {
    return ["International Broadcasters"];
  }
  return [];
}

function getPodcastCategories(episode) {
  if (Array.isArray(episode.categories)) return episode.categories;
  const publisher = normalizeText(`${episode.publisher || ""} ${episode.show || ""}`);
  const categories = [];
  if (/\bnpr\b/.test(publisher)) categories.push("News Organizations", "Radio Networks");
  if (/\b(bbc|global news podcast|reuters|thomson reuters|new york times|the daily)\b/.test(publisher)) {
    categories.push("News Organizations", "International Publishers");
  }
  if (/\b(abs-cbn|anc podcast|24 oras|gma news)\b/.test(publisher)) {
    categories.push("News Organizations");
  }
  return [...new Set(categories)];
}

function queryConcepts(query, synonymGroups) {
  const queryTokens = [...new Set(tokens(query).filter((token) => !ignoredQueryWords.has(token)))];
  const concepts = [];
  const seenGroups = new Set();
  for (const token of queryTokens) {
    const group = synonymGroups.find((synonyms) => synonyms.includes(token));
    if (!group) {
      concepts.push([token]);
      continue;
    }
    const key = group[0];
    if (!seenGroups.has(key)) {
      seenGroups.add(key);
      concepts.push(group);
    }
  }
  return concepts;
}

export function getMediaSearchScore(item, query, kind) {
  const synonymGroups = kind === "live" ? liveSynonyms : podcastSynonyms;
  const concepts = queryConcepts(query, synonymGroups);
  if (!concepts.length) return 1;

  const fields = kind === "live"
    ? [
      [8, item.title],
      [6, item.publisher],
      [5, item.show],
      [5, item.tags],
      [4, item.categories || getLiveCategories(item)],
      [3, item.description],
      [4, item.stream_description],
    ]
    : [
      [8, item.title],
      [6, item.publisher],
      [5, item.tags],
      [4, item.genres],
      [4, item.categories || getPodcastCategories(item)],
      [3, item.description],
      [5, item.transcript || item.transcriptText],
    ];
  const fieldTokens = fields.map(([weight, value]) => [weight, new Set(tokens(value))]);
  let matches = 0;
  let score = 0;

  for (const concept of concepts) {
    const aliases = new Set(concept.flatMap((alias) => tokens(alias)));
    let bestWeight = 0;
    for (const [weight, field] of fieldTokens) {
      if ([...aliases].some((alias) => field.has(alias))) bestWeight = Math.max(bestWeight, weight);
    }
    if (bestWeight) {
      matches += 1;
      score += bestWeight;
    }
  }

  return matches >= Math.ceil(concepts.length * 0.6) ? score + matches : 0;
}

export { getLiveCategories, getPodcastCategories };
