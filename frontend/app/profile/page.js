"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { api } from "@/lib/api";
import { useLanguage } from "@/components/LanguageProvider";

export default function ProfilePage() {
  const { t } = useLanguage();
  const [user, setUser] = useState(null);
  const [stats, setStats] = useState({ saved: 0, history: 0, conversations: 0 });
  const [preferences, setPreferences] = useState(null);

  useEffect(() => {
    supabase?.auth.getSession().then(({ data }) => setUser(data.session?.user || null));
  }, []);

  useEffect(() => {
    Promise.allSettled([
      api("/api/favorites"),
      api("/api/history"),
      api("/api/conversations"),
      api("/api/profile/preferences"),
    ]).then(([saved, history, conversations, accountPreferences]) => {
      setStats({
        saved: saved.status === "fulfilled" ? (saved.value.favorites || []).length : 0,
        history: history.status === "fulfilled" ? (history.value.history || []).length : 0,
        conversations: conversations.status === "fulfilled" ? (conversations.value.conversations || []).length : 0,
      });
      if (accountPreferences.status === "fulfilled") setPreferences(accountPreferences.value);
    });
  }, []);

  if (!user) return (
    <section className="profile-signin glass">
      <span className="profile-signin-icon">M</span>
      <div>
        <p className="label">{t("Account")}</p>
        <h1 className="font-display text-3xl font-bold">{t("Sign in to Profile")}</h1>
        <p className="mt-2 text-sm text-white/60">{t("View your account details and MIRA activity.")}</p>
      </div>
      <Link href="/login" className="btn">{t("Sign in")}</Link>
    </section>
  );

  const displayName = user.user_metadata?.full_name || t("MIRA member");
  const initial = (displayName || "M").slice(0, 1).toUpperCase();
  const memberSince = user.created_at
    ? new Date(user.created_at).toLocaleDateString(undefined, { month: "long", year: "numeric" })
    : t("Recent member");
  const preferenceCount = [
    ...(preferences?.news_preferences || preferences?.interests || []),
    ...(preferences?.journalism_fields || []),
  ].filter((value, index, values) => values.indexOf(value) === index).length;

  return (
    <div className="profile-page">
      <header className="profile-heading">
        <div>
          <p className="label">{t("Account")}</p>
          <h1 className="font-display text-3xl font-bold">{t("Profile")}</h1>
        </div>
      </header>

      <section className="profile-card glass">
        <div className="profile-cover">
          <div className="profile-cover-grid" />
        </div>
        <div className="profile-summary">
          <div className="profile-avatar-wrap">
            <span className="profile-avatar">{initial}</span>
            <span className="profile-status" title={t("Active")} />
          </div>
          <div className="profile-identity">
            <div className="profile-name-row">
              <h2 className="font-display">{displayName}</h2>
              <span className="profile-member-badge">{t("MIRA member")}</span>
            </div>
            <p>{user.email}</p>
          </div>
          <div className="profile-actions">
            <Link href="/settings" className="btn">{t("Open settings")}</Link>
            <Link href="/history" className="btn-ghost">{t("View activity")}</Link>
          </div>
        </div>
      </section>

      <section className="profile-stats" aria-label={t("Account overview")}>
        <Link href="/saved" className="profile-stat glass">
          <span className="profile-stat-icon">⌑</span>
          <div><strong>{stats.saved}</strong><span>{t("Saved stories")}</span></div>
          <span className="profile-stat-arrow">›</span>
        </Link>
        <Link href="/history" className="profile-stat glass">
          <span className="profile-stat-icon">◷</span>
          <div><strong>{stats.history}</strong><span>{t("Read stories")}</span></div>
          <span className="profile-stat-arrow">›</span>
        </Link>
        <Link href="/chat" className="profile-stat glass">
          <span className="profile-stat-icon">✦</span>
          <div><strong>{stats.conversations}</strong><span>{t("Conversations")}</span></div>
          <span className="profile-stat-arrow">›</span>
        </Link>
      </section>

      <div className="profile-details-grid">
        <section className="profile-detail-card glass">
          <div className="profile-section-heading">
            <div>
              <p className="label">{t("About")}</p>
              <h2>{t("Account information")}</h2>
            </div>
            <Link href="/settings" className="profile-edit-link">{t("Edit")} →</Link>
          </div>
          <dl className="profile-info-list">
            <div>
              <dt>{t("Email address")}</dt>
              <dd>{user.email}</dd>
            </div>
            <div>
              <dt>{t("Member since")}</dt>
              <dd>{memberSince}</dd>
            </div>
            <div>
              <dt>{t("Account status")}</dt>
              <dd><span className="profile-status-dot" />{t("Active")}</dd>
            </div>
          </dl>
        </section>

        <section className="profile-detail-card glass">
          <div className="profile-section-heading">
            <div>
              <p className="label">{t("Personalize")}</p>
              <h2>{t("Reading preferences")}</h2>
            </div>
            <Link href="/settings" className="profile-edit-link">{t("Manage")} →</Link>
          </div>
          <div className="profile-preferences">
            <div className="profile-preference-icon">◫</div>
            <div>
              <strong>{preferenceCount ? t("{count} interests selected", { count: preferenceCount }) : t("Build your news feed")}</strong>
              <p>{t("Choose topics and journalism fields that match what you want to follow.")}</p>
            </div>
          </div>
        </section>
      </div>

      <section className="profile-activity glass">
        <div className="profile-section-heading">
          <div>
            <p className="label">{t("Activity")}</p>
            <h2>{t("Continue where you left off")}</h2>
          </div>
        </div>
        <Link href="/history" className="profile-activity-link">
          <span className="profile-activity-icon">◷</span>
          <div>
            <strong>{t("View reading history")}</strong>
            <span>{t("Revisit articles and conversations")}</span>
          </div>
          <span className="profile-stat-arrow">›</span>
        </Link>
      </section>
    </div>
  );
}
