import hashlib
import difflib
import logging
import re
import threading
from collections import OrderedDict, defaultdict
from functools import lru_cache

from .db import sb

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'-]*", re.IGNORECASE)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "their", "this", "to", "was", "were", "will", "with",
}
_LOCALIZED_INTEREST_TERMS = {
    "fil": {
        "photojournalism": "larawan potograpiya",
        "sports journalism": "palakasan atleta laban",
        "mobile journalism": "mobile journalism balita",
        "media arts": "sining midya pelikula",
        "news writing": "balita ulat",
        "feature writing": "tampok kuwento",
        "editorial writing": "editoryal opinyon",
        "science and technology": "agham teknolohiya",
        "investigative journalism": "pagsisiyasat pananagutan",
        "campus journalism": "campus paaralan estudyante",
    },
    "ceb": {
        "photojournalism": "hulagway litrato",
        "sports journalism": "dula atleta duwa",
        "mobile journalism": "mobile journalism balita",
        "media arts": "sining midya pelikula",
        "news writing": "balita report",
        "feature writing": "talagsaong istorya",
        "editorial writing": "editoryal opinyon",
        "science and technology": "siyensiya teknolohiya",
        "investigative journalism": "imbestigasyon tulubagon",
        "campus journalism": "kampus eskwelahan estudyante",
    },
}
_embedding_cache: OrderedDict[tuple[str, str], object] = OrderedDict()
_indexed_hashes: OrderedDict[str, str] = OrderedDict()
_embedding_lock = threading.RLock()
_fast_search_lock = threading.Lock()
_fast_search_index: dict = {}


class IntelligenceUnavailable(RuntimeError):
    pass


def _tokens(text: str) -> list[str]:
    return [word.lower() for word in _WORD_RE.findall(text or "") if word.lower() not in _STOP_WORDS]


@lru_cache(maxsize=1)
def _nlp():
    try:
        import spacy
    except ImportError as exc:
        raise IntelligenceUnavailable("Install backend requirements to use spaCy NLP features.") from exc
    try:
        return spacy.load("en_core_web_sm")
    except OSError as exc:
        raise IntelligenceUnavailable(
            "The spaCy model is missing. Run `python -m spacy download en_core_web_sm` in backend."
        ) from exc


@lru_cache(maxsize=1)
def _embedding_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise IntelligenceUnavailable(
            "Install backend requirements to use semantic search."
        ) from exc
    try:
        return SentenceTransformer(EMBEDDING_MODEL)
    except Exception as exc:
        logger.exception("Could not load sentence embedding model %s", EMBEDDING_MODEL)
        raise IntelligenceUnavailable(
            f"Could not load {EMBEDDING_MODEL}; check model access and network connectivity."
        ) from exc


def preprocess_text(text: str) -> list[str]:
    """Normalize text with spaCy tokenization, stop-word filtering, and lemmatization."""
    doc = _nlp()(text or "")
    return _lemmas(doc)


def _lemmas(doc) -> list[str]:
    return [
        token.lemma_.lower().strip()
        for token in doc
        if token.is_alpha and not token.is_stop and len(token.lemma_.strip()) > 1
    ]


def _article_text(article: dict) -> str:
    return " ".join(
        str(article.get(key) or "")
        for key in ("title", "summary", "text")
    ).strip()


