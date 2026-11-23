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

function NavIcon({ name }) {
  const shapes = {
    home: <><path d="m3.5 10 8.5-7 8.5 7-1.5 1.8L12 5.2l-7 6.6Z" fill="currentColor" fillOpacity=".18" stroke="none" /><path d="M5.5 10.1V20h13v-9.9M9 20v-6h6v6" /></>,
    chat: <><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-6.5A7.5 7.5 0 1 1 20 11.5Z" /><path d="M8 11.5h.01M12 11.5h.01M16 11.5h.01" /></>,
    news: <><path d="M4 4.5h15a1 1 0 0 1 1 1v14H5a2 2 0 0 1-2-2v-12a1 1 0 0 1 1-1Z" fill="currentColor" fillOpacity=".13" /><path d="M7 8h3m2 0h4M7 11h9M7 14h9M7 17h5M3 17.5a2 2 0 0 0 2 2" /></>,
    live: <><circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" /><path d="M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8M2.8 2.8a13 13 0 0 0 0 18.4M21.2 2.8a13 13 0 0 1 0 18.4" /></>,
    podcast: <><path d="M9 8V6a3 3 0 0 1 6 0v8a3 3 0 0 1-6 0V8Z" fill="currentColor" fillOpacity=".2" /><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6M7 7l-1.5 1.5M17 7l1.5 1.5" /></>,
    saved: <><path d="M6 4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21l-6-4-6 4V4.5Z" fill="currentColor" fillOpacity=".16" /><path d="m12 7 .9 1.9 2.1.3-1.5 1.5.4 2.1-1.9-1-1.9 1 .4-2.1L9 9.2l2.1-.3L12 7Z" fill="currentColor" fillOpacity=".85" stroke="none" /></>,
    history: <><circle cx="12" cy="12" r="6.2" fill="currentColor" fillOpacity=".14" stroke="none" /><path d="M3.5 11a8.5 8.5 0 1 1 2.3 6.7M3.5 5.5V11h5.5M12 7v5l3 2" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a8 8 0 0 0 .1-6l1.5-1-1.6-2.8-1.4.6a8 8 0 0 0-5.2-3l-.2-1.5h-3.2l-.2 1.5a8 8 0 0 0-5.2 3L2.6 5.2 1 8l1.5 1a8 8 0 0 0 0 6L1 16l1.6 2.8 1.4-.6a8 8 0 0 0 5.2 3l.2 1.5h3.2l.2-1.5a8 8 0 0 0 5.2-3l1.4.6 1.6-2.8-1.5-1Z" /></>,
    signIn: <><path d="M13 5h5a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-5" /><path d="m10 16 4-4-4-4M14 12H3" /></>,
    signOut: <><path d="M11 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h5" /><path d="m14 16-4-4 4-4M10 12h11" /></>,
  };

  return (
    <svg
      aria-hidden="true"
      className="mira-nav-svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
    >
      {shapes[name]}
    </svg>
  );
}

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
          <img src="/mira-logo.png" alt="" aria-hidden="true" className="mira-logo-dark mira-brand-mark" />
          <img src="/mira-logo-light.png" alt="" aria-hidden="true" className="mira-logo-light mira-brand-mark" />
          <span className="mira-brand-card">
            <span className="mira-brand-copy">
              <strong>Media Intelligence &amp;<br />Research Assistant</strong>
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
                className={`mira-nav-link${key === "live" ? " mira-nav-link-live" : ""}${active ? " is-active" : ""}`}
                title={collapsed ? t(key) : undefined}
                aria-label={t(key)}
                onClick={() => setMobileOpen(false)}
              >
                <span className={`mira-nav-icon mira-nav-icon-${key}`} aria-hidden="true">
                  {key === "chat" ? (
                    <img
                      src="/mira-chat.png"
                      alt=""
                      className="mira-chat-nav-icon"
                      aria-hidden="true"
                    />
                  ) : (
                    <NavIcon name={key} />
                  )}
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
              <span className="mira-nav-icon" aria-hidden="true"><NavIcon name="signOut" /></span>
              <span className="mira-nav-label">{t("Sign out")}</span>
            </button>
          ) : (
            <Link href="/login" className="mira-nav-link" title={collapsed ? t("Sign in") : undefined} onClick={() => setMobileOpen(false)}>
              <span className="mira-nav-icon" aria-hidden="true"><NavIcon name="signIn" /></span>
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
          {collapsed ? (
            <>
              <img src="/mira-logo.png" alt="" aria-hidden="true" className="mira-logo-dark" />
              <img src="/mira-logo-light.png" alt="" aria-hidden="true" className="mira-logo-light" />
            </>
          ) : <span aria-hidden="true">‹</span>}
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
        {mobileOpen ? (
          <span aria-hidden="true">×</span>
        ) : (
          <>
            <img src="/mira-logo.png" alt="" aria-hidden="true" className="mira-logo-dark" />
            <img src="/mira-logo-light.png" alt="" aria-hidden="true" className="mira-logo-light" />
          </>
        )}
      </button>
    </>
  );
}
