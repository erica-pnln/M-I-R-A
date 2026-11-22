"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Chat from "@/components/Chat";
import { api } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { useLanguage } from "@/components/LanguageProvider";

function WelcomeIntroduction({ onClose, replayKey, t }) {
  return (
    <div className="research-welcome-backdrop">
      <section
        className="research-welcome-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="research-welcome-title"
      >
        <div className="research-welcome-copy">
          <p className="label">{t("Your research companion")}</p>
          <h2 id="research-welcome-title" className="research-welcome-title">
            Hello, I&apos;m <span className="research-welcome-name">MIRA!</span>
          </h2>
          <p className="research-welcome-description">
            {t("I’m here to help you explore stories, verify information, and shape your ideas into thoughtful journalism. Ask a question, follow a lead, or start with a blank page—we’ll work through it together.")}
          </p>
          <button type="button" className="btn" onClick={onClose}>
            {t("Skip Introduction")}
          </button>
        </div>
        <div className="research-welcome-video-frame">
          <video
            key={replayKey}
            className="research-welcome-video"
            src="/video/mirachat%20welcome%20video.mp4"
            autoPlay
            muted
            controls
            playsInline
            preload="metadata"
            loop
            aria-label={t("MIRA welcome introduction video")}
          />
        </div>
      </section>
    </div>
  );
}