def fast_search(
    query: str, articles: list[dict], limit: int = 10
) -> tuple[list[dict], str | None]:
    """Search the in-memory news cache with BM25 and lightweight typo correction."""
    if not query.strip() or not articles:
        return articles[:limit], None

    try:
        from rank_bm25 import BM25Okapi
    except ImportError as exc:
        raise IntelligenceUnavailable(
            "Install backend requirements to use news search."
        ) from exc

    texts = [_article_text(article) for article in articles]
    cache_key = hashlib.sha1(
        "\n".join(f"{article.get('id', '')}\0{text}" for article, text in zip(articles, texts))
        .encode("utf-8")
    ).hexdigest()
    global _fast_search_index
    with _fast_search_lock:
        if _fast_search_index.get("key") != cache_key:
            tokenized = [_tokens(text) for text in texts]
            vocabulary = {token for row in tokenized for token in row}
            words_by_shape: dict[tuple[str, int], list[str]] = defaultdict(list)
            for word in vocabulary:
                words_by_shape[(word[0], len(word))].append(word)
            _fast_search_index = {
                "key": cache_key,
                "model": BM25Okapi(tokenized),
                "tokens": tokenized,
                "vocabulary": vocabulary,
                "words_by_shape": words_by_shape,
            }
        index = _fast_search_index

    query_tokens = _tokens(query)
    if not query_tokens:
        return [], None
    corrected_tokens = []
    vocabulary = index["vocabulary"]
    for token in query_tokens:
        if token in vocabulary or len(token) < 5:
            corrected_tokens.append(token)
            continue
        words_by_shape = index["words_by_shape"]
        nearby_words = [
            word
            for length in range(max(1, len(token) - 2), len(token) + 3)
            for word in words_by_shape.get((token[0], length), [])
        ]
        closest = difflib.get_close_matches(
            token, nearby_words or vocabulary, n=1, cutoff=0.76
        )
        corrected_tokens.append(closest[0] if closest else token)
    corrected_query = " ".join(corrected_tokens)
    if not any(token in vocabulary for token in corrected_tokens):
        return [], None

    exact_scores = index["model"].get_scores(query_tokens)
    if corrected_tokens != query_tokens:
        corrected_scores = index["model"].get_scores(corrected_tokens)
        scores = [
            max(float(exact), float(corrected) * 0.95)
            for exact, corrected in zip(exact_scores, corrected_scores)
        ]
    else:
        scores = [float(score) for score in exact_scores]

    ranked = sorted(
        range(len(articles)),
        key=lambda position: (
            scores[position],
            sum(
                token in (articles[position].get("title", "")).lower()
                for token in corrected_tokens
            ),
            articles[position].get("published") or "",
        ),
        reverse=True,
    )
    return [articles[position] for position in ranked[:limit]], (
        corrected_query if corrected_tokens != query_tokens else None
    )


def extract_entities(text: str) -> dict[str, list[str]]:
    return _entities(_nlp()(text or ""))


def _entities(doc) -> dict[str, list[str]]:
    entities: dict[str, set[str]] = {
        "people": set(),
        "organizations": set(),
        "locations": set(),
        "dates": set(),
        "events": set(),
        "other": set(),
    }
    labels = {
        "PERSON": "people",
        "ORG": "organizations",
        "GPE": "locations",
        "LOC": "locations",
        "FAC": "locations",
        "DATE": "dates",
        "TIME": "dates",
        "EVENT": "events",
    }
    for entity in doc.ents:
        value = entity.text.strip()
        if value:
            entities[labels.get(entity.label_, "other")].add(value)
    return {key: sorted(values) for key, values in entities.items()}


def analyze_nlp(text: str) -> dict:
    return _analyze_nlp_cached(text or "")


@lru_cache(maxsize=128)
def _analyze_nlp_cached(text: str) -> dict:
    doc = _nlp()(text or "")
    return {"entities": _entities(doc), "lemmas": _lemmas(doc)}


def sentiment(text: str) -> dict:
    return _sentiment_cached(text or "")


@lru_cache(maxsize=512)
def _sentiment_cached(text: str) -> dict:
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError as exc:
        raise IntelligenceUnavailable(
            "Install backend requirements to use sentiment analysis."
        ) from exc
    analyzer = _sentiment_analyzer()
    scores = analyzer.polarity_scores(text or "")
    compound = scores["compound"]
    label = "positive" if compound >= 0.05 else "negative" if compound <= -0.05 else "neutral"
    return {"label": label, "scores": scores}


@lru_cache(maxsize=1)
def _sentiment_analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    return SentimentIntensityAnalyzer()


def tfidf_keywords(articles: list[dict], top_k: int = 8) -> dict[str, list[dict]]:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError as exc:
        raise IntelligenceUnavailable("Install backend requirements to use TF-IDF features.") from exc
    documents = [_article_text(article) for article in articles]
    if not documents:
        return {}
    vectorizer = TfidfVectorizer(
        max_features=5000, ngram_range=(1, 2), stop_words="english", sublinear_tf=True
    )
    try:
        matrix = vectorizer.fit_transform(documents)
    except ValueError:
        return {str(a.get("id", i)): [] for i, a in enumerate(articles)}
    terms = vectorizer.get_feature_names_out()
    results = {}
    for i, article in enumerate(articles):
        row = matrix.getrow(i)
        ranked = sorted(zip(row.indices, row.data), key=lambda item: item[1], reverse=True)[:top_k]
        results[str(article.get("id", i))] = [
            {"term": str(terms[index]), "score": round(float(score), 5)}
            for index, score in ranked
        ]
    return results


