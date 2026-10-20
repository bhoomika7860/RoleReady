import { Plus, Trash2, X } from "lucide-react";
import { ReactNode, useState } from "react";
import type { ResumeContent } from "@/api/types";
import { Button, cx, Field, Input, Textarea } from "@/components/ui";

const DATE_RE = /^(\d{4}(-\d{2})?|Present)?$/;

export function emptyContent(name = ""): ResumeContent {
  return { header: { full_name: name, email: "", phone: "", location: "", links: [] }, summary: "", education: [],
    skills: [], experience: [], projects: [], certifications: [], achievements: [] };
}

export function validateContent(c: ResumeContent): string[] {
  const errs: string[] = [];
  if (!c.header.full_name.trim()) errs.push("Add your name in the header.");
  if (c.header.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.header.email)) errs.push("Header email looks invalid.");
  if (!(c.education.length || c.experience.length || c.projects.length)) errs.push("Add at least one education, experience or project entry.");
  const dates = [...c.education.flatMap((e) => [e.start, e.end]), ...c.experience.flatMap((e) => [e.start, e.end]),
    ...c.projects.flatMap((p) => [p.start, p.end])];
  if (dates.some((d) => d && !DATE_RE.test(d))) errs.push("Dates must be YYYY, YYYY-MM or Present.");
  const bullets = [...c.experience.flatMap((e) => e.bullets), ...c.projects.flatMap((p) => p.bullets)];
  if (bullets.some((b) => !b.text.trim())) errs.push("Remove empty bullets.");
  if (bullets.some((b) => b.text.length > 300)) errs.push("Bullets can be at most 300 characters.");
  if (c.education.some((e) => !e.institution.trim())) errs.push("Each education entry needs an institution.");
  if (c.experience.some((e) => !e.title.trim())) errs.push("Each experience entry needs a title.");
  if (c.projects.some((p) => !p.name.trim())) errs.push("Each project needs a name.");
  if (c.experience.length > 10 || c.projects.length > 10) errs.push("Keep at most 10 projects and 10 experience entries.");
  return errs;
}

/** Normalises empty strings to null so the server schema accepts the payload. */
export function cleanContent(c: ResumeContent): ResumeContent {
  const n = (v?: string | null) => (v && v.trim() ? v.trim() : null);
  return {
    ...c,
    header: { ...c.header, full_name: c.header.full_name.trim(), email: n(c.header.email), phone: n(c.header.phone),
      location: n(c.header.location), links: c.header.links ?? [] },
    summary: n(c.summary),
    education: c.education.map((e) => ({ ...e, degree: n(e.degree), field: n(e.field), start: n(e.start), end: n(e.end),
      score: n(e.score), details: e.details ?? [] })),
    experience: c.experience.map((e) => ({ ...e, organization: n(e.organization), location: n(e.location),
      start: n(e.start), end: n(e.end), technologies: e.technologies.filter(Boolean),
      bullets: e.bullets.filter((b) => b.text.trim()).map((b) => ({ ...b, text: b.text.trim() })) })),
    projects: c.projects.map((p) => ({ ...p, role: n(p.role), link: n(p.link), start: n(p.start), end: n(p.end),
      technologies: p.technologies.filter(Boolean),
      bullets: p.bullets.filter((b) => b.text.trim()).map((b) => ({ ...b, text: b.text.trim() })) })),
    certifications: c.certifications.map((x) => ({ ...x, issuer: n(x.issuer), date: n(x.date) })),
    skills: c.skills.filter((s) => s.name.trim()),
    achievements: c.achievements.filter((a) => a.text.trim()),
  };
}

function Section({ title, children, onAdd, addLabel }: { title: string; children: ReactNode; onAdd?: () => void;
  addLabel?: string }) {
  return (
    <details open className="group rounded-md border border-line bg-white">
      <summary className="flex items-center justify-between cursor-pointer px-4 py-3 font-medium text-sm list-none">
        <span>{title}</span><span className="text-ink-subtle text-xs group-open:hidden">Show</span>
      </summary>
      <div className="px-4 pb-4 space-y-3">
        {children}
        {onAdd && <Button type="button" size="sm" variant="secondary" icon={<Plus className="h-3.5 w-3.5" />} onClick={onAdd}>{addLabel}</Button>}
      </div>
    </details>
  );
}

