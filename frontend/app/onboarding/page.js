"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { useLanguage } from "@/components/LanguageProvider";

const JOURNALISM_FIELDS = [
  "News Writing",
  "Sports Journalism",
  "Feature Writing",
  "Editorial Writing",
  "Photojournalism",
  "Investigative Journalism",
  "Science and Technology",
  "Mobile Journalism",
  "Campus Journalism",
  "Media Arts",
  "Campus News Writing",
  "Campus Editorial Writing",
  "Campus Feature Writing",
  "Campus Sports Writing",
  "Campus Science and Technology Writing",
  "Campus Photojournalism",
  "Campus Copyreading and Headline Writing",
  "Campus Cartooning",
  "Campus Radio Broadcasting",
  "Campus TV Broadcasting",
  "Campus Collaborative Publishing",
  "Campus Online Publishing",
];

const NEWS_INTERESTS = [
  "Politics",
  "Health",
  "Sports",
  "Entertainment",
  "Technology",
  "Business",
  "Education",
  "Environment",
  "Agriculture",
  "Crime & Safety",
];

export default function Onboarding() {
  const { language, t } = useLanguage();
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [fields, setFields] = useState([]);
  const [interests, setInterests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    supabase?.auth.getSession().then(({ data }) => {
      const userId = data.session?.user?.id;
      if (!userId || localStorage.getItem(`mira_pending_onboarding:${userId}`) !== "true") {
        router.replace("/");
      }
    });
    api("/api/profile/preferences")
      .then((preferences) => {
        if (!active) return;
        setFields(preferences.journalism_fields || []);
        setInterests(preferences.interests || []);
      })
      .catch((requestError) => {
        if (active) setError(requestError.status === 401
          ? t("Please log in to personalize your MIRA dashboard.")
          : t("Couldn’t load your profile: {message}", { message: t(requestError.message) }));
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [router, t]);

  function toggleField(field) {
    setFields((current) => {
      if (current.includes(field)) return current.filter((item) => item !== field);
      if (current.length >= 3) return current;
      return [...current, field];
    });
  }

  function toggleInterest(interest) {
    setInterests((current) => current.includes(interest)
      ? current.filter((item) => item !== interest)
      : [...current, interest]);
  }

  async function finish() {
    setSaving(true);
    setError("");
    try {
      await api("/api/profile/preferences", {
        method: "PUT",
        body: {
          interests,
          journalism_fields: fields,
          onboarding_completed: true,
          system_language: language,
        },
      });
      const { data } = await supabase.auth.getSession();
      const userId = data.session?.user?.id;
      if (userId) localStorage.removeItem(`mira_pending_onboarding:${userId}`);
      router.replace("/");
    } catch (requestError) {
      setError(t("Couldn’t save your preferences: {message}", { message: t(requestError.message) }));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="mx-auto max-w-3xl animate-pulse py-24 text-center text-sm text-white/65">{t("Preparing your MIRA workspace…")}</p>;
  }

  return (
    <div className="onboarding-layout">
      <header className="onboarding-header">
        <Link href="/" className="auth-brand">
          <img src="/mira-logo.png" alt="" aria-hidden="true" className="mira-logo-dark h-8 w-8 object-contain" />
          <img src="/mira-logo-light.png" alt="" aria-hidden="true" className="mira-logo-light h-8 w-8 object-contain" />
          MIRA
        </Link>
        <span className="onboarding-step-label">{t("YOUR PERSONALIZED NEWSROOM")} · {step} {t("OF 2")}</span>
      </header>

      <main className="onboarding-card">
        <div className="onboarding-progress" aria-label={t("Step {step} of 2", { step })}>
          <span className={step >= 1 ? "progress-active" : ""} />
          <span className={step >= 2 ? "progress-active" : ""} />
        </div>
        {step === 1 ? (
          <>
            <p className="label mt-8">{t("First, tell us about your craft")}</p>
            <h1 className="font-display text-3xl font-bold sm:text-4xl">{t("What kind of journalism do you do?")}</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-white/60">
              {t("Choose up to three fields. We’ll use them to tailor your workspace and surface relevant reporting.")}
            </p>
            <div className="onboarding-options mt-7" aria-label={t("Journalism fields")}>
              {JOURNALISM_FIELDS.map((field) => {
                const selected = fields.includes(field);
                const locked = !selected && fields.length >= 3;
                return (
                  <button key={field} type="button" className={`onboarding-option ${selected ? "option-selected" : ""}`}
                    aria-pressed={selected} disabled={locked} onClick={() => toggleField(field)}>
                    <span className="option-check">{selected ? "✓" : "+"}</span>{t(field)}
                  </button>
                );
              })}
            </div>
            <div className="onboarding-footer">
              <span className="text-xs text-white/45">{t("{count} of 3 selected", { count: fields.length })}</span>
              <div className="flex items-center gap-3">
                <button type="button" className="btn-ghost" onClick={() => setStep(2)}>{t("Skip for now")}</button>
                <button type="button" className="btn" onClick={() => setStep(2)}>
                  {t("Confirm fields")} <span aria-hidden="true" className="ml-2">→</span>
                </button>
              </div>
            </div>
          </>
        ) : (
          <>
            <p className="label mt-8">{t("Make the news yours")}</p>
            <h1 className="font-display text-3xl font-bold sm:text-4xl">{t("What stories matter most to you?")}</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-white/60">
              {t("Pick topics you follow. MIRA combines these with your reading and saved stories to organize your recommendations.")}
            </p>
            <div className="onboarding-options mt-7" aria-label={t("News interests")}>
              {NEWS_INTERESTS.map((interest) => {
                const selected = interests.includes(interest);
                return (
                  <button key={interest} type="button" className={`onboarding-option ${selected ? "option-selected" : ""}`}
                    aria-pressed={selected} onClick={() => toggleInterest(interest)}>
                    <span className="option-check">{selected ? "✓" : "+"}</span>{t(interest)}
                  </button>
                );
              })}
            </div>
            <div className="onboarding-footer">
              <button type="button" className="text-sm font-semibold text-white/55 hover:text-white"
                onClick={() => setStep(1)}>← {t("Back")}</button>
              <div className="flex items-center gap-3">
                <button type="button" className="btn-ghost" onClick={finish} disabled={saving}>{t("Skip for now")}</button>
                <button type="button" className="btn" onClick={finish} disabled={saving}>
                  {saving ? t("saving") : t("Build my dashboard")} <span aria-hidden="true" className="ml-2">→</span>
                </button>
              </div>
            </div>
          </>
        )}
        {error && (
          <div role="alert" className="mt-5 rounded-xl border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-200">
            {error}
            {error.startsWith(t("Please log in")) && <Link href="/login" className="ml-2 underline">{t("Log in")}</Link>}
          </div>
        )}
      </main>
      <p className="onboarding-footnote">{t("Your picks are private and can be changed anytime in Settings.")}</p>
    </div>
  );
}
