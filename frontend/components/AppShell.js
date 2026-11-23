"use client";

import { usePathname } from "next/navigation";
import Nav from "@/components/Nav";

const AUTH_ROUTES = ["/login", "/onboarding"];

export default function AppShell({ children }) {
  const pathname = usePathname();
  const isAuthRoute = AUTH_ROUTES.includes(pathname);

  return (
    <div id="app-root">
      {!isAuthRoute && <Nav />}
      <main
        className={`mira-main mx-auto w-full max-w-[1800px] px-4 py-5 sm:px-6 lg:px-8${isAuthRoute ? " mira-main-auth" : ""}`}
      >
        {children}
      </main>
    </div>
  );
}
