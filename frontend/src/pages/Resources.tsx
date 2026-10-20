import { useQuery } from "@tanstack/react-query";
import { BookOpen, ExternalLink, Search } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { get, qs } from "@/api/client";
import type { ResourceItem } from "@/api/types";
import { Badge, Button, EmptyState, ErrorState, Input, PageHeader, PageSkeleton, Select } from "@/components/ui";
import { useActiveTargetId } from "@/hooks/session";
import { fmtDate } from "@/lib/format";

export default function ResourcesPage() {
  const tid = useActiveTargetId();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const filters = { skill: params.get("skill") ?? "", difficulty: params.get("difficulty") ?? "", format: params.get("format") ?? "",
    free: params.get("free") ?? "", q: params.get("q") ?? "", page: Number(params.get("page") ?? 1) };
  const skills = useQuery({ queryKey: ["skills"], queryFn: () => get<{ slug: string; name: string }[]>("/skills"), staleTime: Infinity });
  const q = useQuery({ queryKey: ["resources", tid, filters], queryFn: () => get<{ items: ResourceItem[]; total: number; page: number;
    page_size: number; hidden_unverified: number }>(`/resources${qs({ ...filters, target_id: tid, page_size: 20 })}`) });
  const setF = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); n.delete("page"); setParams(n); };

  return (
    <div className="space-y-5">
      <PageHeader title="Learning resources" subtitle="A curated, link-checked library. Resources linked to your open gaps come first." />
      <form className="card p-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5" onSubmit={(e) => { e.preventDefault(); setF("q", search); }} role="search">
        <div className="relative lg:col-span-2">
          <Search className="h-4 w-4 absolute left-3 top-3 text-ink-subtle" aria-hidden />
          <Input className="pl-9" placeholder="Search title or provider" value={search} aria-label="Search resources" onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Select aria-label="Skill" value={filters.skill} onChange={(e) => setF("skill", e.target.value)}>
          <option value="">All skills</option>{skills.data?.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
        </Select>
        <Select aria-label="Difficulty" value={filters.difficulty} onChange={(e) => setF("difficulty", e.target.value)}>
          <option value="">Any level</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option>
        </Select>
        <Select aria-label="Format" value={filters.format} onChange={(e) => setF("format", e.target.value)}>
          <option value="">Any format</option>{["doc", "article", "video", "course", "interactive", "notes"].map((f) => <option key={f} value={f}>{f}</option>)}
        </Select>
      </form>
      {q.isLoading ? <PageSkeleton /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
        <>
          <p className="text-xs text-ink-subtle">{q.data!.total} resource{q.data!.total === 1 ? "" : "s"}
            {q.data!.hidden_unverified ? ` · ${q.data!.hidden_unverified} hidden because their links couldn't be verified` : ""}</p>
          {q.data!.items.length === 0 ? <EmptyState title="No resources match" icon={<BookOpen className="h-5 w-5" />}>Try clearing a filter.</EmptyState> : (
            <ul className="grid gap-3 md:grid-cols-2">
              {q.data!.items.map((r) => (
                <li key={r.id} className="card p-4 flex flex-col gap-2">
                  <div className="flex items-start justify-between gap-2">
                    <a href={r.url} target="_blank" rel="noopener noreferrer" className="font-medium text-[15px] hover:text-brand-800 inline-flex gap-1.5">
                      {r.title}<ExternalLink className="h-3.5 w-3.5 mt-1 shrink-0" aria-label="(opens in a new tab)" /></a>
                    {r.relevance > 0 && <Badge tone="brand">For your gaps</Badge>}
                  </div>
                  <p className="text-sm text-ink-muted">{r.description}</p>
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    <Badge>{r.provider}</Badge><Badge tone="neutral">{r.format}</Badge><Badge tone="neutral">{r.difficulty}</Badge>
                    <Badge tone="neutral">~{r.minutes} min</Badge>{r.is_free ? <Badge tone="ok">Free</Badge> : <Badge tone="warn">Paid</Badge>}
                  </div>
                  <div className="flex flex-wrap gap-1">{r.skills.map((s) => <button key={s.slug} onClick={() => setF("skill", s.slug)}
                    className="text-xs text-brand-800 hover:underline">{s.name}{s.topic ? ` · ${s.topic}` : ""}</button>)}</div>
                  <p className="text-[11px] text-ink-subtle">Link checked {fmtDate(r.last_verified_at)}</p>
                </li>
              ))}
            </ul>
          )}
          {q.data!.total > q.data!.page_size && (
            <div className="flex gap-2 justify-center">
              <Button variant="secondary" size="sm" disabled={filters.page <= 1} onClick={() => setF("page", String(filters.page - 1))}>Previous</Button>
              <span className="text-sm text-ink-muted self-center">Page {filters.page} of {Math.ceil(q.data!.total / q.data!.page_size)}</span>
              <Button variant="secondary" size="sm" disabled={filters.page * q.data!.page_size >= q.data!.total} onClick={() => { const n = new URLSearchParams(params); n.set("page", String(filters.page + 1)); setParams(n); }}>Next</Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
