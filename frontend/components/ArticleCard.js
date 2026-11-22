"use client";

import Link from "next/link";
import ArticleImage from "@/components/ArticleImage";
import { useLanguage } from "@/components/LanguageProvider";

export default function ArticleCard({ article, saved, onSave, compact = false, priority = false }) {
  const { t } = useLanguage();
  if (compact) {
    return (
      <article className="dashboard-compact-card">
        <ArticleImage article={article} className="dashboard-compact-image" priority={priority} />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between gap-2 text-[10px] font-semibold text-white/55">
            <span className="truncate">{article.source}</span>
            {article.published && <time className="shrink-0">{new Date(article.published).toLocaleDateString()}</time>}
          </div>
          <Link href={`/story/${article.id}`} className="mt-1 line-clamp-2 text-sm font-bold leading-snug hover:text-mira-blue-light">
            {article.title}
          </Link>
          {article.summary && (
            <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-white/65">
              {article.summary}
            </p>
          )}
          <div className="mt-auto flex items-center justify-between gap-2 pt-3">
            <Link href={`/story/${article.id}`} className="btn !px-3 !py-1.5 text-[11px]">{t("Read full story")}</Link>
            <button
              className="btn-ghost !px-3 !py-1.5 text-[11px]"
              onClick={() => onSave(article)}
              aria-label={saved ? t("Remove {title} from saved stories", { title: article.title }) : t("Save {title}", { title: article.title })}
            >
              {saved ? t("Saved ✓") : t("Save +")}
            </button>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article className="glass flex h-full flex-col overflow-hidden transition hover:border-mira-blue-light/60">
      <ArticleImage article={article} className="h-36 w-full sm:h-40" priority={priority} />

      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-center justify-between gap-2 text-xs font-semibold text-white/75">
          <span>{article.source}</span>
          {article.published && <span>{new Date(article.published).toLocaleDateString()}</span>}
        </div>
        <Link href={`/story/${article.id}`} className="line-clamp-3 font-display text-base font-semibold leading-snug hover:underline">
          {article.title}
        </Link>
        {article.summary && <p className="line-clamp-3 text-sm text-white/75">{article.summary}</p>}
        <div className="mt-auto flex gap-2 pt-2">
          <Link href={`/story/${article.id}`} className="btn !px-4 !py-2 text-xs">{t("Ask this story")}</Link>
          <button className="btn-ghost !px-4 !py-2 text-xs" onClick={() => onSave(article)}>{saved ? t("Saved ✓") : t("Save")}</button>
        </div>
      </div>
    </article>
  );
}