def _encode(texts: list[str]):
    model = _embedding_model()
    try:
        vectors = model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
    except Exception as exc:
        logger.exception("Sentence embedding failed")
        raise IntelligenceUnavailable("Could not generate sentence embeddings.") from exc
    if vectors.shape[-1] != EMBEDDING_DIMENSIONS:
        raise IntelligenceUnavailable(
            f"Embedding model returned {vectors.shape[-1]} dimensions; "
            f"expected {EMBEDDING_DIMENSIONS} for the pgvector index."
        )
    return vectors


@lru_cache(maxsize=512)
def _encode_query(text: str):
    return _encode([text])[0]


def _encode_articles(articles: list[dict]):
    hashes = [
        hashlib.sha256(_article_text(article).encode("utf-8")).hexdigest()
        for article in articles
    ]
    keys = [(str(article["id"]), content_hash) for article, content_hash in zip(articles, hashes)]
    with _embedding_lock:
        for key in keys:
            if key in _embedding_cache:
                _embedding_cache.move_to_end(key)
        missing_indices = [i for i, key in enumerate(keys) if key not in _embedding_cache]
        if missing_indices:
            vectors = _encode([_article_text(articles[i]) for i in missing_indices])
            for index, vector in zip(missing_indices, vectors):
                _embedding_cache[keys[index]] = vector
                _embedding_cache.move_to_end(keys[index])
                while len(_embedding_cache) > 2000:
                    _embedding_cache.popitem(last=False)
        import numpy as np

        matrix = np.asarray([_embedding_cache[key] for key in keys])
    return matrix, hashes


def _vector_string(vector) -> str:
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def _index_embeddings(articles: list[dict], vectors) -> None:
    if sb is None or not articles:
        return
    with _embedding_lock:
        unchecked = [
            (article, vector, hashlib.sha256(_article_text(article).encode("utf-8")).hexdigest())
            for article, vector in zip(articles, vectors)
            if _indexed_hashes.get(str(article["id"]))
            != hashlib.sha256(_article_text(article).encode("utf-8")).hexdigest()
        ]
    if not unchecked:
        return
    ids = [str(article["id"]) for article, _, _ in unchecked]
    existing: dict[str, str] = {}
    for offset in range(0, len(ids), 100):
        response = sb.table("article_embeddings").select("article_id,content_hash,model").in_(
            "article_id", ids[offset:offset + 100]
        ).execute()
        existing.update({row["article_id"]: row["content_hash"] for row in response.data
                         if row.get("model") == EMBEDDING_MODEL})
    rows = []
    for article, vector, content_hash in unchecked:
        if existing.get(str(article["id"])) == content_hash:
            continue
        rows.append({
            "article_id": str(article["id"]),
            "content_hash": content_hash,
            "model": EMBEDDING_MODEL,
            "embedding": _vector_string(vector),
        })
    for offset in range(0, len(rows), 100):
        sb.table("article_embeddings").upsert(
            rows[offset:offset + 100], on_conflict="article_id"
        ).execute()
    with _embedding_lock:
        _indexed_hashes.update({str(article["id"]): content_hash
                                for article, _, content_hash in unchecked})
        while len(_indexed_hashes) > 2000:
            _indexed_hashes.popitem(last=False)


