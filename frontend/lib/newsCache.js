const DATABASE_NAME = "mira-news";
const DATABASE_VERSION = 2;
const STORE_NAME = "entries";
const IMAGE_STORE_NAME = "article-images";
const MAX_CACHED_ARTICLE_IMAGES = 40;
const MAX_CACHED_ARTICLE_IMAGE_BYTES = 3 * 1024 * 1024;
const DEFAULT_REFRESH_INTERVALS_SECONDS = {
  trending: 300,
  national: 600,
  regional: 900,
  local: 900,
  international: 1200,
  business: 900,
  sports: 600,
  agriculture: 1800,
  education: 1800,
};

let databasePromise;
let refreshIntervals;

function getRefreshIntervals() {
  if (refreshIntervals) return refreshIntervals;
  refreshIntervals = { ...DEFAULT_REFRESH_INTERVALS_SECONDS };
  const raw = process.env.NEXT_PUBLIC_NEWS_REFRESH_INTERVALS_SECONDS;
  if (raw) {
    try {
      const overrides = JSON.parse(raw);
      if (!overrides || typeof overrides !== "object" || Array.isArray(overrides)) {
        throw new Error("Expected a JSON object.");
      }
      for (const [category, value] of Object.entries(overrides)) {
        if (!(category in refreshIntervals) || !Number.isFinite(Number(value)) || Number(value) <= 0) {
          throw new Error(`Invalid news refresh interval for "${category}".`);
        }
        refreshIntervals[category] = Number(value);
      }
    } catch (error) {
      console.error("Invalid NEXT_PUBLIC_NEWS_REFRESH_INTERVALS_SECONDS:", error);
    }
  }
  return refreshIntervals;
}

export function newsRefreshIntervalMs(category) {
  const key = String(category || "trending").toLowerCase();
  const intervals = getRefreshIntervals();
  return (intervals[key] || intervals.trending) * 1000;
}

export function isNewsCacheFresh(entry, category) {
  return Boolean(entry?.savedAt && Date.now() - entry.savedAt < newsRefreshIntervalMs(category));
}

export function newsCacheFreshInMs(entry, category) {
  if (!entry?.savedAt) return 0;
  return Math.max(0, newsRefreshIntervalMs(category) - (Date.now() - entry.savedAt));
}

function openDatabase() {
  if (typeof indexedDB === "undefined") {
    return Promise.reject(new Error("IndexedDB is unavailable in this browser."));
  }
  if (databasePromise) return databasePromise;

  databasePromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: "key" });
      }
      if (!database.objectStoreNames.contains(IMAGE_STORE_NAME)) {
        const imageStore = database.createObjectStore(IMAGE_STORE_NAME, { keyPath: "articleId" });
        imageStore.createIndex("savedAt", "savedAt");
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      databasePromise = null;
      reject(request.error || new Error("Could not open the local news cache."));
    };
    request.onblocked = () => {
      databasePromise = null;
      reject(new Error("The local news cache is blocked by another browser tab."));
    };
  });
  return databasePromise;
}

export async function getCachedNews(key) {
  const entry = await getCachedNewsEntry(key);
  return entry?.value ?? null;
}

export async function getCachedNewsEntry(key) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const request = database.transaction(STORE_NAME, "readonly")
      .objectStore(STORE_NAME)
      .get(key);
    request.onsuccess = () => resolve(request.result ?? null);
    request.onerror = () => reject(request.error || new Error("Could not read the local news cache."));
  });
}

export async function putCachedNews(key, value) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).put({ key, value, savedAt: Date.now() });
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error || new Error("Could not update the local news cache."));
    transaction.onabort = () => reject(transaction.error || new Error("The local news cache update was aborted."));
  });
}

export async function getCachedArticleImage(articleId) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const request = database.transaction(IMAGE_STORE_NAME, "readonly")
      .objectStore(IMAGE_STORE_NAME)
      .get(articleId);
    request.onsuccess = () => resolve(request.result?.blob ?? null);
    request.onerror = () => reject(request.error || new Error("Could not read the local article image cache."));
  });
}

export async function putCachedArticleImage(articleId, blob) {
  if (!(blob instanceof Blob)) throw new TypeError("An article image cache entry must be a Blob.");
  if (blob.size > MAX_CACHED_ARTICLE_IMAGE_BYTES) return false;

  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(IMAGE_STORE_NAME, "readwrite");
    const store = transaction.objectStore(IMAGE_STORE_NAME);
    store.put({ articleId, blob, savedAt: Date.now() });
    const countRequest = store.count();
    countRequest.onsuccess = () => {
      let excess = countRequest.result - MAX_CACHED_ARTICLE_IMAGES;
      if (excess <= 0) return;
      const cursorRequest = store.index("savedAt").openCursor();
      cursorRequest.onsuccess = () => {
        const cursor = cursorRequest.result;
        if (!cursor || excess <= 0) return;
        if (cursor.value.articleId !== articleId) {
          cursor.delete();
          excess -= 1;
        }
        if (excess > 0) cursor.continue();
      };
    };
    transaction.oncomplete = () => resolve(true);
    transaction.onerror = () => reject(transaction.error || new Error("Could not update the local article image cache."));
    transaction.onabort = () => reject(transaction.error || new Error("The local article image cache update was aborted."));
  });
}
