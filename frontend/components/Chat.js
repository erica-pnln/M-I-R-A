"use client";
import { useEffect, useRef, useState } from "react";
import { apiStream } from "@/lib/api";
import { useLanguage } from "@/components/LanguageProvider";

const TRUSTED_IMAGE_HOSTS = [
  "aljazeera.com",
  "assettype.com",
  "bbci.co.uk",
  "bbc.com",
  "dw.com",
  "fbcdn.net",
  "france24.com",
  "gmanews.tv",
  "guim.co.uk",
  "inquirer.net",
  "rappler.com",
  "wixstatic.com",
];

function isTrustedImageUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && TRUSTED_IMAGE_HOSTS.some(
      (host) => url.hostname === host || url.hostname.endsWith(`.${host}`),
    );
  } catch {
    return false;
  }
}

function renderInline(text, keyPrefix, sourceScope, sourceCard = false, t = (value) => value) {
  const pattern = /!\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|\[(S\d+|ARTICLE)\]|(https?:\/\/[^\s<]+)|\*\*(.+?)\*\*|\*(.+?)\*/g;
  const parts = [];
  let cursor = 0;
  let match;
  let index = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) parts.push(text.slice(cursor, match.index));
    if (match[2] && isTrustedImageUrl(match[2])) {
      parts.push(
        <a
          key={`${keyPrefix}-${index}`}
          href={match[2]}
          target="_blank"
          rel="noopener noreferrer"
          className={sourceCard
            ? "block w-full overflow-hidden rounded-lg"
            : "inline-block align-middle"}
        >
          <img
            src={match[2]}
            alt={match[1] || "Source thumbnail"}
            loading="lazy"
            referrerPolicy="no-referrer"
            className={sourceCard
              ? "block aspect-video w-full object-cover"
              : "my-2 block h-24 w-24 rounded border border-white/15 object-cover"}
          />
        </a>,
      );
    } else if (match[4]) {
      parts.push(
        <a
          key={`${keyPrefix}-${index}`}
          href={match[4]}
          target="_blank"
          rel="noopener noreferrer"
          className={sourceCard
            ? "mt-auto block min-w-0 break-words text-sm font-medium leading-snug text-blue-400 underline decoration-blue-400/70 underline-offset-2 hover:text-blue-300 line-clamp-2"
            : "text-blue-400 underline decoration-blue-400/70 underline-offset-2 hover:text-blue-300"}
          title={sourceCard ? match[3] : undefined}
        >
          {match[3]}
        </a>,
      );
    } else if (match[5]) {
      const sourceLabel = match[5] === "ARTICLE" ? t("Article") : match[5].slice(1);
      parts.push(
        <sup key={`${keyPrefix}-${index}`} className="ml-0.5">
          <a
            href={`#source-${sourceScope}-${match[5]}`}
            aria-label={t("Jump to {source}", { source: sourceLabel })}
            title={t("Jump to {source}", { source: sourceLabel })}
            className="text-blue-300 underline underline-offset-2"
          >
            {match[5] === "ARTICLE" ? "A" : match[5].slice(1)}
          </a>
        </sup>,
      );
    } else if (match[6]) {
      const url = match[6];
      const cleanUrl = url.replace(/[.,!?;:]+$/, "");
      parts.push(
        <a
          key={`${keyPrefix}-${index}`}
          href={cleanUrl}
          target="_blank"
          rel="noopener noreferrer"
          className={sourceCard
            ? "mt-auto block min-w-0 break-all text-xs leading-snug text-blue-400 underline decoration-blue-400/70 underline-offset-2 hover:text-blue-300 line-clamp-2"
            : "text-blue-400 underline decoration-blue-400/70 underline-offset-2 hover:text-blue-300"}
        >
          {cleanUrl}
        </a>,
      );
      if (cleanUrl.length < url.length) parts.push(url.slice(cleanUrl.length));
    } else if (match[7]) {
      parts.push(<strong key={`${keyPrefix}-${index}`}>{match[7]}</strong>);
    } else {
      parts.push(<em key={`${keyPrefix}-${index}`}>{match[8]}</em>);
    }
    cursor = pattern.lastIndex;
    index += 1;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

