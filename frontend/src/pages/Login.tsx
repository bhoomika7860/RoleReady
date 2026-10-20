import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, Info } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "@/api/client";
import { Logo } from "@/components/AppShell";
import { Button, Field, Input, Notice } from "@/components/ui";
import { useLogin, useSession } from "@/hooks/session";
import { errorMessage } from "@/lib/errors";

const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/;
const USERNAME = /^[a-z0-9](?:[a-z0-9._-]{1,30})[a-z0-9]$/i;

export const loginSchema = z.object({
  identifier: z.string().trim().min(1, "Enter a username or email address.").superRefine((v, ctx) => {
    if (v.includes("@")) {
      if (!EMAIL.test(v) || v.includes("..") || v.length > 254) {
        ctx.addIssue({ code: "custom", message: "That doesn't look like a valid email address." });
      }
    } else if (!USERNAME.test(v) || v.includes("..")) {
      ctx.addIssue({ code: "custom", message: "Usernames are 3–32 characters: letters, numbers, dots, dashes or underscores." });
    }
  }),
});

function safeNext(next: string | null): string | null {
  return next && next.startsWith("/app") && !next.startsWith("//") ? next : null;
}

export default function Login() {
  const { data: me } = useSession();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const login = useLogin();
  const { register, handleSubmit, setError, formState: { errors } } = useForm<{ identifier: string }>({
    resolver: zodResolver(loginSchema), defaultValues: { identifier: "" },
  });
  const next = safeNext(params.get("next"));
  if (me && !login.isPending) return <Navigate to={next ?? "/app/dashboard"} replace />;

  const onSubmit = handleSubmit(async ({ identifier }) => {
    try {
      const out = await login.mutateAsync(identifier.trim());
      nav(out.user.onboarding_completed ? next ?? out.redirect_to : out.redirect_to, { replace: true });
    } catch (e) {
      const field = e instanceof ApiError ? e.fieldErrors.identifier : undefined;
      setError("identifier", { message: field ?? errorMessage(e) });
    }
  });

  return (
    <div className="min-h-screen bg-canvas flex flex-col">
      <header className="px-4 sm:px-6 h-16 flex items-center"><Link to="/"><Logo /></Link></header>
      <main className="flex-1 flex items-start sm:items-center justify-center px-4 pb-10">
        <div className="w-full max-w-[420px]">
          <div className="card p-6 sm:p-7">
            <h1 className="text-xl font-semibold">Log in to RoleReady</h1>
            <p className="text-sm text-ink-muted mt-1">Enter a username or email to open your preparation workspace. New
              identifiers create a new account.</p>
            <form onSubmit={onSubmit} noValidate className="mt-5 space-y-4">
              <Field label="Username or email" htmlFor="identifier" error={errors.identifier?.message}
                hint="Example: priya.s or priya@example.com">
                <Input id="identifier" autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus
                  invalid={!!errors.identifier} aria-describedby={errors.identifier ? "identifier-error" : undefined}
                  {...register("identifier")} />
              </Field>
              <Button type="submit" className="w-full" size="lg" loading={login.isPending} icon={!login.isPending && <ArrowRight className="h-4 w-4" />}>
                {login.isPending ? "Signing you in…" : "Continue"}
              </Button>
            </form>
          </div>
          <Notice tone="warn" className="mt-4" title="Demo-only login">
            No password or verification: anyone who enters the same identifier opens the same account. Use a username you
            make up and avoid sensitive personal information.
          </Notice>
          <p className="mt-4 text-xs text-ink-subtle flex gap-1.5"><Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            Sessions use a secure, HTTP-only cookie and expire after 7 days of inactivity.</p>
        </div>
      </main>
    </div>
  );
}
