/** The only module that talks to the network. Same-origin, cookie session, CSRF header on mutations. */

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, any>;
  retryable: boolean;
  requestId?: string;

  constructor(status: number, code: string, message: string, details: Record<string, any> = {}, retryable = false,
              requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.retryable = retryable;
    this.requestId = requestId;
  }

  get fieldErrors(): Record<string, string> {
    return (this.details?.fields as Record<string, string>) ?? {};
  }
}

export const API_BASE = "/api/v1";
const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

type Options = { method?: string; body?: unknown; form?: FormData; timeoutMs?: number; signal?: AbortSignal };

let onUnauthenticated: (() => void) | null = null;
export function setUnauthenticatedHandler(fn: () => void) {
  onUnauthenticated = fn;
}

export async function api<T = any>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (MUTATING.has(method)) headers["X-RoleReady-Client"] = "web";
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? 120_000);
  if (opts.signal) opts.signal.addEventListener("abort", () => controller.abort());
  let res: Response;
  try {
    res = await fetch(API_BASE + path, { method, headers, body, credentials: "include", signal: controller.signal });
  } catch (e) {
    clearTimeout(timer);
    if ((e as Error).name === "AbortError") {
      throw new ApiError(0, "TIMEOUT", "This is taking longer than expected. Your input is saved — try again.", {}, true);
    }
    throw new ApiError(0, "NETWORK", "Can't reach RoleReady. Check your connection and try again.", {}, true);
  }
  clearTimeout(timer);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = data?.error ?? {};
    const apiErr = new ApiError(res.status, err.code ?? `HTTP_${res.status}`, err.message ?? "Something went wrong.",
      err.details ?? {}, Boolean(err.retryable), err.request_id);
    if (res.status === 401 && onUnauthenticated && !path.startsWith("/auth/")) onUnauthenticated();
    throw apiErr;
  }
  if (res.status === 202) return data as T;
  return data as T;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body?: unknown, timeoutMs?: number) =>
  api<T>(p, { method: "POST", body: body ?? {}, timeoutMs });
export const put = <T = any>(p: string, body: unknown) => api<T>(p, { method: "PUT", body });
export const patch = <T = any>(p: string, body: unknown) => api<T>(p, { method: "PATCH", body });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });
export const upload = <T = any>(p: string, form: FormData) => api<T>(p, { method: "POST", form, timeoutMs: 180_000 });

export function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") s.set(k, String(v));
  });
  const str = s.toString();
  return str ? `?${str}` : "";
}