export default function ChatPage() {
  const { language, t } = useLanguage();
  const [user, setUser] = useState(null);
  const [welcomeChecked, setWelcomeChecked] = useState(false);
  const [showWelcome, setShowWelcome] = useState(false);
  const [welcomeIsFirst, setWelcomeIsFirst] = useState(false);
  const [welcomeError, setWelcomeError] = useState("");
  const [replayKey, setReplayKey] = useState(0);
  const closingWelcome = useRef(false);
  const [projects, setProjects] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatKey, setChatKey] = useState(0);
  const [projectTitle, setProjectTitle] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);
  const [sidebarError, setSidebarError] = useState("");
  const [historyAvailable, setHistoryAvailable] = useState(true);
  const [projectSetupNeeded, setProjectSetupNeeded] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(false);
  const actionsRef = useRef(null);

  useEffect(() => {
    if (!actionsOpen && !historyOpen && !projectsOpen) return undefined;
    function handlePointerDown(event) {
      if (!actionsRef.current?.contains(event.target)) {
        setActionsOpen(false);
        setHistoryOpen(false);
        setProjectsOpen(false);
      }
    }
    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setActionsOpen(false);
        setHistoryOpen(false);
        setProjectsOpen(false);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [actionsOpen, historyOpen, projectsOpen]);

  useEffect(() => {
    if (!supabase) {
      setWelcomeChecked(true);
      return undefined;
    }

    let active = true;
    supabase.auth.getSession().then(({ data, error }) => {
      if (!active) return;
      if (error) {
        console.error("Could not restore the MIRA session for the welcome experience:", error);
        setWelcomeError(t("Could not check your introduction status. You can still use Research Desk."));
      }
      setUser(data?.session?.user || null);
      setWelcomeChecked(true);
    }).catch((error) => {
      if (!active) return;
      console.error("Could not restore the MIRA session for the welcome experience:", error);
      setWelcomeError(t("Could not check your introduction status. You can still use Research Desk."));
      setWelcomeChecked(true);
    });

    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user || null);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, [t]);

  useEffect(() => {
    if (!welcomeChecked) return;
    if (!user || !supabase) {
      setWelcomeIsFirst(false);
      setShowWelcome(false);
      setWelcomeError("");
      return;
    }

    closingWelcome.current = false;
    setWelcomeError("");
    const isFirstVisit = user.user_metadata?.mira_welcome_completed === false;
    setWelcomeIsFirst(isFirstVisit);
    setShowWelcome(isFirstVisit);
  }, [user?.id, welcomeChecked, t]);

  function replayWelcome() {
    closingWelcome.current = false;
    setReplayKey((key) => key + 1);
    setShowWelcome(true);
  }

  function closeWelcome() {
    if (closingWelcome.current) return;
    closingWelcome.current = true;
    setShowWelcome(false);
    if (!welcomeIsFirst || !user || !supabase) return;

    supabase.auth
      .updateUser({ data: { mira_welcome_completed: true } })
      .then(({ data, error }) => {
        if (error) throw error;
        if (!data.user) throw new Error(t("Your introduction status could not be saved to your profile."));
        setWelcomeIsFirst(false);
      })
      .catch((error) => {
        console.error("Could not save the MIRA welcome status:", error);
        setWelcomeError(t("Could not save your introduction status: {message}", { message: error.message }));
      });
  }

  const refreshSidebar = useCallback(async () => {
    const [projectResult, conversationResult] = await Promise.allSettled([
      api("/api/projects"),
      api("/api/conversations"),
    ]);
    if (conversationResult.status === "fulfilled") {
      setConversations(conversationResult.value.conversations || []);
      setHistoryAvailable(true);
      setSidebarError("");
    } else {
      const error = conversationResult.reason;
      if (error.status === 401) {
        setHistoryAvailable(false);
      } else {
        setSidebarError(t("Couldn’t load chat history: {message}", { message: t(error.message) }));
      }
    }
    if (projectResult.status === "fulfilled") {
      setProjects(projectResult.value.projects || []);
      setProjectSetupNeeded(false);
    } else {
      const error = projectResult.reason;
      if (error.status === 401) {
        setHistoryAvailable(false);
      } else if (
        error.status === 503
        && /Chat projects are not set up in Supabase|20261111_chat_projects\.sql/i.test(error.message)
      ) {
        setProjects([]);
        setProjectSetupNeeded(true);
      } else {
        setProjects([]);
        setProjectSetupNeeded(false);
        setSidebarError(t("Couldn’t load projects: {message}", { message: t(error.message) }));
      }
    }
  }, [t]);

  useEffect(() => {
    refreshSidebar();
  }, [refreshSidebar]);

  function startNewChat(projectId = activeProjectId) {
    setActiveProjectId(projectId);
    setSelectedConversation(null);
    setChatMessages([]);
    setChatKey((key) => key + 1);
  }

  async function createProject(event) {
    event.preventDefault();
    const title = projectTitle.trim();
    if (!title) return;
    try {
      const result = await api("/api/projects", {
        method: "POST",
        body: { title },
      });
      setProjects((current) => [result.project, ...current]);
      setProjectTitle("");
      setCreatingProject(false);
      startNewChat(result.project.id);
    } catch (error) {
      setSidebarError(t("Couldn’t create project: {message}", { message: t(error.message) }));
    }
  }

  async function openConversation(conversation) {
    try {
      const result = await api(`/api/conversations/${conversation.id}`);
      setSelectedConversation(result.conversation);
      setActiveProjectId(result.conversation.project_id || null);
      setChatMessages((result.messages || []).map(({ role, content }) => ({ role, content })));
      setChatKey((key) => key + 1);
    } catch (error) {
      setSidebarError(t("Couldn’t open this chat: {message}", { message: t(error.message) }));
    }
  }

  const activeProject = projects.find((project) => project.id === activeProjectId);
  const dateLocale = language === "fil" ? "fil-PH" : language === "ceb" ? "ceb-PH" : "en-US";

  return (
    <>
    <div className="research-desk-layout grid min-h-[36rem] grid-rows-[minmax(0,1fr)] gap-4">
      <section className="glass flex min-h-0 min-w-0 flex-col overflow-hidden p-4 sm:p-6">
        {welcomeError && (
          <p role="alert" className="mb-3 rounded-xl border border-amber-300/30 bg-amber-950/30 p-3 text-sm text-amber-100">
            {welcomeError}
          </p>
        )}
        {sidebarError && (
          <p role="alert" className="mb-3 rounded-xl border border-red-400/30 bg-red-950/30 p-3 text-sm text-red-200">
            {sidebarError}
          </p>
        )}
        <header className="relative mb-4 flex flex-col gap-3 border-b border-white/10 pb-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1 pl-14">
            <div className="research-header-intro flex min-w-0 items-center gap-3 sm:gap-4">
              <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl border border-mira-blue-light/20 bg-white/[.04] p-1 sm:h-16 sm:w-16">
                <img
                  src="/mira-chat.png"
                  alt="MIRA Chat AI"
                  className="h-full w-full object-contain"
                />
              </div>
              <div className="min-w-0">
                <h1 className="font-display text-2xl font-bold tracking-tight text-white sm:text-3xl">
                  {t("MIRA Chat")}
                </h1>
                <p className="mt-0.5 text-sm font-medium text-mira-blue-light sm:text-base">
                  {t("Your companion in research, discovery, and journalism.")}
                </p>
                {(selectedConversation || activeProject) && (
                  <p className="mt-2 max-w-3xl truncate text-xs text-white/40">
                    {selectedConversation?.title || activeProject?.title}
                  </p>
                )}
              </div>
            </div>
          </div>
          <button type="button" className="btn-ghost shrink-0 self-start" onClick={replayWelcome}>
            {t("Watch Introduction")}
          </button>
          <div className="absolute left-0 top-0 z-30" ref={actionsRef}>
            <button
              type="button"
              className="group grid h-11 w-11 place-items-center rounded-2xl border border-mira-blue-light/35 bg-gradient-to-br from-mira-blue/35 via-[#111a2b] to-[#0b1220] text-mira-blue-light transition-all duration-200 hover:-translate-y-0.5 hover:border-mira-blue-light/70 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mira-blue-light"
              aria-label={t("Research Desk actions")}
              aria-haspopup="menu"
              aria-expanded={actionsOpen}
              onClick={() => {
                setHistoryOpen(false);
                setProjectsOpen(false);
                setActionsOpen((open) => !open);
              }}
            >
              <span aria-hidden="true" className="text-xl font-bold leading-none tracking-[0.08em] transition-transform group-hover:scale-110">⋯</span>
            </button>
            <div
              role="menu"
              aria-label={t("Research Desk actions")}
              className={`absolute left-0 top-full z-30 mt-2 w-52 origin-top-left rounded-xl border border-white/10 bg-[#101827] p-1.5 shadow-2xl transition duration-200 ease-out ${actionsOpen ? "visible translate-y-0 opacity-100" : "invisible pointer-events-none -translate-y-1 opacity-0"}`}
            >
              <button
                type="button"
                role="menuitem"
                className="w-full rounded-lg px-3 py-2.5 text-left text-sm text-white/85 transition-colors hover:bg-white/[.08] hover:text-white"
                onClick={() => {
                  startNewChat();
                  setActionsOpen(false);
                  setHistoryOpen(false);
                  setProjectsOpen(false);
                }}
              >
                {t("New chat")}
              </button>
              <button
                type="button"
                role="menuitem"
                className="w-full rounded-lg px-3 py-2.5 text-left text-sm text-white/85 transition-colors hover:bg-white/[.08] hover:text-white"
                onClick={() => {
                  setActionsOpen(false);
                  setHistoryOpen(false);
                  setProjectsOpen((open) => !open);
                }}
              >
                {t("Projects")}
              </button>
              <button
                type="button"
                role="menuitem"
                className="w-full rounded-lg px-3 py-2.5 text-left text-sm text-white/85 transition-colors hover:bg-white/[.08] hover:text-white disabled:cursor-not-allowed disabled:opacity-45"
                disabled={!historyAvailable || projectSetupNeeded}
                onClick={() => {
                  setCreatingProject(true);
                  setActionsOpen(false);
                  setHistoryOpen(false);
                  setProjectsOpen(true);
                }}
              >
                {t("Create project")}
              </button>
              <button
                type="button"
                role="menuitem"
                className="w-full rounded-lg px-3 py-2.5 text-left text-sm text-white/85 transition-colors hover:bg-white/[.08] hover:text-white"
                onClick={() => {
                  setActionsOpen(false);
                  setProjectsOpen(false);
                  setHistoryOpen((open) => !open);
                }}
              >
                {t("Chat history")}
              </button>
            </div>
            <section
              aria-label={t("Chat history")}
              aria-hidden={!historyOpen}
              className={`absolute left-0 top-full z-20 mt-2 flex max-h-[min(70dvh,34rem)] w-[min(24rem,calc(100vw-2rem))] origin-top-left flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0c1422] shadow-2xl transition duration-200 ease-out ${historyOpen ? "visible translate-y-0 opacity-100" : "invisible pointer-events-none -translate-y-1 opacity-0"}`}
            >
              <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
                <h2 className="font-semibold">{t("Chat history")}</h2>
                <span className="text-xs text-white/45">{conversations.length}</span>
              </div>
              <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
                {conversations.map((conversation) => {
                  const date = conversation.created_at ? new Date(conversation.created_at) : null;
                  const timestamp = date && !Number.isNaN(date.getTime())
                    ? date.toLocaleString(dateLocale, { dateStyle: "medium", timeStyle: "short" })
                    : "";
                  return (
                    <button
                      key={conversation.id}
                      type="button"
                      className={`w-full rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-white/[.07] ${selectedConversation?.id === conversation.id ? "bg-mira-blue/25 text-white" : "text-white/75"}`}
                      onClick={() => {
                        openConversation(conversation);
                        setHistoryOpen(false);
                      }}
                    >
                      <span className="block truncate text-sm">{conversation.title || t("New chat")}</span>
                      {timestamp && <time className="mt-1 block text-xs text-white/45">{timestamp}</time>}
                    </button>
                  );
                })}
                {!conversations.length && historyAvailable && (
                  <p className="px-3 py-4 text-sm text-white/50">{t("Your saved chats will appear here.")}</p>
                )}
                {!historyAvailable && (
                  <p className="px-3 py-4 text-sm text-white/50">{t("Sign in to save chat history and create research projects.")}</p>
                )}
              </div>
            </section>
            <section
              aria-label={t("Projects")}
              aria-hidden={!projectsOpen}
              className={`absolute left-0 top-full z-20 mt-2 flex max-h-[min(70dvh,34rem)] w-[min(24rem,calc(100vw-2rem))] origin-top-left flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0c1422] shadow-2xl transition duration-200 ease-out ${projectsOpen ? "visible translate-y-0 opacity-100" : "invisible pointer-events-none -translate-y-1 opacity-0"}`}
            >
              <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
                <h2 className="font-semibold">{t("Projects")}</h2>
                <span className="text-xs text-white/45">{projects.length}</span>
              </div>
              <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
                <button
                  type="button"
                  className={`w-full rounded-lg px-3 py-2.5 text-left text-sm transition-colors hover:bg-white/[.07] ${!activeProjectId ? "bg-white/10 text-white" : "text-white/75"}`}
                  onClick={() => {
                    startNewChat(null);
                    setProjectsOpen(false);
                  }}
                >
                  {t("All chats")}
                </button>
                {projects.map((project) => (
                  <button
                    key={project.id}
                    type="button"
                    className={`w-full truncate rounded-lg px-3 py-2.5 text-left text-sm transition-colors hover:bg-white/[.07] ${activeProjectId === project.id ? "bg-white/10 text-white" : "text-white/75"}`}
                    onClick={() => {
                      startNewChat(project.id);
                      setProjectsOpen(false);
                    }}
                    title={project.title}
                  >
                    {project.title}
                  </button>
                ))}
                {creatingProject && (
                  <form onSubmit={createProject} className="my-2 flex flex-col gap-2 rounded-xl border border-white/10 bg-black/20 p-3">
                    <label htmlFor="project-title" className="text-xs font-semibold text-white/70">
                      {t("Project name")}
                    </label>
                    <input
                      id="project-title"
                      className="input"
                      value={projectTitle}
                      maxLength={80}
                      onChange={(event) => setProjectTitle(event.target.value)}
                      placeholder={t("e.g. Local water access study")}
                      autoFocus
                    />
                    <div className="flex gap-2">
                      <button type="submit" className="btn flex-1" disabled={!projectTitle.trim()}>{t("Create")}</button>
                      <button type="button" className="btn-ghost" onClick={() => setCreatingProject(false)}>{t("Cancel")}</button>
                    </div>
                  </form>
                )}
                {projectSetupNeeded && historyAvailable && (
                  <p className="rounded-xl border border-amber-300/25 bg-amber-400/10 px-3 py-2 text-xs leading-relaxed text-amber-100">
                    {t("Projects are unavailable until the database update in {path} is applied in the Supabase SQL Editor. Chat still works.", {
                      path: "supabase/migrations/20261111_chat_projects.sql",
                    })}
                  </p>
                )}
                {!projects.length && historyAvailable && !projectSetupNeeded && (
                  <p className="px-3 py-2 text-xs text-white/45">{t("Create a project to group related research chats.")}</p>
                )}
                {!historyAvailable && (
                  <p className="px-3 py-2 text-xs text-white/55">
                    {t("Sign in to save chat history and create research projects.")}
                  </p>
                )}
              </div>
            </section>
          </div>
        </header>
        <Chat
          key={chatKey}
          endpoint="/api/chat"
          projectId={activeProjectId}
          initialConversationId={selectedConversation?.id || null}
          initialMessages={chatMessages}
          enableAttachments
          fill
          onConversationUpdate={refreshSidebar}
          intro={t("Hi, I’m MIRA. Ask me about current events or journalism, request a newspaper-style article draft, or attach an image for analysis. For factual claims, I’ll provide relevant source links when available.")}
          placeholder={t("Ask a question, request an article, paste a draft, or attach an image…")}
          suggestions={[
            "How do I verify a viral claim?",
            "Help me outline a feature story",
            "Draft a newspaper-style article about a topic using verified facts and sources",
            "Explain the inverted pyramid",
          ].map((suggestion) => t(suggestion))}
        />
      </section>
    </div>
    {showWelcome && welcomeChecked && (
      <WelcomeIntroduction onClose={closeWelcome} replayKey={replayKey} t={t} />
    )}
    </>
  );
}
