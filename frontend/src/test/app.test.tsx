import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";
import { ScoreTile, ToastProvider } from "@/components/ui";
import { wordDiff } from "@/lib/diff";
import Login, { loginSchema } from "@/pages/Login";
import { cleanContent, emptyContent, validateContent } from "@/pages/resume/ResumeEditor";

function wrap(ui: ReactNode, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}><ToastProvider>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </ToastProvider></QueryClientProvider>,
  );
}

function mockFetch(handler: (url: string, init?: RequestInit) => { status: number; body?: unknown }) {
  const fn = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const { status, body } = handler(String(url), init);
    return new Response(body === undefined ? null : JSON.stringify(body), { status,
      headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("login validation", () => {
  it("accepts usernames and emails, rejects malformed identifiers", () => {
    for (const ok of ["priya.s", "riya_k", "Priya@Example.com", "a1b"]) expect(loginSchema.safeParse({ identifier: ok }).success).toBe(true);
    for (const bad of ["", "  ", "ab", "has space", "x@y", "a..b@example.com", "-start"]) {
      expect(loginSchema.safeParse({ identifier: bad }).success).toBe(false);
    }
  });

  it("shows inline errors without calling the server for an invalid identifier", async () => {
    const fetchFn = mockFetch(() => ({ status: 401, body: { error: { code: "UNAUTHENTICATED", message: "x" } } }));
    wrap(<Login />, "/login");
    await userEvent.type(screen.getByLabelText(/username or email/i), "a b");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/usernames are 3–32 characters/i);
    expect(fetchFn.mock.calls.filter(([u]) => String(u).includes("/auth/login"))).toHaveLength(0);
  });

  it("posts the identifier with the CSRF header and shows server errors", async () => {
    const fetchFn = mockFetch((url) => url.includes("/auth/login")
      ? { status: 429, body: { error: { code: "RATE_LIMITED", message: "Too many attempts. Try again in 30 s." } } }
      : { status: 401, body: { error: { code: "UNAUTHENTICATED", message: "x" } } });
    wrap(<Login />, "/login");
    await userEvent.type(screen.getByLabelText(/username or email/i), "priya@example.com");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByText(/too many attempts/i)).toBeInTheDocument();
    const call = fetchFn.mock.calls.find(([u]) => String(u).includes("/auth/login"))!;
    const init = call[1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-RoleReady-Client"]).toBe("web");
    expect(JSON.parse(String(init.body))).toEqual({ identifier: "priya@example.com" });
    expect(init.credentials).toBe("include");
  });
});

describe("route protection", () => {
  it("redirects unauthenticated visitors from /app pages to login, keeping the destination", async () => {
    mockFetch(() => ({ status: 401, body: { error: { code: "UNAUTHENTICATED", message: "Please log in." } } }));
    wrap(<Routes><Route path="*" element={<App />} /></Routes>, "/app/plan");
    expect(await screen.findByRole("heading", { name: /log in to roleready/i })).toBeInTheDocument();
  });

  it("sends users who haven't finished onboarding to the onboarding flow", async () => {
    mockFetch((url) => url.includes("/auth/me")
      ? { status: 200, body: { user: { id: "u1", identifier: "riya", identifier_kind: "username", preferred_name: "Riya",
        experience_level: null, timezone: "Asia/Kolkata", onboarding_step: 1, onboarding_completed: false, is_demo: false },
        active_target_id: null, auth_mode: "demo_identifier" } }
      : { status: 404, body: { error: { code: "NOT_FOUND", message: "x" } } });
    wrap(<Routes><Route path="*" element={<App />} /></Routes>, "/app/dashboard");
    await waitFor(() => expect(screen.getByRole("heading", { name: /set up your preparation/i })).toBeInTheDocument());
  });
});

describe("honest score display", () => {
  it("never shows a zero when there is no evidence", () => {
    wrap(<ScoreTile name="Interview communication" score={null} confidence="none" />);
    expect(screen.getByText(/not enough evidence yet/i)).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});

describe("rewrite diff", () => {
  it("marks added and removed words", () => {
    const parts = wordDiff("Made backend using FastAPI", "Built backend using FastAPI and PostgreSQL");
    expect(parts.filter((p) => p.type === "del").map((p) => p.text.trim())).toContain("Made");
    expect(parts.filter((p) => p.type === "add").map((p) => p.text).join("")).toMatch(/Built.*PostgreSQL/s);
  });
});

describe("resume editor validation", () => {
  it("requires a name and at least one entry, and normalises empty strings", () => {
    const c = emptyContent("");
    expect(validateContent(c)).toEqual(expect.arrayContaining([expect.stringMatching(/name/i), expect.stringMatching(/at least one/i)]));
    c.header.full_name = "Riya";
    c.projects.push({ name: "Portfolio", technologies: ["React"], bullets: [{ text: "Built a site" }, { text: "  " }] });
    expect(validateContent(c)).toEqual(["Remove empty bullets."]);
    const cleaned = cleanContent(c);
    expect(cleaned.projects[0].bullets).toHaveLength(1);
    expect(cleaned.header.email).toBeNull();
  });
});
