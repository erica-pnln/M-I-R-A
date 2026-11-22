"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useLanguage } from "@/components/LanguageProvider";

const DEFAULT_WIDTH = 310;
const MIN_WIDTH = 230;
const MAX_WIDTH = 400;
const COLLAPSED_WIDTH = 76;
const WIDTH_STORAGE_KEY = "mira-sidebar-width";
const COLLAPSED_STORAGE_KEY = "mira-sidebar-collapsed";

const LINKS = [
  ["/", "home"],
  ["/chat", "chat"],
  ["/news", "news"],
  ["/live", "live"],
  ["/podcast", "podcast"],
  ["/saved", "saved"],
  ["/history", "history"],
  ["/settings", "settings"],
];

export default function Nav() {
  const path = usePathname();
  const [user, setUser] = useState(null);
  const [online, setOnline] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_WIDTH);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [resizing, setResizing] = useState(false);
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const resizeStart = useRef(null);
  const { t } = useLanguage();

  useEffect(() => {
    try {
      const savedWidth = Number(window.localStorage.getItem(WIDTH_STORAGE_KEY));
      if (Number.isFinite(savedWidth) && savedWidth >= MIN_WIDTH && savedWidth <= MAX_WIDTH) {
        setSidebarWidth(savedWidth);
      }
      setCollapsed(window.localStorage.getItem(COLLAPSED_STORAGE_KEY) === "true");
    } catch (error) {
      console.error("Could not load MIRA sidebar preferences:", error);
    } finally {
      setPreferencesLoaded(true);
    }
  }, []);

  useEffect(() => {
    const width = collapsed ? COLLAPSED_WIDTH : sidebarWidth;
    document.documentElement.style.setProperty("--mira-sidebar-width", `${width}px`);
    if (!preferencesLoaded) return;

    try {
      window.localStorage.setItem(WIDTH_STORAGE_KEY, String(sidebarWidth));
      window.localStorage.setItem(COLLAPSED_STORAGE_KEY, String(collapsed));
    } catch (error) {
      console.error("Could not save MIRA sidebar preferences:", error);
    }
  }, [sidebarWidth, collapsed, preferencesLoaded]);

  useEffect(() => {
    if (!resizing) return undefined;
    document.body.classList.add("mira-sidebar-resizing");
    return () => document.body.classList.remove("mira-sidebar-resizing");
  }, [resizing]);

  function startResize(event) {
    event.preventDefault();
    resizeStart.current = { x: event.clientX, width: sidebarWidth, pointerId: event.pointerId };
    event.currentTarget.setPointerCapture(event.pointerId);
    setResizing(true);
  }

  function resizeSidebar(event) {
    if (!resizeStart.current || resizeStart.current.pointerId !== event.pointerId) return;
    const maxWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, window.innerWidth * 0.45));
    const width = resizeStart.current.width + event.clientX - resizeStart.current.x;
    setSidebarWidth(Math.min(maxWidth, Math.max(MIN_WIDTH, width)));
  }

  function resizeWithKeyboard(event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const maxWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, window.innerWidth * 0.45));
    const delta = event.key === "ArrowRight" ? 16 : -16;
    setSidebarWidth((width) => Math.min(maxWidth, Math.max(MIN_WIDTH, width + delta)));
  }

  function endResize(event) {
    if (resizeStart.current?.pointerId !== event.pointerId) return;
    resizeStart.current = null;
    setResizing(false);
  }

  function signOut() {
    if (
      document.documentElement.dataset.miraUnsavedSettings === "true"
      && !window.confirm(t("Discard unsaved changes?"))
    ) return;
    supabase.auth.signOut();
  }

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
    if (!supabase) return;
    const updateUser = (session) => {
      setUser(session?.user ?? null);
    };
    supabase.auth.getSession().then(({ data }) => updateUser(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, session) => updateUser(session));
    return () => {
      data.subscription.unsubscribe();
    };
  }, []);

  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          className="mira-mobile-backdrop"
          aria-label={t("Close navigation")}
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={`mira-sidebar${collapsed ? " is-collapsed" : ""}${resizing ? " is-resizing" : ""}${mobileOpen ? " is-mobile-open" : ""}`}
      >
        <Link href="/" className="mira-brand" onClick={() => setMobileOpen(false)}>
          <img src="/mira-logo.png" alt="" aria-hidden="true" className="h-24 w-24 object-contain" />
          <span className="mira-brand-card">
            <span className="mira-brand-copy">
              <strong>Media Intelligence &amp; Research Assistant</strong>
            </span>
          </span>
        </Link>
        <div className="mira-sidebar-brand-divider" aria-hidden="true" />
        {!online && (
          <span role="status" className="mira-offline mx-3 rounded-full border border-amber-300/30 bg-amber-300/10 px-3 py-1 text-center text-[10px] font-bold uppercase tracking-wider text-amber-100">
            {t("Offline")}
          </span>
        )}
        <nav className="mira-nav-links" aria-label="Primary navigation">
          {LINKS.map(([href, key]) => {
            const active = path === href || (href !== "/" && path.startsWith(href));
            return (
              <Link
                key={href}
                href={href}
                className={`mira-nav-link ${active ? "is-active" : ""}`}
                title={collapsed ? t(key) : undefined}
                aria-label={t(key)}
                onClick={() => setMobileOpen(false)}
              >
                <span className="mira-nav-icon" aria-hidden="true">
                  {key === "home" ? "⌂" : key === "chat" ? "✦" : key === "news" ? "▤" : key === "live" ? "◉" : key === "podcast" ? "♫" : key === "saved" ? "⌑" : key === "history" ? "◷" : key === "profile" ? "○" : "⚙"}
                </span>
                <span className="mira-nav-label">{t(key)}</span>
              </Link>
            );
          })}
        </nav>
        <div className="mira-account">
          {user && (
            <Link href="/profile" className="mira-profile" aria-label={t("Open my account profile")} onClick={() => setMobileOpen(false)}>
              <span className="mira-avatar">{(user.email || "M").slice(0, 1).toUpperCase()}</span>
              <span className="mira-profile-details min-w-0">
                <strong className="block truncate text-sm">{user.user_metadata?.full_name || t("My account")}</strong>
                <small className="block truncate text-white/50">{user.email || t("Profile")}</small>
              </span>
            </Link>
          )}
          {user ? (
            <button className="mira-nav-link mira-signout" onClick={signOut} title={collapsed ? t("Sign out") : undefined}>
              <span className="mira-nav-icon" aria-hidden="true">↪</span>
              <span className="mira-nav-label">{t("Sign out")}</span>
            </button>
          ) : (
            <Link href="/login" className="mira-nav-link" title={collapsed ? t("Sign in") : undefined} onClick={() => setMobileOpen(false)}>
              <span className="mira-nav-icon" aria-hidden="true">↪</span>
              <span className="mira-nav-label">{t("Sign in")}</span>
            </Link>
          )}
        </div>
        <button
          type="button"
          className="mira-sidebar-toggle"
          aria-label={collapsed ? t("Expand sidebar") : t("Collapse sidebar")}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <img src="/mira-logo.png" alt="" aria-hidden="true" /> : <span aria-hidden="true">‹</span>}
        </button>
        {!collapsed && (
          <div
            className="mira-sidebar-resize"
            role="separator"
            aria-orientation="vertical"
            aria-label={t("Resize sidebar")}
            aria-valuemin={MIN_WIDTH}
            aria-valuemax={MAX_WIDTH}
            aria-valuenow={sidebarWidth}
            tabIndex={0}
            onPointerDown={startResize}
            onPointerMove={resizeSidebar}
            onPointerUp={endResize}
            onPointerCancel={endResize}
            onLostPointerCapture={endResize}
            onKeyDown={resizeWithKeyboard}
          />
        )}
      </aside>
      <button
        type="button"
        className={`mira-mobile-toggle${mobileOpen ? " is-open" : ""}`}
        aria-label={mobileOpen ? t("Close navigation") : t("Open navigation")}
        aria-expanded={mobileOpen}
        onClick={() => setMobileOpen((value) => !value)}
      >
        {mobileOpen ? <span aria-hidden="true">×</span> : <img src="/mira-logo.png" alt="" aria-hidden="true" />}
      </button>
    </>
  );
}
