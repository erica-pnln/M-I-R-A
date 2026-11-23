"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { useLanguage } from "@/components/LanguageProvider";

export default function Login() {
  const { t } = useLanguage();
  const router = useRouter();
  const [mode, setMode] = useState("in");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!supabase) return setMsg(t("Supabase isn't configured. Check .env.local."));
    setMsg("");
    setBusy(true);

    try {
      if (mode === "up") {
        if (!username.trim()) return setMsg(t("Username is required."));
        if (password.length < 6) return setMsg(t("Password must be at least 6 characters."));
        if (password !== confirm) return setMsg(t("Passwords do not match."));

        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: {
            data: {
              username: username.trim(),
              display_name: username.trim(),
              mira_welcome_completed: false,
            },
          },
        });
        if (error) return setMsg(t(error.message));
        if (data.session) {
          if (data.user?.id) localStorage.setItem(`mira_pending_onboarding:${data.user.id}`, "true");
          router.push("/onboarding");
          return;
        }
        if (data.user?.id) localStorage.setItem(`mira_pending_onboarding:${data.user.id}`, "true");
        setMsg(t("Check your email to confirm your account, then log in."));
        setMode("in");
        return;
      }

      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) return setMsg(t(error.message));
      const { data } = await supabase.auth.getSession();
      const userId = data.session?.user?.id;
      if (userId && localStorage.getItem(`mira_pending_onboarding:${userId}`) === "true") {
        router.replace("/onboarding");
      } else {
        router.replace("/");
      }
    } catch (error) {
      setMsg(t(error.message || "Something went wrong. Please try again."));
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    await submit();
  }

  return (
    <div className="auth-layout">
      <section className="auth-story">
        <p className="auth-hero-label">{t("AI-powered media intelligence")}</p>
        <Link href="/" className="auth-brand" aria-label="MIRA home">
          <img src="/mira-logo.png" alt="MIRA" className="mira-logo-dark auth-logo-blink aspect-square h-auto w-[230px] max-w-full object-contain" />
          <img src="/mira-logo-light.png" alt="MIRA" className="mira-logo-light auth-logo-blink aspect-square h-auto w-[230px] max-w-full object-contain" />
        </Link>
        <div className="auth-story-content">
          <div className="auth-copy">
            <h1 className="auth-copy-title font-display text-4xl font-bold leading-tight sm:text-5xl">
              {t("Go beyond")}<br />
              <span className="auth-copy-highlight">{t("the headline.")}</span>
            </h1>
            <p className="auth-copy-description mt-4 max-w-md text-sm leading-6 text-white/65">
              {t("MIRA means Media Intelligence & Research Assistant—an AI-powered guide to the news, research, and context that matter to your work.")}
            </p>
          </div>
          <div className="auth-story-note auth-story-note-enter">
            <span className="auth-pulse" />
            <span>{t("Independent thinking. Smarter discovery.")}</span>
          </div>
        </div>
      </section>

      <section className="auth-card">
        <div className="auth-switch" role="tablist" aria-label={t("Account options")}>
          <button type="button" role="tab" aria-selected={mode === "in"}
            className={mode === "in" ? "auth-switch-active" : ""}
            onClick={() => { setMode("in"); setMsg(""); }}>
            {t("Log in")}
          </button>
          <button type="button" role="tab" aria-selected={mode === "up"}
            className={mode === "up" ? "auth-switch-active" : ""}
            onClick={() => { setMode("up"); setMsg(""); }}>
            {t("Create account")}
          </button>
        </div>
        <p className="label mt-8">{mode === "in" ? t("Welcome back") : t("Start your MIRA journey")}</p>
        <h2 className="font-display text-3xl font-bold">
          {mode === "in" ? t("Log in") : t("Create account")}
        </h2>
        <p className="mt-2 text-sm text-white/55">
          {mode === "in" ? t("Pick up where your curiosity left off.") : t("A few details, then your dashboard is yours.")}
        </p>
        <form className="mt-7 space-y-4" onSubmit={handleSubmit}>
          <label className="auth-field">
            <span>{t("Email address")}</span>
            <input className="input" type="email" autoComplete="email" placeholder="you@example.com"
              value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          {mode === "up" && (
            <label className="auth-field">
              <span>{t("Username")}</span>
              <input className="input" type="text" autoComplete="username" placeholder={t("How should we call you?")}
                value={username} onChange={(event) => setUsername(event.target.value)} required />
            </label>
          )}
          <label className="auth-field">
            <span>{t("Password")}</span>
            <input className="input" type="password" autoComplete={mode === "in" ? "current-password" : "new-password"}
              placeholder={t("At least 6 characters")} value={password}
              onChange={(event) => setPassword(event.target.value)} required minLength={6} />
          </label>
          {mode === "up" && (
            <label className="auth-field">
              <span>{t("Confirm password")}</span>
              <input className="input" type="password" autoComplete="new-password" placeholder={t("Enter your password again")}
                value={confirm} onChange={(event) => setConfirm(event.target.value)} required minLength={6} />
            </label>
          )}
          <button className="btn w-full !rounded-xl !py-3.5" type="submit" disabled={busy} data-loading="true" aria-busy={busy}>
            {busy ? (
              <span className="mira-button-loading" role="status">
                <span className="mira-button-spinner" aria-hidden="true" />
                {t("Please wait…")}
              </span>
            ) : mode === "in" ? t("Log in") : t("Create account")}
          </button>
          {msg && <p role="status" className="auth-message">{msg}</p>}
        </form>
        <p className="mt-6 text-center text-xs text-white/45">
          {mode === "in" ? t("New to MIRA?") : t("Already have an account?")}{" "}
          <button type="button" className="font-semibold text-mira-blue-light hover:text-white"
            onClick={() => { setMode(mode === "in" ? "up" : "in"); setMsg(""); }}>
            {mode === "in" ? t("Create account") : t("Log in")}
          </button>
        </p>
      </section>
    </div>
  );
}
