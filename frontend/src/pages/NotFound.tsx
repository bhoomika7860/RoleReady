import { LinkButton } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="max-w-md mx-auto py-16 text-center space-y-3">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-ink-muted text-sm">That page doesn't exist or has moved.</p>
      <LinkButton to="/app/dashboard">Go to dashboard</LinkButton>
    </div>
  );
}
