# MIRA — Media Intelligence & Research Assistant
*Go Beyond the Headline.*

Prototype codebase for the MIRA system: a Philippine-focused, globally aware news discovery and journalism research platform.

| Layer | Tech | Folder |
|---|---|---|
| Frontend (PWA) | Next.js 14 + React + Tailwind CSS | `frontend/` |
| Backend | Python + FastAPI | `backend/` |
| Database + Auth | Supabase (PostgreSQL) | `supabase/schema.sql` |
| AI engine | Multi-provider orchestration (Gemini, xAI, Hugging Face) | `backend/app/ai.py`, `backend/app/providers.py` |
| Design reference | Static HTML prototype | `design-prototype/` |

## 1. Supabase
Supabase is already configured for this project. In its SQL Editor, run `supabase/schema.sql` to add or update the tables, policies, user language preferences, search history, AI provider usage records, and pgvector search function. For an existing deployment, also run `supabase/migrations/20261111_chat_projects.sql`, `supabase/migrations/20261112_journalism_onboarding.sql`, `supabase/migrations/20261112_regional_articles.sql`, `supabase/migrations/20261117_ai_usage.sql`, `supabase/migrations/20261121_ai_language.sql`, `supabase/migrations/20261121_system_language.sql`, and `supabase/migrations/20261122_news_author.sql`. Keep the service-role key exclusively in the backend environment.

## 2. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
# Configure backend/.env with Supabase and one or more AI provider credentials.
# CORS_ORIGINS is optional for local development; it defaults to both localhost origins.
# GEMINI_API_KEY, XAI_API_KEY, and HF_TOKEN are optional; configure at least one.
# HF_TOKEN needs Hugging Face Inference Providers permission. HF_MODEL defaults to
# CohereLabs/tiny-aya-global; configure HF_MODEL to select another available model.
# Optional: GEMINI_ANALYSIS_API_KEY and GEMINI_ANALYSIS_MODEL select a separate
# Gemini credential/model for story analysis and summaries.
# Optional model selection: GEMINI_MODEL, XAI_MODEL, XAI_VISION_MODEL,
# HF_MODEL, HF_VISION_MODEL. Provider priority defaults to gemini,xai,huggingface.
# The default Gemini model is gemini-3.5-flash-lite; gemini-2.5-flash is mapped to it.
# AI_REQUEST_TIMEOUT_SECONDS defaults to 30 seconds; AI_MAX_RETRIES_PER_MODEL
# defaults to 0 so a transient failure quickly moves to the next provider.
# AI_PROVIDER_COOLDOWN_SECONDS, AI_RESPONSE_CACHE_TTL_SECONDS, and
# AI_MAX_COST_PER_1K_TOKENS tune reliability and cost selection.
uvicorn app.main:app --reload --port 8000
```
API docs: http://localhost:8000/docs

The Sentence Transformers model (`sentence-transformers/all-MiniLM-L6-v2`) downloads from Hugging Face when semantic search is first used. The backend caches article embeddings and stores them in Supabase; it only re-embeds changed article text. NLP analysis uses spaCy's English model and VADER sentiment.

All provider requests are routed through the FastAPI backend. Keep AI credentials only in `backend/.env`; never add them to frontend environment variables. Gemini remains supported, and xAI/Hugging Face use their OpenAI-compatible chat-completions APIs. Image-capable models are explicitly marked in the registry, so image payloads are never sent to text-only models.

The optional `AI_MODELS_JSON` environment variable can register additional OpenAI-compatible providers without code changes. Each entry names an existing environment variable for its key:

```json
[
  {
    "provider": "my_provider",
    "model": "provider/model-name",
    "api_key_env": "MY_PROVIDER_API_KEY",
    "base_url": "https://api.example.com/v1",
    "tasks": ["general_chat", "research", "news_summarization"],
    "vision": false,
    "priority": 2
  }
]
```

Set `"vision": true` only for models whose configured endpoint accepts image inputs, and optionally set `"image_types"` to the supported MIME types. Task names include `general_chat`, `story_chat`, `image_analysis`, `article_analysis`, `news_summarization`, `article_generation`, `fact_checking`, and `research`; `"*"` enables all tasks. `AI_PROVIDER_PRIORITY` orders providers. Optional `cost_per_1k_tokens` model metadata ranks models within a provider; setting `AI_MAX_COST_PER_1K_TOKENS` excludes models with unknown or higher configured costs. Keep this metadata aligned with the provider's current prices. Transient server/network failures move to the next compatible provider without retrying the same model by default. To enable bounded retries with exponential delay, set `AI_MAX_RETRIES_PER_MODEL` to 1–3. Gemini tries one alternate model after a transient failure when no other provider is available; with another provider configured it switches away from Gemini immediately. Rate limits use model cooldowns, while quota exhaustion cools down that provider's models. Authentication failures stop fallback. Invalid-request failures try the next compatible model/provider before any response has been streamed; after streaming starts, the partial response is preserved and the failure is reported rather than mixing provider output. Article analysis and summaries are cached briefly in backend memory; prompts, images, and credentials are not written to usage records.

Algorithm endpoints are available in the FastAPI docs: `GET /api/search?q=...` (query-time public news RSS discovery plus BM25 ranking over live and archived articles; accepts `scope`, `period`, `topic`, `from_date`, `to_date`, and `sort` filters), `GET /api/intelligence/{article_id}` (entities, sentiment, keywords, lemmas), `GET /api/topics` (LDA and K-means), `GET /api/classification` (supervised model metrics and predictions), and `GET /api/knowledge-graph/{article_id}`. `POST /api/summarize/{article_id}`, chat, and article analysis use retrieved news context with source IDs and URLs.

## 3. Frontend
```bash
cd frontend
npm install
# Configure the existing .env.local with your public Supabase and backend API values.
npm run dev
```
Open http://localhost:3000

`NEXT_PUBLIC_API_URL` must be a URL the browser can reach (by default, `http://127.0.0.1:8000`). If the backend runs in Docker, WSL, or on another machine, use its host-reachable URL and include the frontend origin in backend `CORS_ORIGINS`.