def hybrid_search(query: str, articles: list[dict], limit: int = 10) -> tuple[list[dict], str]:
    """Combine BM25 keyword retrieval and sentence-transformer cosine similarity."""
    if not query.strip() or not articles:
        return articles[:limit], "empty"
    try:
        from rank_bm25 import BM25Okapi
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as exc:
        raise IntelligenceUnavailable("Install backend requirements to use hybrid search.") from exc

    texts = [_article_text(article) for article in articles]
    tokenized = [_tokens(text) for text in texts]
    query_tokens = _tokens(query)
    all_bm25_scores = BM25Okapi(tokenized).get_scores(query_tokens)
    candidate_count = min(len(articles), max(100, limit * 10))
    candidate_indices = sorted(
        range(len(articles)),
        key=lambda index: (
            all_bm25_scores[index],
            articles[index].get("published") or "",
        ),
        reverse=True,
    )[:candidate_count]
    candidates = [articles[index] for index in candidate_indices]
    bm25_scores = all_bm25_scores[candidate_indices]
    query_vector = _encode_query(query)
    import numpy as np

    article_vectors, _ = _encode_articles(candidates)
    semantic_scores = cosine_similarity([query_vector], article_vectors)[0]
    if sb is not None:
        try:
            _index_embeddings(candidates, article_vectors)
        except Exception as exc:
            logger.exception("Could not index embeddings in Supabase")
            raise IntelligenceUnavailable(
                "Could not index embeddings. Apply the current supabase/schema.sql migration."
            ) from exc

    if sb is not None:
        try:
            candidate_limit = min(len(articles), max(limit * 5, 50))
            response = sb.rpc("hybrid_search_articles", {
                "query_embedding": _vector_string(query_vector),
                "match_count": candidate_limit,
                "embedding_model": EMBEDDING_MODEL,
            }).execute()
            by_id = {str(article["id"]): article for article in candidates}
            vector_candidates = [
                by_id[str(row["id"])] for row in response.data
                if str(row["id"]) in by_id
            ]
            if vector_candidates:
                candidates = vector_candidates

            def normalized(scores):
                scores = np.asarray(scores, dtype=float)
                maximum = float(scores.max()) if scores.size else 0
                return scores / maximum if maximum > 0 else scores

            article_indexes = {str(article["id"]): index for index, article in enumerate(
                [articles[index] for index in candidate_indices]
            )}
            bm25_normalized = normalized(bm25_scores)
            semantic_normalized = normalized(semantic_scores)
            ranked = sorted(
                candidates,
                key=lambda article: (
                    0.45 * bm25_normalized[article_indexes[str(article["id"])]]
                    + 0.55 * semantic_normalized[article_indexes[str(article["id"])]],
                    article.get("published") or "",
                ),
                reverse=True,
            )
            return ranked[:limit], "pgvector+bm25"
        except Exception as exc:
            logger.exception("Supabase pgvector hybrid search failed")
            if isinstance(exc, IntelligenceUnavailable):
                raise
            raise IntelligenceUnavailable(
                "Supabase hybrid search failed. Apply the current supabase/schema.sql migration."
            ) from exc

    def normalized(scores):
        scores = np.asarray(scores, dtype=float)
        maximum = float(scores.max()) if scores.size else 0
        return scores / maximum if maximum > 0 else scores

    combined = 0.45 * normalized(bm25_scores) + 0.55 * normalized(semantic_scores)
    ranked = sorted(enumerate(candidates), key=lambda pair: (combined[pair[0]], pair[1].get("published") or ""), reverse=True)
    return [article for _, article in ranked[:limit]], "bm25+sentence-transformers"


def discover_topics(articles: list[dict], topic_count: int = 6) -> dict:
    """Fit corpus-level LDA topics and K-means groups from TF-IDF text features."""
    if len(articles) < 2:
        return {"topics": [], "clusters": []}
    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.decomposition import LatentDirichletAllocation
        from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
        from sklearn.metrics import silhouette_score
    except ImportError as exc:
        raise IntelligenceUnavailable("Install backend requirements to discover topics.") from exc

    documents = [_article_text(article) for article in articles]
    topic_count = max(1, min(topic_count, len(articles), 10))
    count_vectorizer = CountVectorizer(max_features=3000, stop_words="english")
    tfidf_vectorizer = TfidfVectorizer(max_features=3000, stop_words="english")
    try:
        counts = count_vectorizer.fit_transform(documents)
        tfidf = tfidf_vectorizer.fit_transform(documents)
    except ValueError:
        return {"topics": [], "clusters": []}

    lda = LatentDirichletAllocation(
        n_components=topic_count, max_iter=10, random_state=17, learning_method="batch"
    )
    topic_distribution = lda.fit_transform(counts)
    terms = count_vectorizer.get_feature_names_out()
    topics = []
    for topic_id, weights in enumerate(lda.components_):
        indices = weights.argsort()[-8:][::-1]
        article_indices = np.where(topic_distribution.argmax(axis=1) == topic_id)[0]
        topics.append({
            "id": topic_id,
            "keywords": [str(terms[index]) for index in indices],
            "article_ids": [str(articles[index]["id"]) for index in article_indices],
        })

    cluster_count = max(2, min(int(len(articles) ** 0.5), 10, len(articles)))
    labels = KMeans(n_clusters=cluster_count, random_state=17, n_init=10).fit_predict(tfidf)
    unique_labels = np.unique(labels)
    silhouette = (
        round(float(silhouette_score(tfidf, labels)), 4)
        if 1 < len(unique_labels) < len(articles)
        else None
    )
    clusters = [
        {"id": cluster_id, "article_ids": [
            str(articles[index]["id"]) for index, label in enumerate(labels) if label == cluster_id
        ]}
        for cluster_id in range(cluster_count)
    ]
    return {
        "topics": topics,
        "clusters": clusters,
        "evaluation": {
            "lda_perplexity": round(float(lda.perplexity(counts)), 4),
            "kmeans_silhouette": silhouette,
        },
    }


