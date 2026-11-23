"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

export default function ActivityIndicator() {
  const pathname = usePathname();
  const [active, setActive] = useState(false);
  const timeoutRef = useRef(null);

  const show = (duration = 900) => {
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    setActive(true);
    timeoutRef.current = window.setTimeout(() => setActive(false), duration);
  };

  useEffect(() => {
    setActive(false);
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
  }, [pathname]);

  useEffect(() => {
    function onClick(event) {
      const target = event.target instanceof Element ? event.target : null;
      if (!target) return;

      const link = target.closest("a[href]");
      const loadingControl = target.closest("[data-loading]");
      const button = target.closest("button");

      if (link) {
        const href = link.getAttribute("href") || "";
        if (href.startsWith("/") || href.startsWith("#")) show(1200);
      } else if (loadingControl) {
        show(Number(loadingControl.getAttribute("data-loading-duration")) || 1500);
      } else if (button?.type === "submit") {
        show(1200);
      }
    }

    function onSubmit(event) {
      const form = event.target;
      if (form instanceof HTMLFormElement) show(1500);
    }

    document.addEventListener("click", onClick, true);
    document.addEventListener("submit", onSubmit, true);
    return () => {
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("submit", onSubmit, true);
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    };
  }, []);

  return active ? (
    <div className="mira-activity-overlay" role="status" aria-live="polite" aria-label="Loading">
      <div className="mira-loading-spinner" aria-hidden="true" />
      <span>Loading…</span>
    </div>
  ) : null;
}