function TagInput({ values, onChange, label, placeholder }: { values: string[]; onChange: (v: string[]) => void;
  label: string; placeholder?: string }) {
  const [text, setText] = useState("");
  const add = () => {
    const parts = text.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...values, ...parts.filter((p) => !values.includes(p))]);
    setText("");
  };
  return (
    <div>
      <div className="label">{label}</div>
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-1 text-xs">
            {v}<button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}><X className="h-3 w-3" /></button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <Input value={text} placeholder={placeholder ?? "Type and press Enter (comma-separated works)"} aria-label={label}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        <Button type="button" variant="secondary" onClick={add}>Add</Button>
      </div>
    </div>
  );
}

function Bullets({ bullets, onChange }: { bullets: { id?: string; text: string }[];
  onChange: (b: { id?: string; text: string }[]) => void }) {
  return (
    <div className="space-y-2">
      <div className="label">Bullet points</div>
      {bullets.map((b, i) => (
        <div key={b.id ?? i} className="flex gap-2">
          <Textarea rows={2} className="min-h-[60px]" value={b.text} maxLength={300} aria-label={`Bullet ${i + 1}`}
            onChange={(e) => onChange(bullets.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
          <button type="button" className="p-2 h-fit rounded hover:bg-slate-100 text-ink-muted" aria-label={`Remove bullet ${i + 1}`}
            onClick={() => onChange(bullets.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
        </div>
      ))}
      {bullets.length < 8 && <Button type="button" size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />}
        onClick={() => onChange([...bullets, { text: "" }])}>Add bullet</Button>}
    </div>
  );
}

function Entry({ children, onRemove, label }: { children: ReactNode; onRemove: () => void; label: string }) {
  return (
    <div className="rounded-md border border-line p-3 space-y-3 bg-canvas/50">
      <div className="flex justify-end"><button type="button" onClick={onRemove} className="text-xs text-bad hover:underline inline-flex items-center gap-1"
        aria-label={`Remove ${label}`}><Trash2 className="h-3.5 w-3.5" />Remove</button></div>
      {children}
    </div>
  );
}

export function ResumeEditor({ value, onChange }: { value: ResumeContent; onChange: (c: ResumeContent) => void }) {
  const set = (patch: Partial<ResumeContent>) => onChange({ ...value, ...patch });
  const h = value.header;
  return (
    <div className="space-y-3">
      <Section title="Header">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Full name" htmlFor="h-name" required><Input id="h-name" value={h.full_name} maxLength={100}
            onChange={(e) => set({ header: { ...h, full_name: e.target.value } })} /></Field>
          <Field label="Email" htmlFor="h-email"><Input id="h-email" type="email" value={h.email ?? ""}
            onChange={(e) => set({ header: { ...h, email: e.target.value } })} /></Field>
          <Field label="Phone" htmlFor="h-phone"><Input id="h-phone" value={h.phone ?? ""} maxLength={20}
            onChange={(e) => set({ header: { ...h, phone: e.target.value } })} /></Field>
          <Field label="Location" htmlFor="h-loc"><Input id="h-loc" value={h.location ?? ""} maxLength={100}
            onChange={(e) => set({ header: { ...h, location: e.target.value } })} /></Field>
        </div>
        <Field label="Summary (optional)" htmlFor="h-sum"><Textarea id="h-sum" rows={3} maxLength={600} value={value.summary ?? ""}
          onChange={(e) => set({ summary: e.target.value })} /></Field>
      </Section>

      <Section title={`Education (${value.education.length})`} addLabel="Add education"
        onAdd={() => set({ education: [...value.education, { institution: "", degree: "", field: "", start: "", end: "", score: "", details: [] }] })}>
        {value.education.map((e, i) => {
          const up = (p: Partial<typeof e>) => set({ education: value.education.map((x, j) => (j === i ? { ...x, ...p } : x)) });
          return (
            <Entry key={e.id ?? i} label="education entry" onRemove={() => set({ education: value.education.filter((_, j) => j !== i) })}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Institution" required><Input value={e.institution} onChange={(ev) => up({ institution: ev.target.value })} /></Field>
                <Field label="Degree"><Input value={e.degree ?? ""} onChange={(ev) => up({ degree: ev.target.value })} /></Field>
                <Field label="Field of study"><Input value={e.field ?? ""} onChange={(ev) => up({ field: ev.target.value })} /></Field>
                <Field label="Score (CGPA / %)"><Input value={e.score ?? ""} maxLength={40} onChange={(ev) => up({ score: ev.target.value })} /></Field>
                <Field label="Start" hint="YYYY or YYYY-MM"><Input value={e.start ?? ""} onChange={(ev) => up({ start: ev.target.value })} /></Field>
                <Field label="End" hint="YYYY, YYYY-MM or Present"><Input value={e.end ?? ""} onChange={(ev) => up({ end: ev.target.value })} /></Field>
              </div>
            </Entry>
          );
        })}
      </Section>

      <Section title={`Skills (${value.skills.length})`}>
        <TagInput label="Skills" values={value.skills.map((s) => s.name)}
          onChange={(names) => set({ skills: names.map((n) => value.skills.find((s) => s.name === n) ?? { name: n }) })} />
      </Section>

      <Section title={`Experience (${value.experience.length})`} addLabel="Add experience"
        onAdd={() => set({ experience: [...value.experience, { title: "", organization: "", start: "", end: "", technologies: [], bullets: [{ text: "" }] }] })}>
        {value.experience.map((e, i) => {
          const up = (p: Partial<typeof e>) => set({ experience: value.experience.map((x, j) => (j === i ? { ...x, ...p } : x)) });
          return (
            <Entry key={e.id ?? i} label="experience entry" onRemove={() => set({ experience: value.experience.filter((_, j) => j !== i) })}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Title" required><Input value={e.title} onChange={(ev) => up({ title: ev.target.value })} /></Field>
                <Field label="Organisation"><Input value={e.organization ?? ""} onChange={(ev) => up({ organization: ev.target.value })} /></Field>
                <Field label="Start" hint="YYYY-MM"><Input value={e.start ?? ""} onChange={(ev) => up({ start: ev.target.value })} /></Field>
                <Field label="End" hint="YYYY-MM or Present"><Input value={e.end ?? ""} onChange={(ev) => up({ end: ev.target.value })} /></Field>
              </div>
              <TagInput label="Technologies used" values={e.technologies} onChange={(v) => up({ technologies: v })} />
              <Bullets bullets={e.bullets} onChange={(b) => up({ bullets: b })} />
            </Entry>
          );
        })}
      </Section>

      <Section title={`Projects (${value.projects.length})`} addLabel="Add project"
        onAdd={() => set({ projects: [...value.projects, { name: "", role: "", technologies: [], bullets: [{ text: "" }] }] })}>
        {value.projects.map((p, i) => {
          const up = (q: Partial<typeof p>) => set({ projects: value.projects.map((x, j) => (j === i ? { ...x, ...q } : x)) });
          return (
            <Entry key={p.id ?? i} label="project" onRemove={() => set({ projects: value.projects.filter((_, j) => j !== i) })}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Project name" required><Input value={p.name} onChange={(ev) => up({ name: ev.target.value })} /></Field>
                <Field label="Your role (optional)"><Input value={p.role ?? ""} onChange={(ev) => up({ role: ev.target.value })} /></Field>
              </div>
              <TagInput label="Technologies used" values={p.technologies} onChange={(v) => up({ technologies: v })} />
              <Bullets bullets={p.bullets} onChange={(b) => up({ bullets: b })} />
            </Entry>
          );
        })}
      </Section>

      <Section title={`Certifications (${value.certifications.length})`} addLabel="Add certification"
        onAdd={() => set({ certifications: [...value.certifications, { name: "", issuer: "", date: "" }] })}>
        {value.certifications.map((c, i) => {
          const up = (q: Partial<typeof c>) => set({ certifications: value.certifications.map((x, j) => (j === i ? { ...x, ...q } : x)) });
          return (
            <Entry key={c.id ?? i} label="certification" onRemove={() => set({ certifications: value.certifications.filter((_, j) => j !== i) })}>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Name" required><Input value={c.name} onChange={(ev) => up({ name: ev.target.value })} /></Field>
                <Field label="Issuer"><Input value={c.issuer ?? ""} onChange={(ev) => up({ issuer: ev.target.value })} /></Field>
                <Field label="Date" hint="YYYY-MM"><Input value={c.date ?? ""} onChange={(ev) => up({ date: ev.target.value })} /></Field>
              </div>
            </Entry>
          );
        })}
      </Section>

      <Section title={`Achievements (${value.achievements.length})`} addLabel="Add achievement"
        onAdd={() => set({ achievements: [...value.achievements, { text: "" }] })}>
        {value.achievements.map((a, i) => (
          <div key={a.id ?? i} className="flex gap-2">
            <Input value={a.text} maxLength={300} aria-label={`Achievement ${i + 1}`}
              onChange={(ev) => set({ achievements: value.achievements.map((x, j) => (j === i ? { ...x, text: ev.target.value } : x)) })} />
            <button type="button" className="p-2 rounded hover:bg-slate-100" aria-label={`Remove achievement ${i + 1}`}
              onClick={() => set({ achievements: value.achievements.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
      </Section>
    </div>
  );
}

const range = (s?: string | null, e?: string | null) => [s, e].filter(Boolean).join(" – ");

/** ATS-friendly single-column preview (also used as the print layout). */
export function ResumePreview({ c, className }: { c: ResumeContent; className?: string }) {
  const h = c.header;
  return (
    <article className={cx("bg-white border border-line rounded-md p-5 text-[13px] leading-relaxed text-ink print:border-0", className)}
      aria-label="Resume preview">
      <h2 className="text-lg font-semibold">{h.full_name || "Your name"}</h2>
      <div className="text-ink-muted text-xs">{[h.email, h.phone, h.location].filter(Boolean).join(" · ")}</div>
      {c.summary && <p className="mt-2">{c.summary}</p>}
      {c.education.length > 0 && <PSection title="Education">{c.education.map((e, i) => (
        <div key={i} className="mb-1.5"><div className="font-medium">{e.institution}</div>
          <div className="text-ink-muted">{[e.degree, e.field].filter(Boolean).join(", ")}{range(e.start, e.end) && ` · ${range(e.start, e.end)}`}{e.score && ` · ${e.score}`}</div></div>
      ))}</PSection>}
      {c.skills.length > 0 && <PSection title="Skills"><p>{c.skills.map((s) => s.name).join(", ")}</p></PSection>}
      {c.experience.length > 0 && <PSection title="Experience">{c.experience.map((e, i) => (
        <div key={i} className="mb-2"><div className="font-medium">{e.title}{e.organization && `, ${e.organization}`}</div>
          {range(e.start, e.end) && <div className="text-ink-muted text-xs">{range(e.start, e.end)}</div>}
          <ul className="list-disc pl-5">{e.bullets.filter((b) => b.text).map((b, j) => <li key={j}>{b.text}</li>)}</ul></div>
      ))}</PSection>}
      {c.projects.length > 0 && <PSection title="Projects">{c.projects.map((p, i) => (
        <div key={i} className="mb-2"><div className="font-medium">{p.name}{p.technologies.length > 0 && <span className="font-normal text-ink-muted"> ({p.technologies.join(", ")})</span>}</div>
          <ul className="list-disc pl-5">{p.bullets.filter((b) => b.text).map((b, j) => <li key={j}>{b.text}</li>)}</ul></div>
      ))}</PSection>}
      {c.certifications.length > 0 && <PSection title="Certifications"><ul className="list-disc pl-5">{c.certifications.map((x, i) => <li key={i}>{x.name}{x.issuer && ` — ${x.issuer}`}</li>)}</ul></PSection>}
      {c.achievements.length > 0 && <PSection title="Achievements"><ul className="list-disc pl-5">{c.achievements.map((a, i) => <li key={i}>{a.text}</li>)}</ul></PSection>}
    </article>
  );
}

function PSection({ title, children }: { title: string; children: ReactNode }) {
  return <section className="mt-3"><h3 className="text-[11px] font-semibold uppercase tracking-wider text-navy-800 border-b border-line pb-0.5 mb-1.5">{title}</h3>{children}</section>;
}
