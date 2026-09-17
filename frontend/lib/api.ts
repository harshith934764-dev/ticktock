export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("ticktock_token");
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options, headers, cache: "no-store",
  });
  const text = await response.text();
  let data: any = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
  if (!response.ok) throw new Error(data.detail || data.message || `Request failed (${response.status})`);
  return data as T;
}

export function saveAuth(data: { access_token?: string; user?: any }) {
  if (data.access_token) localStorage.setItem("ticktock_token", data.access_token);
  if (data.user) localStorage.setItem("ticktock_user", JSON.stringify(data.user));
}
export function logout() {
  localStorage.removeItem("ticktock_token");
  localStorage.removeItem("ticktock_user");
}