function LocalImagePreview({ file, className = "", t }) {
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => {
    if (!file?.type?.startsWith("image/")) {
      setPreviewUrl("");
      return undefined;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  if (!previewUrl) return null;
  return (
    <img
      src={previewUrl}
      alt={t("Preview of {name}", { name: file.name })}
      className={`h-14 w-16 rounded-lg border border-white/15 object-cover ${className}`}
    />
  );
}

function FormattedMessage({ content, messageIndex, t }) {
  const sourceScope = messageIndex ?? 0;
  const visibleContent = content
    .replace(/<!--MIRA_RESEARCH:[A-Za-z0-9_-]+-->/g, "")
    .trim();
  const isArticleDraft = /\*\*MIRA AI DRAFT\b/i.test(visibleContent);
  const lines = visibleContent.split(/\r?\n/);
  const blocks = [];
  let paragraph = [];
  let list = [];
  let listType = null;

  function flushParagraph() {
    if (paragraph.length) {
      blocks.push(
        <p key={`p-${blocks.length}`} className="my-2 first:mt-0 last:mb-0">
          {paragraph.map((line, index) => (
            <span key={index}>
              {index > 0 && <br />}
              {renderInline(line, `p-${blocks.length}-${index}`, sourceScope, false, t)}
            </span>
          ))}
        </p>,
      );
      paragraph = [];
    }
  }

  function flushList() {
    if (list.length) {
      const List = listType === "ordered" ? "ol" : "ul";
      const sourceList = list.every((item) => /^\[(S\d+|ARTICLE)\]/.test(item));
      blocks.push(
        <List
          key={`list-${blocks.length}`}
          className={sourceList
            ? "my-3 grid grid-cols-1 items-stretch gap-3 pl-0 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
            : `my-2 space-y-1 pl-5 ${listType === "ordered" ? "list-decimal" : "list-disc"}`}
        >
          {list.map((item, index) => {
            const sourceId = item.match(/^\[(S\d+|ARTICLE)\]/)?.[1];
            return (
              <li
                key={index}
                id={sourceId ? `source-${sourceScope}-${sourceId}` : undefined}
                className={sourceList
                  ? "flex aspect-square min-w-0 list-none flex-col gap-2 overflow-hidden rounded-xl border border-white/10 bg-white/[.03] p-3 transition-colors hover:border-mira-blue-light hover:bg-white/[.05]"
                  : ""}
              >
                {renderInline(
                  item,
                  `list-${blocks.length}-${index}`,
                  sourceScope,
                  sourceList,
                  t,
                )}
              </li>
            );
          })}
        </List>,
      );
      list = [];
      listType = null;
    }
  }

  lines.forEach((line) => {
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const Heading = level === 1 ? "h1" : level === 2 ? "h2" : "h3";
      const className = isArticleDraft
        ? level === 1
          ? "mb-2 mt-1 border-b border-amber-100/20 pb-3 font-display text-2xl font-bold leading-tight text-white sm:text-3xl"
          : level === 2
            ? "mb-2 mt-6 text-lg font-semibold text-white/95"
            : "mb-2 mt-4 text-sm font-bold uppercase tracking-wide text-amber-100/80"
        : "mb-1 mt-4 text-sm font-bold first:mt-0";
      blocks.push(
        <Heading key={`h-${blocks.length}`} className={className}>
          {renderInline(heading[2], `h-${blocks.length}`, sourceScope, false, t)}
        </Heading>,
      );
    } else if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushParagraph();
      flushList();
      blocks.push(
        <hr key={`hr-${blocks.length}`} className="my-4 border-white/15" />,
      );
    } else if (bullet || numbered) {
      flushParagraph();
      const nextType = numbered ? "ordered" : "unordered";
      if (listType && listType !== nextType) flushList();
      listType = nextType;
      list.push((numbered || bullet)[1]);
    } else if (list.length && /^\s{2,}\S/.test(line)) {
      list[list.length - 1] += `\n${line.trim()}`;
    } else if (!line.trim()) {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(line);
    }
  });
  flushParagraph();
  flushList();
  return (
    <div className={`leading-relaxed ${isArticleDraft
      ? "rounded-xl border border-amber-100/30 bg-slate-950/80 p-4 text-white/90 shadow-xl shadow-black/20 sm:p-6"
      : ""}`}>
      {blocks}
    </div>
  );
}