def train_category_classifiers(articles: list[dict]) -> dict:
    """Train/evaluate SVM, Random Forest, and Logistic Regression on RSS category labels."""
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import make_pipeline
        from sklearn.svm import LinearSVC
    except ImportError as exc:
        raise IntelligenceUnavailable("Install backend requirements to train classifiers.") from exc

    labeled = [
        (article, str(article.get("category") or "").strip())
        for article in articles
        if article.get("category") and str(article.get("category")).strip()
    ]
    label_counts: dict[str, int] = defaultdict(int)
    for _, label in labeled:
        label_counts[label] += 1
    if len(label_counts) < 2 or min(label_counts.values(), default=0) < 5:
        return {
            "status": "insufficient_labeled_data",
            "labeled_articles": len(labeled),
            "category_counts": dict(label_counts),
            "minimum_per_category": 5,
            "models": {},
        }

    texts = [_article_text(article) for article, _ in labeled]
    labels = [label for _, label in labeled]
    train_indices, test_indices = train_test_split(
        list(range(len(labels))), test_size=0.2, random_state=17, stratify=labels
    )
    factories = {
        "svm": lambda: LinearSVC(),
        "random_forest": lambda: RandomForestClassifier(
            n_estimators=200, random_state=17, class_weight="balanced", n_jobs=1
        ),
        "logistic_regression": lambda: LogisticRegression(
            max_iter=1000, class_weight="balanced", random_state=17
        ),
    }
    models = {}
    for name, factory in factories.items():
        model = make_pipeline(
            TfidfVectorizer(max_features=10000, ngram_range=(1, 2), stop_words="english"),
            factory(),
        )
        model.fit([texts[i] for i in train_indices], [labels[i] for i in train_indices])
        predicted = model.predict([texts[i] for i in test_indices])
        models[name] = {
            "accuracy": round(float(accuracy_score([labels[i] for i in test_indices], predicted)), 4),
            "macro_f1": round(float(f1_score(
                [labels[i] for i in test_indices], predicted, average="macro", zero_division=0
            )), 4),
        }
    return {"status": "evaluated", "labeled_articles": len(labeled), "models": models}


def classify_articles(articles: list[dict]) -> dict:
    """Return held-out metrics and predictions only when category labels support training."""
    evaluation = train_category_classifiers(articles)
    if evaluation["status"] != "evaluated":
        return evaluation
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.svm import LinearSVC
    except ImportError as exc:
        raise IntelligenceUnavailable("Install backend requirements to train classifiers.") from exc
    labels = [
        str(article["category"]).strip() for article in articles if article.get("category")
    ]
    texts = [_article_text(article) for article in articles if article.get("category")]
    factories = {
        "svm": LinearSVC(),
        "random_forest": RandomForestClassifier(n_estimators=200, random_state=17, n_jobs=1),
        "logistic_regression": LogisticRegression(max_iter=1000, random_state=17),
    }
    predictions = {}
    for name, estimator in factories.items():
        model = make_pipeline(
            TfidfVectorizer(max_features=10000, ngram_range=(1, 2), stop_words="english"),
            estimator,
        )
        model.fit(texts, labels)
        predictions[name] = {
            str(article["id"]): str(model.predict([_article_text(article)])[0])
            for article in articles
        }
    return {**evaluation, "predictions": predictions}


