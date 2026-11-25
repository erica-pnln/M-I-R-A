# MIRA Presentation Deck

**Title:** MIRA - Media Intelligence and Research Assistant<br>
**Tagline:** Go Beyond the Headline<br>
**Format:** 12-slide presentation

---

## Slide 1 - Title

### MIRA
**Media Intelligence and Research Assistant**

*Go Beyond the Headline.*

**Presented by:** [Student/Team Name]<br>
**Course/Subject:** [Subject Name]
**Date:** [Presentation Date]

**Presenter opening:**
> MIRA is a news discovery and journalism research platform designed to help users understand information in context, not only read headlines.

---

## Slide 2 - The Problem

### Why MIRA?

- News is published across many websites and formats.
- Readers may encounter headlines without enough context.
- Verifying claims, related reports, and source information takes time.
- Journalists and students need tools for research, summarization, and organization.
- Language barriers can limit access to Philippine and international reporting.

**Central problem:**
> How can a platform make news discovery, research, and information understanding easier and more accessible?

---

## Slide 3 - Project Overview

### MIRA: A News Intelligence Platform

MIRA combines:

- Philippine and international news discovery
- AI-assisted research and conversation
- Story summaries and article analysis
- Media review and source-linked information
- Personalized recommendations
- Saved stories, reading history, and research projects

**Main goal:** Provide a responsive digital environment where users can explore, compare, analyze, and organize news.

---

## Slide 4 - Project Objectives

### Objectives

1. Build a responsive news dashboard.
2. Collect and organize articles from RSS news sources.
3. Provide BM25 and semantic search.
4. Perform basic NLP analysis such as entities, sentiment, keywords, and topics.
5. Support AI chat for general research and story-specific questions.
6. Help users save articles and maintain research history.
7. Provide English, Filipino, and Bisaya interface support.
8. Make the system installable as a Progressive Web App.

**Presenter prompt:**
> These objectives turn MIRA from a simple news page into a complete research assistant.

---

## Slide 5 - Scope and Limitations

### Project Scope

**Included**
- News dashboard and category filters
- Live radio and podcast discovery
- Search and article recommendations
- AI chat and story analysis
- Supabase accounts and saved data
- Offline-ready PWA features

**Limitations**
- News availability depends on connected RSS feeds.
- AI responses vary by provider, model, and network.
- RSS category labels may be noisy.
- Media-review clues do not prove authenticity or manipulation.
- MIRA is an assistant, not a guaranteed fact-checker.

---

## Slide 6 - System Architecture

### How MIRA Works

```text
News RSS Sources
       |
       v
FastAPI Backend -----> Supabase Database/Auth
       |                   |
       |                   +-> Articles, favorites,
       |                       history, conversations
       v
AI / NLP Services
       |
       v
Next.js Frontend
```

**Technology stack**
- Frontend: Next.js 14, React, Tailwind CSS
- Backend: Python, FastAPI
- Database/Auth: Supabase PostgreSQL
- AI: Gemini, xAI, and Hugging Face
- NLP: spaCy, VADER, scikit-learn, Sentence Transformers

---

## Slide 7 - Core Features

### User-Facing Features

| Feature | Purpose |
|---|---|
| News dashboard | Displays trending, national, regional, local, and international stories |
| Search | Finds relevant news using keywords and semantic similarity |
| Saved stories | Allows users to bookmark reports |
| Ask This Story | Answers questions using the selected article |
| MIRA AI Chat | Supports general research and project-based conversations |
| Live and Podcasts | Provides broadcaster, radio, and podcast discovery |
| Profile and Settings | Personalizes interests, fields, language, and account activity |

**Presenter prompt:**
> MIRA places these tools in one shared interface instead of requiring users to switch between separate services.

---

## Slide 8 - AI-Assisted Research

### AI Chat and Story Analysis

MIRA supports:

- General research questions
- Story-specific questions
- Article summaries
- Claim and context analysis
- Media review with source-backed context
- Project-organized conversations
- English, Filipino, and Bisaya AI responses

**Important behavior:**
> MIRA distinguishes article statements from AI interpretation. It should assist research rather than present uncertain output as verified truth.

**Possible demo:** Open **Chat**, ask a current-news question, and show the cited sources.

---

## Slide 9 - Search and NLP Pipeline

### How Stories Become Insights

```text
RSS Article
    |
    v
Cleaning and Deduplication
    |
    +--> BM25 keyword ranking
    +--> Sentence embeddings and semantic search
    +--> spaCy entities and lemmas
    +--> TF-IDF keywords
    +--> VADER sentiment
    +--> LDA / K-means topics
    +--> Category classification
```

**Key point:** MIRA combines traditional search with semantic retrieval to find both keyword matches and conceptually related reports.

---

## Slide 10 - Personalization and Data Management

### A More Relevant Experience

- Guided onboarding selects journalism fields and news interests.
- Recommendations use TF-IDF, reading history, saved stories, and language terms.
- Supabase stores accounts, favorites, history, conversations, and preferences.
- Reading history and chat projects keep research organized.
- IndexedDB caches news for faster loading and offline viewing.
- The PWA can be installed on supported devices.

**Privacy note:** Credentials remain on the backend; media uploads are temporary and confidential source material should not be uploaded.

---

## Slide 11 - Demonstration

### Live Demo Checklist

1. Open the MIRA dashboard.
2. Show trending, national, regional, and topical news.
3. Search for a relevant story.
4. Open an article and display its summary or analysis.
5. Use **Ask This Story**.
6. Open MIRA AI Chat and show project/history organization.
7. Save the story and show it in the Saved section.
8. Show settings for English, Filipino, or Bisaya.
9. Open the Live or Podcast section.
10. Demonstrate the responsive layout or PWA behavior.

**Backup plan:** Keep a few pre-opened browser tabs and screenshots in case live news or provider responses are unavailable.

---

## Slide 12 - Conclusion and Future Improvements

### Conclusion

MIRA provides an integrated platform for:

- Discovering news
- Understanding article context
- Searching and comparing reports
- Researching with AI
- Organizing saved stories and conversations

**Future improvements**
- Verified fact-checking integrations
- Broader direct publisher partnerships
- Stronger multilingual NLP
- Real-time collaboration
- Public trend-analysis indicators
- Automated source and bias transparency
- Mobile applications

**Closing statement:**
> MIRA helps users go beyond the headline by combining technology, journalism workflows, and responsible AI assistance.

---

## Suggested Presentation Flow

- **Slides 1-3:** Introduction and problem
- **Slides 4-6:** Objectives and system design
- **Slides 7-10:** Features and technical implementation
- **Slide 11:** Live demonstration
- **Slide 12:** Conclusion and future work

**Recommended time:** 8-12 minutes, with 3-4 minutes reserved for the live demo.