## Features included
- Full-width, responsive dashboard with trending coverage, personalized recommendations, latest news, search, and paginated loading
- Shared Philippine broadcaster metadata connects multilingual News filters, searchable Live radio-station listings, and verified podcast episodes across the three sections
- Guided account onboarding for up to three journalism fields and preferred news topics; both can be updated in Settings
- A shared English, Filipino, and Bisaya interface translation system, with separate saved system-language and AI-response-language preferences
- Settings for news interests and up to three journalism fields, plus reading, search, saved-story, and conversation history
- Personalized recommendations use the existing TF-IDF model with selected news topics, reading history, saved stories, and language terms
- Compare related reports from other sources on each story, with publisher attribution, original links, and available summaries
- Cached articles are served before RSS refresh; stale feeds update asynchronously, RSS requests run in parallel, and canonical URLs are deduplicated
- Topical category filters normalize headlines and descriptions, score category-specific evidence, and select one primary topic to avoid cross-category noise; category result caches are versioned when this classification changes
- MIRA AI Chat (general research assistant)
- MIRA AI Chat, Ask Story, article analysis, and summaries follow the account's independently selected AI-response language
- Project-organized chat history, writing-coach feedback, and temporary PDF/image/audio/text uploads with local image previews
- Ask This Story uses cached article summaries for quick questions; full article retrieval and live source research are reserved for explicit deep-research tasks.
- AI News Analysis that separates *what the article states* from *AI interpretation*
- BM25 + sentence-embedding hybrid search, pgvector-backed retrieval, and RAG citations in chat and story analysis
- spaCy entity extraction and lemmatization, TF-IDF keywords, VADER sentiment, LDA topics, and K-means clustering
- SVM, Random Forest, and Logistic Regression category classifiers with held-out metrics when RSS category labels are sufficient
- Evidence-linked entity co-occurrence graphs (edges mean "co-mentioned in the same article," not a verified causal relationship)
- Accounts, saved articles, reading and search history, and saved conversations (Supabase)
- Installable PWA (manifest + service worker)

