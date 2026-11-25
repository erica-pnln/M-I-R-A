import { supabase } from "./supabase";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function getOptionalSession() {
  try {
    const result = await supabase.auth.getSession();
    if (result.error) {
      console.warn("Could not read the optional Supabase session for this API request.", result.error);
      return null;
    }
    return result.data.session;
  } catch (error) {
    console.warn("Could not read the optional Supabase session for this API request.", error);
    return null;
  }
}

export async function api(path, { method = "GET", body } = {}) {
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  const headers = body !== undefined && !isFormData ? { "Content-Type": "application/json" } : {};
  if (supabase) {
    const data = { session: await getOptionalSession() };
    if (data.session) headers.Authorization = `Bearer ${data.session.access_token}`;
  }
  let res;
  const maxNetworkRetries = method === "GET" ? 2 : 0;
  for (let attempt = 0; ; attempt += 1) {
    try {
      res = await fetch(API_BASE + path, {
        method,
        headers,
        body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
      });
      break;
    } catch (error) {
      if (!(error instanceof TypeError)) throw error;
      if (attempt >= maxNetworkRetries) {
        throw new Error(`Couldn’t reach the MIRA API at ${API_BASE}. Verify the API URL, backend listener, and CORS_ORIGINS setting.`);
      }
      await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
    }
  }
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    const detail = payload.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || JSON.stringify(item)).join("; ")
      : typeof detail === "string" ? detail : `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function apiStream(path, { body, onToken, onStatus } = {}) {
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  const headers = body !== undefined && !isFormData ? { "Content-Type": "application/json" } : {};
  if (supabase) {
    const data = { session: await getOptionalSession() };
    if (data.session) headers.Authorization = `Bearer ${data.session.access_token}`;
  }

  let res;
  try {
    res = await fetch(API_BASE + path, {
      method: "POST",
      headers,
      body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(`Couldn’t reach the MIRA API at ${API_BASE}. Verify the API URL, backend listener, and CORS_ORIGINS setting.`);
    }
    throw error;
  }

  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    const detail = payload.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || JSON.stringify(item)).join("; ")
      : typeof detail === "string" ? detail : `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }
  if (!res.body) throw new Error("The MIRA API did not return a readable response stream.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;

  function readEvent(block) {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;

    const event = JSON.parse(data);
    if (event.type === "token") {
      onToken?.(event.text);
    } else if (event.type === "status") {
      onStatus?.(event.text);
    } else if (event.type === "error") {
      throw new Error(event.message || "The assistant could not complete its response.");
    } else if (event.type === "done") {
      result = event;
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        readEvent(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    if (buffer.trim()) readEvent(buffer);
  } finally {
    reader.releaseLock();
  }

  if (!result) throw new Error("The assistant stream ended before the response was complete.");
  return result;
}