def content_recommendations(
    articles: list[dict],
    interests: list[str],
    limit: int = 40,
    history: list[dict] | None = None,
    favorites: list[dict] | None = None,
    language: str = "en",
) -> list[dict]:
    if not articles:
        return articles[:limit]
    history = history or []
    favorites = favorites or []
    localized_terms = _LOCALIZED_INTEREST_TERMS.get(language, {})
    preference_text = " ".join(
        [*interests, *(localized_terms.get(item.removeprefix("Campus ").casefold(), "")
                       for item in interests)]
    )
    history_texts = [_article_text(item) for item in history if _article_text(item)]
    favorite_texts = [_article_text(item) for item in favorites if _article_text(item)]
    if not preference_text and not history_texts and not favorite_texts:
        return articles[:limit]
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as exc:
        raise IntelligenceUnavailable(
            "Install backend requirements to use content-based recommendations."
        ) from exc

    documents = [_article_text(article) for article in articles]
    vectorizer = TfidfVectorizer(
        max_features=5000, ngram_range=(1, 2), stop_words="english", sublinear_tf=True
    )
    seeds = [text for text in [preference_text, *history_texts, *favorite_texts] if text]
    try:
        matrix = vectorizer.fit_transform([*documents, *seeds])
    except ValueError:
        return articles[:limit]
    article_matrix = matrix[:len(documents)]
    interest_count = int(bool(preference_text))
    history_end = len(documents) + interest_count + len(history_texts)
    interest_score = (
        cosine_similarity(matrix[len(documents)], article_matrix).ravel()
        if interest_count else None
    )
    history_start = len(documents) + interest_count
    history_scores = (
        cosine_similarity(matrix[history_start:history_end], article_matrix).mean(axis=0).ravel()
        if history_texts else None
    )
    favorite_scores = (
        cosine_similarity(matrix[history_end:], article_matrix).mean(axis=0).ravel()
        if favorite_texts else None
    )
    scores = (
        (0.50 * interest_score if interest_score is not None else 0)
        + (0.30 * history_scores if history_scores is not None else 0)
        + (0.20 * favorite_scores if favorite_scores is not None else 0)
    )
    ranked = sorted(
        enumerate(articles),
        key=lambda pair: (float(scores[pair[0]]), pair[1].get("published") or ""),
        reverse=True,
    )
    return [article for _, article in ranked[:limit]]


def knowledge_graph(articles: list[dict]) -> dict:
    """Build an evidence graph from entities co-mentioned in each article."""
    nodes: dict[str, dict] = {}
    edge_evidence: dict[tuple[str, str], list[dict]] = defaultdict(list)
    mention_edges = []
    for article in articles:
        entities = extract_entities(_article_text(article))
        article_node_id = f"article:{article['id']}"
        nodes[article_node_id] = {
            "id": article_node_id,
            "label": article.get("title", ""),
            "type": "news_report",
            "source": article.get("source", ""),
            "url": article.get("url", ""),
        }
        article_entities = []
        for kind in ("people", "organizations", "locations", "dates", "events"):
            for name in entities[kind]:
                key = name.casefold()
                node = nodes.setdefault(key, {"id": key, "label": name, "type": kind, "articles": []})
                node["articles"].append(str(article["id"]))
                article_entities.append(key)
        article_entities = sorted(set(article_entities))
        evidence = {
            "article_id": str(article["id"]),
            "title": article.get("title", ""),
            "source": article.get("source", ""),
            "url": article.get("url", ""),
        }
        mention_edges.extend({
            "source": entity,
            "target": article_node_id,
            "relationship": "mentioned-in",
            "evidence": [evidence],
        } for entity in article_entities)
        for index, left in enumerate(article_entities):
            for right in article_entities[index + 1:]:
                edge_evidence[(left, right)].append(evidence)
    edges = [
        {
            "source": left,
            "target": right,
            "relationship": "co-mentioned",
            "evidence": evidence,
        }
        for (left, right), evidence in edge_evidence.items()
    ]
    return {"nodes": list(nodes.values()), "edges": edges + mention_edges}
