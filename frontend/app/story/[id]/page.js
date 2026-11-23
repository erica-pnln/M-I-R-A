"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import Chat from "@/components/Chat";
import ArticleImage from "@/components/ArticleImage";
import { getCachedNews, putCachedNews } from "@/lib/newsCache";
import { useLanguage } from "@/components/LanguageProvider";

const List = ({ items }) => (items?.length ? <ul className="list-disc space-y-1 pl-5">{items.map((x, i) => <li key={i}>{x}</li>)}</ul> : null);

export default function Story() {
  const { language, t } = useLanguage();
  const dateLocale = language === "fil" ? "fil-PH" : language === "ceb" ? "ceb-PH" : "en-US";
  const { id } = useParams();
  const [a, setA] = useState(null);
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [coverage, setCoverage] = useState([]);
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [coverageError, setCoverageError] = useState("");
  const [usingCachedArticle, setUsingCachedArticle] = useState(false);
  const [connectionIssue, setConnectionIssue] = useState(false);
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const updateOnline = () => setOnline(navigator.onLine);
    updateOnline();
    window.addEventListener("online", updateOnline);
    window.addEventListener("offline", updateOnline);
    return () => {
      window.removeEventListener("online", updateOnline);
      window.removeEventListener("offline", updateOnline);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadArticle() {
      let cachedArticle = null;
      try {
        cachedArticle = await getCachedNews(`article:${id}`);
        if (cachedArticle && !cancelled) {
          setA(cachedArticle);
          setUsingCachedArticle(true);
        }
      } catch (cacheError) {
        console.warn("Could not read the cached MIRA article:", cacheError);
      }
      if (!navigator.onLine) {
        setConnectionIssue(true);
        if (!cachedArticle) setError(t("You’re offline and this article is not cached on this device."));
        return;
      }
      try {
        const art = await api(`/api/articles/${id}`);
        if (cancelled) return;
        setA(art);
        setUsingCachedArticle(false);
        setConnectionIssue(false);
        putCachedNews(`article:${id}`, art).catch((cacheError) => {
          console.warn("Could not update the cached MIRA article:", cacheError);
        });
        api("/api/history", { method: "POST", body: art }).catch(() => {});
      } catch (e) {
        if (!cancelled) {
          setConnectionIssue(true);
          if (!cachedArticle) setError(t("Couldn’t load article: {message}", { message: t(e.message) }));
        }
      }
    }
    loadArticle();
    if (online) {
      api(`/api/compare/${id}`).then((result) => setCoverage(result.reports || []))
        .catch((e) => setCoverageError(t(e.message)))
        .finally(() => setCoverageLoading(false));
    } else {
      setCoverageLoading(false);
      setCoverageError(t("Related coverage is unavailable offline."));
    }
    return () => { cancelled = true; };
  }, [id, online, t]);

  async function analyze() {
    setAnalyzing(true);
    try { setAnalysis(await api(`/api/analyze/${id}`, { method: "POST" })); }
    catch (e) { setError(t("Couldn’t analyze this story: {message}", { message: t(e.message) })); }
    finally { setAnalyzing(false); }
  }

  if (error && !a) return <p className="text-red-400">{t(error)}</p>;
  if (!a) return <p className="text-white/70">{t("Loading…")}</p>;

  return (
    <>
      <Link href="/" className="btn-ghost inline-block">← {t("Back")}</Link>
      <div className="mt-5 grid items-start gap-5 lg:grid-cols-[1.3fr_1fr]">
        <article className="glass p-6">
          <div className="text-xs font-semibold text-white/75">{a.source}{a.published && ` · ${new Date(a.published).toLocaleString(dateLocale)}`}</div>
          {(usingCachedArticle || connectionIssue) && (
            <p role="status" className="mt-2 text-xs text-amber-100">
              {connectionIssue ? t("Connection unavailable · showing the cached article.") : t("Showing a cached copy while MIRA checks for updates.")}
            </p>
          )}
          <ArticleImage article={a} className="mt-4 h-72 max-h-[28rem] w-full rounded-xl object-cover" />
          <h1 className="my-3 font-display text-3xl font-bold leading-tight">{a.title}</h1>
          <p className="text-white/90">{a.summary}</p>
          <a href={a.url} target="_blank" rel="noreferrer" className="btn mt-4 inline-block">{t("Read the original at {source} ↗", { source: a.source })}</a>

          <section className="mt-8 border-t border-white/10 pt-5">
            <h2 className="font-display text-xl font-bold">{t("Compare coverage")}</h2>
            <p className="mt-1 text-xs text-white/60">{t("Related reports from other sources, ranked by text similarity. Read the originals to compare reporting, evidence, and framing.")}</p>
            {coverageLoading && <p className="mt-3 animate-pulse text-sm text-white/60">{t("Finding related reports…")}</p>}
            {coverageError && <p role="status" className="mt-3 text-sm text-amber-200">{t("Related coverage is unavailable: {message}", { message: coverageError })}</p>}
            {!coverageLoading && !coverageError && !coverage.length && <p className="mt-3 text-sm text-white/60">{t("No related reports from other sources are available yet.")}</p>}
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {coverage.map((report) => (
                <article key={report.id} className="rounded-xl border border-white/10 bg-white/[.04] p-4">
                  <p className="text-xs font-semibold text-mira-blue-light">{report.source}{report.published && ` · ${new Date(report.published).toLocaleDateString(dateLocale)}`}</p>
                  <h3 className="mt-1 font-semibold">{report.title}</h3>
                  {report.summary && <p className="mt-2 line-clamp-4 text-sm text-white/70">{report.summary}</p>}
                  <a className="mt-3 inline-block text-sm underline" href={report.url} target="_blank" rel="noreferrer">{t("Read original report ↗")}</a>
                </article>
              ))}
            </div>
          </section>

          <h2 className="mt-8 font-display text-xl">{t("AI News Analysis")}</h2>
          {!analysis && <button className="btn mt-3" onClick={analyze} disabled={analyzing}>{analyzing ? t("Analyzing…") : t("Analyze this story")}</button>}
          {error && <p className="mt-2 text-sm text-red-400">{t(error)}</p>}
          {analysis && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border-l-4 border-mira-blue bg-white/[.06] p-4 text-sm">
                <span className="label">{t("What the article states")}</span>
                <p className="mb-2">{analysis.main_issue}</p>
                <List items={analysis.key_points} />
                {analysis.people_orgs?.length > 0 && <p className="mt-2"><b>{t("People & organizations:")}</b> {analysis.people_orgs.join(", ")}</p>}
                {analysis.locations?.length > 0 && <p className="mt-1"><b>{t("Locations:")}</b> {analysis.locations.join(", ")}</p>}
                {analysis.claims_to_verify?.length > 0 && <><p className="mb-1 mt-3 font-bold">{t("Claims to verify")}</p><List items={analysis.claims_to_verify} /></>}
              </div>
              <div className="rounded-xl border-l-4 border-mira-blue-light bg-mira-blue-dark/40 p-4 text-sm">
                <span className="label">{t("AI interpretation")}</span>
                {analysis.background && <p className="mb-2"><b>{t("Background:")}</b> {analysis.background}</p>}
                {analysis.implications && <p className="mb-2"><b>{t("Possible implications:")}</b> {analysis.implications}</p>}
                {analysis.perspectives?.length > 0 && <><p className="font-bold">{t("Perspectives")}</p><List items={analysis.perspectives} /></>}
                {analysis.angles?.length > 0 && <><p className="mt-2 font-bold">{t("Reporting angles")}</p><List items={analysis.angles} /></>}
              </div>
              {analysis.nlp && (
                <div className="rounded-xl bg-white/[.06] p-4 text-sm sm:col-span-2">
                  <span className="label">{t("Text signals (automated, verify independently)")}</span>
                  <p className="mt-2"><b>{t("Sentiment:")}</b> {t(analysis.nlp.sentiment?.label || "unavailable")}</p>
                  {analysis.nlp.keywords?.length > 0 && (
                    <p className="mt-1"><b>{t("TF-IDF keywords:")}</b> {analysis.nlp.keywords.map((item) => item.term).join(", ")}</p>
                  )}
                  {analysis.nlp.entities?.people?.length > 0 && <p className="mt-1"><b>{t("People:")}</b> {analysis.nlp.entities.people.join(", ")}</p>}
                  {analysis.nlp.entities?.organizations?.length > 0 && <p className="mt-1"><b>{t("Organizations:")}</b> {analysis.nlp.entities.organizations.join(", ")}</p>}
                  {analysis.nlp.entities?.locations?.length > 0 && <p className="mt-1"><b>{t("Locations:")}</b> {analysis.nlp.entities.locations.join(", ")}</p>}
                  {analysis.nlp.entities?.dates?.length > 0 && <p className="mt-1"><b>{t("Dates:")}</b> {analysis.nlp.entities.dates.join(", ")}</p>}
                </div>
              )}
              {analysis.cited_sources?.length > 0 && (
                <div className="rounded-xl bg-white/[.06] p-4 text-sm sm:col-span-2">
                  <span className="label">{t("Retrieved sources cited")}</span>
                  <ul className="mt-2 list-disc space-y-1 pl-5">
                    {analysis.cited_sources.map((source) => (
                      <li key={source.id}>
                        <a className="underline" href={source.url} target="_blank" rel="noreferrer">
                          [{source.id}] {source.title} — {source.source}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          <p className="mt-6 text-xs text-white/60">{t("AI assistance is not a guarantee that a claim is true. Verify with primary sources. The journalist makes the final judgment.")}</p>
        </article>

        <aside className="glass p-5 lg:sticky lg:top-24">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-mira-blue-light/20 bg-white/[.04] p-1">
                <img
                  src="/mira-chat.png"
                  alt="MIRA Chat AI"
                  className="h-full w-full object-contain"
                />
              </div>
              <h2 className="font-display text-xl">{t("Ask This Story")}</h2>
            </div>
            <Link href="/ask-story/history" className="btn-ghost !px-3 !py-1.5 text-xs">
              {t("Conversation history")}
            </Link>
          </div>
          <Chat endpoint="/api/ask" extra={{ article_id: id }}
            intro={t("Ask about this article. I start from its text and name any extra sources.")}
            placeholder={t("Ask about this story…")}
            suggestions={["What does this mean?", "Who is involved?", "What happened before?", "Suggest interview questions"].map(t)} />
          <p className="mt-3 text-xs text-white/50">
            {t("Sign in to save Ask Story conversations to your account and review them later.")}
          </p>
        </aside>
      </div>
    </>
  );
}