/** Reusable chat panel. `endpoint` is /api/chat (general) or /api/ask (article-specific). */
export default function Chat({
  endpoint,
  extra = {},
  intro,
  suggestions = [],
  placeholder,
  initialConversationId = null,
  initialMessages = [],
  projectId = null,
  enableAttachments = false,
  onConversationUpdate,
  fill = false,
}) {
  const { t } = useLanguage();
  const [msgs, setMsgs] = useState(initialMessages);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [conv, setConv] = useState(initialConversationId);
  const [files, setFiles] = useState([]);
  const box = useRef(null);
  const fileInput = useRef(null);

  useEffect(() => { box.current?.scrollTo(0, box.current.scrollHeight); }, [msgs, busy]);

  async function send(text) {
    const attachedFiles = files;
    const imageCount = attachedFiles.filter((file) => file.type.startsWith("image/")).length;
    const q = (text ?? input).trim() || (attachedFiles.length
      ? imageCount
        ? `Please analyze the attached image${imageCount === 1 ? "" : "s"}. Describe what is visible, transcribe readable text, and explain any uncertainty.`
        : "Please analyze this file and help me with it. Infer what kind of help I need from the file and our conversation, and explain any uncertainty."
      : "");
    if (!q || busy) return;
    const next = [...msgs, {
      role: "user",
      content: q,
      attachments: attachedFiles.map((file) => ({
        file,
        name: file.name,
        type: file.type,
      })),
    }];
    setMsgs(next);
    setInput("");
    setFiles([]);
    if (fileInput.current) fileInput.current.value = "";
    setBusy(true);
    let partialReply = "";
    try {
      const messagePayload = next.map(({ role, content }) => ({ role, content }));
      const body = {
        messages: messagePayload,
        conversation_id: conv,
        project_id: endpoint === "/api/chat" ? projectId : undefined,
        mode: endpoint === "/api/chat" ? "auto" : undefined,
        ...extra,
      };
      let url = endpoint;
      let requestBody = body;
      if (enableAttachments && attachedFiles.length) {
        url = "/api/chat/upload";
        requestBody = new FormData();
        requestBody.append("messages", JSON.stringify(messagePayload));
        if (conv) requestBody.append("conversation_id", conv);
        if (projectId) requestBody.append("project_id", projectId);
        requestBody.append("mode", "auto");
        attachedFiles.forEach((file) => requestBody.append("files", file));
      }
      const res = await apiStream(`${url}?stream=true`, {
        body: requestBody,
        onToken: (token) => {
          partialReply += token;
          setMsgs([...next, { role: "assistant", content: partialReply }]);
        },
      });
      setConv(res.conversation_id);
      setMsgs([...next, { role: "assistant", content: res.reply }]);
      onConversationUpdate?.(res.conversation_id);
    } catch (e) {
      const raw = e.message || "The assistant could not respond.";
      const friendly = /timed out|timeout/i.test(raw)
        ? t("The assistant took too long to answer. Please send that again.")
        : t(raw);
      const message = partialReply
        ? `${partialReply}\n\n*${t("The response stopped before it finished: {message}", { message: friendly })}*`
        : t("Sorry, I couldn’t answer: {message}", { message: friendly });
      setMsgs([...next, { role: "assistant", content: message }]);
    } finally { setBusy(false); }
  }

  return (
    <div className={fill ? "flex min-h-0 flex-1 flex-col" : ""}>
      {suggestions.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <button key={s} onClick={() => send(s)} disabled={busy} className="rounded-full border border-white/20 bg-white/[.06] px-3 py-1.5 text-left text-xs leading-snug hover:border-mira-blue-light disabled:opacity-50">{s}</button>
          ))}
        </div>
      )}
      <div ref={box} aria-busy={busy} className={`mb-3 flex flex-col gap-2.5 overflow-y-auto ${fill ? "min-h-0 flex-1" : "max-h-96 min-h-[120px]"}`}>
        {msgs.length === 0 && <div className="max-w-[90%] rounded-2xl border border-white/15 bg-white/[.06] px-4 py-2.5 text-sm">{intro}</div>}
        {msgs.map((m, i) => (
          <div key={i} className={`max-w-[90%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm ${m.role === "user"
            ? "self-end border border-white/20 bg-mira-blue/40"
            : "self-start border border-white/15 bg-white/[.06]"}`}>
            {m.role === "assistant"
              ? <FormattedMessage content={m.content} messageIndex={i} t={t} />
              : m.content}
            {m.attachments?.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2 border-t border-white/15 pt-2">
                {m.attachments.map((file, index) => (
                  <div key={`${file.name}-${index}`} className="flex items-center gap-2 text-xs text-white/65">
                    <LocalImagePreview file={file.file} t={t} />
                    <span className="max-w-40 break-all">{file.name}</span>
                  </div>
                ))}
                <p className="basis-full text-xs text-white/50">{t("Attached for this analysis (not retained)")}</p>
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 self-start rounded-2xl border border-white/15 bg-white/[.06] px-4 py-2.5 text-sm text-white/70"
          >
            <span
              aria-hidden="true"
              className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-white/25 border-t-mira-blue-light"
            />
            <span>
              {msgs[msgs.length - 1]?.role === "assistant"
                ? t("MIRA is responding…")
                : t("MIRA is processing your request…")}
            </span>
          </div>
        )}
      </div>
      {enableAttachments && (
        files.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2" aria-live="polite">
            {files.map((file, index) => (
              <div
                key={`${file.name}-${index}`}
                className="flex max-w-full items-center gap-2 rounded-xl border border-white/15 bg-white/[.04] p-1.5"
              >
                <LocalImagePreview file={file} t={t} />
                <span className="max-w-40 break-all text-xs text-white/75">{file.name}</span>
                <button
                  type="button"
                  className="rounded-full px-2 text-sm text-white/70 hover:bg-white/10"
                  title={t("Remove {name}", { name: file.name })}
                  aria-label={t("Remove {name}", { name: file.name })}
                  onClick={() => setFiles((current) => current.filter((_, fileIndex) => fileIndex !== index))}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )
      )}
      <div className="flex items-end gap-2">
        {enableAttachments && (
          <>
            <input
              ref={fileInput}
              className="hidden"
              type="file"
              multiple
              accept=".pdf,.txt,.md,.jpg,.jpeg,.png,.webp,.mp3,.m4a,.ogg,.wav,.webm,application/pdf,text/plain,text/markdown,image/jpeg,image/png,image/webp,audio/mpeg,audio/mp4,audio/ogg,audio/wav,audio/webm"
              onChange={(event) => setFiles((current) => [...current, ...Array.from(event.target.files || [])].slice(0, 3))}
            />
            <button
              type="button"
              className="btn-ghost flex h-11 w-11 shrink-0 items-center justify-center rounded-full p-0 text-2xl leading-none"
              onClick={() => fileInput.current?.click()}
              disabled={busy}
              aria-label={t("Add a file or image")}
              title={t("Add a file or image")}
            >
              +
            </button>
          </>
        )}
        <textarea
          className="input min-h-11 flex-1 resize-y"
          rows={2}
          value={input}
          placeholder={placeholder}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="btn" onClick={() => send()} disabled={busy || (!input.trim() && !files.length)}>{t("Send")}</button>
      </div>
      {enableAttachments && (
        <p className="mt-2 text-xs text-white/50">
          {t("Uploads are analyzed for this reply and not stored. AI media review can identify clues, not prove authenticity.")}
        </p>
      )}
    </div>
  );
}