## Important notes
- **News feeds:** `backend/app/feeds.py` lists direct RSS feeds and Google News RSS searches for Philippine radio station names grouped by language. The shared station and language metadata is in `backend/app/media_sources.py`; News language, broadcaster, and region filters match the actual publisher reported by each feed, not the search query. Check publisher feed availability, licensing, and terms before relying on it. Publisher homepages are not RSS endpoints. Add direct PNA, PIA, GMA, ABS-CBN, and Manila Bulletin feeds only after confirming their feed URLs.
- **Live radio:** The Live section lists regional stations from the shared catalog and supports search/filtering by network, language, region, province, city, and station type. Radio entries remain unavailable until a verified official stream or live page is configured; only currently verified YouTube broadcasts are marked LIVE.
- **Podcasts:** Episode cards come from Apple Podcasts episode-search results. Publisher, language, and editorial filters are derived from returned episode metadata; a category with no matching published episodes remains empty rather than being populated with sample episodes.
- **News collection:** Articles are collected from those configured feeds, deduplicated by canonical URL, and stored in the `articles` table. Set `NEWS_REFRESH_TOKEN` in `backend/.env` to enable `POST /api/admin/news/refresh`; send it in the `X-Refresh-Token` header when invoking the endpoint manually or from a scheduler. The response includes feeds that could not be reached.
- **Cache-first news refresh:** The API serves its in-memory/Supabase article cache immediately and loads Supabase or refreshes RSS sources in a background worker. RSS requests use async HTTP, bounded timeouts, and up to two retries with exponential backoff; one failed feed does not prevent other feeds or cached stories from being served. The existing `articles.collected_at` field tracks successful ingestion, so no additional database table or migration is needed. Refresh intervals for source sections can be overridden in backend `NEWS_REFRESH_INTERVALS_SECONDS`, for example `{"local":900,"regional":900,"national":600,"international":1200}`. Browser cache expirations can be overridden in frontend `NEXT_PUBLIC_NEWS_REFRESH_INTERVALS_SECONDS`; supported defaults are trending 300s, national 600s, regional/local 900s, international 1200s, business 900s, sports 600s, and agriculture/education 1800s. Topical tabs are filters over the shared feed corpus rather than independent source integrations, so they reuse the same scheduled RSS refreshes.
- **Article images:** MIRA reads image links from RSS media, enclosures, and embedded HTML. If a feed omits images, it looks for Open Graph/Twitter image metadata in a bounded background job and saves discovered image URLs for later feed refreshes. Some publishers do not expose image metadata or block automated requests, so those stories will still use the placeholder.
- **Trending Stories** prioritizes local/regional, Philippine national, then international stories by publication time. It is not a social-media or cross-publisher trend measurement; add an independently sourced trend signal before presenting it as one.
- **AI is an assistant, not a fact-checker.** The system prompt tells the configured AI provider to separate article content from interpretation and never to guarantee that a claim is true.
- **Media review is not an authenticity verdict.** Uploaded files are processed by the selected vision-capable provider for the current response and are not stored by MIRA; generated clues cannot prove that media is genuine or manipulated. Do not upload confidential source material.
- **Chat citations and media review:** replies stream as the model generates them and show only retrieved news sources the assistant explicitly cites; available publisher images appear as small thumbnails. General chat avoids blocking live-news searches unless the prompt explicitly asks for current/recent news or sources; it uses relevant stored articles when available. Media review gives a Supported, Misleading, False, or Unverified verdict, and distinguishes claim accuracy from image authenticity. Upload filenames and text-file content help retrieve related reports, but visual inspection alone cannot prove authenticity and unrelated articles are not evidence. Retrieved news is limited to established publishers such as BBC, Rappler, Philippine Daily Inquirer, Al Jazeera, The Guardian, Deutsche Welle, France 24, Reuters, and AP. Network/model response times still vary.
- **Classifier training data:** models train only on collected RSS category labels and report "insufficient labeled data" until at least two categories have five articles each. Metrics use a stratified holdout split; the RSS labels may be noisy and are not editorially verified.
- **Search setup:** apply the updated schema before using semantic search with Supabase. Search uses BM25 and sentence-transformer cosine similarity; article vectors are persisted in the pgvector table.
- **News discovery:** searches query the public Google News RSS search interface and merge returned publisher-attributed records with the stored article archive. Search filters are applied to retrieved dates, sections, and categories; explicit years and date ranges are extracted from natural-language queries. Trending remains a separate feed view.
- **Feed loading:** a warm backend serves stored/cached stories immediately. On a cold backend, the API returns promptly while Supabase is loaded in the background; the browser can show its IndexedDB snapshot immediately and polls for the central cache. Interest ranking uses lightweight TF-IDF; sentence-transformer inference remains reserved for explicit search and RAG.
- **Offline news:** the dashboard, visited article details, and signed-in saved-story lists are cached in browser IndexedDB. They are hydrated before API revalidation; saved-story cache keys are scoped to the signed-in user. The dashboard and navigation show connection state and the last successful synchronization timestamp.
- Keep the `service_role` key on the backend only. Never expose it in the frontend.
