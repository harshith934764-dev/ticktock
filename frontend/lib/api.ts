// Tick Tock API client
// Production Render backend is used automatically when the Next.js
// build-time environment variable is missing.

const PRODUCTION_API = "https://ticktock-neke.onrender.com";

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL || PRODUCTION_API
).replace(/\/$/, "");

async function request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("ticktock_token")
        : null;

    const headers = new Headers(options.headers || {});
    if (
      options.body &&
      !(options.body instanceof FormData) &&
      !headers.has("Content-Type")
    ) {
      headers.set("Content-Type", "application/json");
    }
    if (token) headers.set("Authorization", `Bearer ${token}`);

    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      cache: "no-store",
      signal: controller.signal,
    });

    const text = await response.text();
    let data: any = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }

    if (!response.ok) {
      throw new Error(
        data?.detail || data?.message || `Request failed (${response.status})`
      );
    }

    return data as T;
  } catch (error: any) {
    if (error?.name === "AbortError") {
      throw new Error("Request timed out. Please try again.");
    }
    if (error instanceof TypeError) {
      throw new Error(
        `Cannot reach Tick Tock server (${API_BASE}). Please try again.`
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export const API = API_BASE;
export const api = request;

export async function apiGet<T = any>(path: string) {
  return request<T>(path);
}

export async function apiPost<T = any>(path: string, body: any) {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function saveAuth(data: any) {
  if (typeof window === "undefined") return;
  const token = data?.token || data?.access_token;
  if (token) localStorage.setItem("ticktock_token", token);
  if (data?.user) {
    localStorage.setItem("ticktock_user", JSON.stringify(data.user));
  }
}

export function clearAuth() {
  if (typeof window === "undefined") return;
  localStorage.removeItem("ticktock_token");
  localStorage.removeItem("ticktock_user");
}

export function getStoredUser<T = any>(): T | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("ticktock_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}
