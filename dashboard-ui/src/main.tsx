import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Archive,
  BookOpen,
  Check,
  ChevronRight,
  Copy,
  Database,
  Eye,
  KeyRound,
  Layers3,
  Lock,
  LogOut,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import "./styles.css";

type Dict = Record<string, any>;

type Session = {
  has_admin: boolean;
  user: null | { id: string; username: string };
};

type Category = {
  id: string;
  name: string;
  description?: string | null;
  allow_auto_prefetch: number;
  agent_can_create: number;
  agent_can_write: number;
};

type Memory = {
  id: string;
  category_id: string;
  category_name?: string;
  title: string;
  summary?: string | null;
  body: string;
  tags?: string[];
  tags_text?: string;
  confidence: number;
  auto_prefetch_level: string;
  archived: number;
  updated_at: string;
};

type Secret = {
  id: string;
  name: string;
  description?: string | null;
  value_type: string;
  service?: string | null;
  host?: string | null;
  scope?: string | null;
  tags?: string[];
  tags_text?: string;
  updated_at: string;
  last_revealed_at?: string | null;
};

type ApiKey = {
  id: string;
  name: string;
  actor: string;
  description?: string | null;
  key_prefix: string;
  scopes: string[];
  enabled: number;
  last_used_at?: string | null;
  created_at: string;
};

const navItems = [
  { label: "Overview", path: "/dashboard", icon: Database },
  { label: "Memories", path: "/dashboard/memories", icon: BookOpen },
  { label: "Secrets", path: "/dashboard/secrets", icon: Lock },
  { label: "API Keys", path: "/dashboard/api-keys", icon: KeyRound },
  { label: "Categories", path: "/dashboard/categories", icon: Layers3 },
  { label: "Activity", path: "/dashboard/activity", icon: Activity },
];

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  if (!response.ok) {
    let detail = `Request failed with HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

function splitTags(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function Button({
  children,
  icon: Icon,
  tone = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: React.ComponentType<{ size?: number }>;
  tone?: "primary" | "secondary" | "danger" | "ghost";
}) {
  return (
    <button className={`btn ${tone}`} {...props}>
      {Icon && <Icon size={16} />}
      <span>{children}</span>
    </button>
  );
}

function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

function EmptyState({
  title,
  body,
  icon: Icon = Search,
}: {
  title: string;
  body: string;
  icon?: React.ComponentType<{ size?: number }>;
}) {
  return (
    <div className="empty-state">
      <Icon size={28} />
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <h2>{title}</h2>
          <Button tone="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}

function useRoute() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = (next: string) => {
    window.history.pushState({}, "", next);
    setPath(next);
  };
  return { path, navigate };
}

function AuthPage({
  mode,
  onSession,
}: {
  mode: "setup" | "login";
  onSession: (session: Session) => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    username: "",
    password: "",
    confirm_password: "",
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api(mode === "setup" ? "/dashboard/api/setup" : "/dashboard/api/login", {
        method: "POST",
        body: JSON.stringify(form),
      });
      onSession(await api<Session>("/dashboard/api/session"));
      window.history.replaceState({}, "", "/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel">
        <div className="brand-mark">
          <ShieldCheck size={30} />
          <div>
            <strong>Glyph Hold</strong>
            <span>Local memory and secrets</span>
          </div>
        </div>
        <h1>{mode === "setup" ? "Create dashboard access" : "Sign in"}</h1>
        <p>
          {mode === "setup"
            ? "Set the first local admin account for this Glyph Hold instance."
            : "Use your local dashboard account to manage memories, secrets, and agent keys."}
        </p>
        {error && <div className="alert">{error}</div>}
        <form className="stack" onSubmit={submit}>
          <Field label="Username">
            <input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              required
              autoFocus
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required
            />
          </Field>
          {mode === "setup" && (
            <Field label="Confirm password" hint="Use at least 12 characters.">
              <input
                type="password"
                value={form.confirm_password}
                onChange={(e) => setForm({ ...form, confirm_password: e.target.value })}
                required
              />
            </Field>
          )}
          <Button icon={Check} disabled={busy}>
            {busy ? "Working" : mode === "setup" ? "Create account" : "Sign in"}
          </Button>
        </form>
      </section>
    </main>
  );
}

function Shell({
  session,
  path,
  navigate,
  onLogout,
  children,
}: {
  session: Session;
  path: string;
  navigate: (path: string) => void;
  onLogout: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand-button" onClick={() => navigate("/dashboard")}>
          <div className="brand-icon">GH</div>
          <div>
            <strong>Glyph Hold</strong>
            <span>Agent memory vault</span>
          </div>
        </button>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            const active =
              item.path === "/dashboard" ? path === "/dashboard" : path.startsWith(item.path);
            return (
              <button
                key={item.path}
                className={active ? "active" : ""}
                onClick={() => navigate(item.path)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div>
            <span>Signed in</span>
            <strong>{session.user?.username}</strong>
          </div>
          <Button tone="ghost" icon={LogOut} onClick={onLogout}>
            Sign out
          </Button>
        </div>
      </aside>
      <main className="content-shell">{children}</main>
    </div>
  );
}

function PageHeader({
  eyebrow,
  title,
  body,
  action,
}: {
  eyebrow: string;
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{body}</p>
      </div>
      {action && <div className="page-action">{action}</div>}
    </header>
  );
}

function OverviewPage({ navigate }: { navigate: (path: string) => void }) {
  const [data, setData] = useState<Dict | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Dict>("/dashboard/api/overview").then(setData).catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="alert">{error}</div>;
  if (!data) return <div className="loading">Loading dashboard</div>;

  const stats = [
    { label: "Memories", value: data.memory_count, icon: BookOpen, path: "/dashboard/memories" },
    { label: "Secrets", value: data.secret_count, icon: Lock, path: "/dashboard/secrets" },
    { label: "API keys", value: data.api_key_count, icon: KeyRound, path: "/dashboard/api-keys" },
    { label: "Schema", value: data.schema_version, icon: Database, path: "/dashboard/activity" },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Status"
        title="Dashboard"
        body="Manage durable agent memory, local secrets, API keys, and audit activity from one place."
      />
      <section className="stats-grid">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <button key={stat.label} className="stat-card" onClick={() => navigate(stat.path)}>
              <Icon size={22} />
              <span>{stat.label}</span>
              <strong>{stat.value}</strong>
              <ChevronRight size={18} />
            </button>
          );
        })}
      </section>
      <section className="two-column">
        <div className="panel">
          <div className="panel-heading">
            <h2>Runtime</h2>
          </div>
          <dl className="detail-grid">
            <dt>Version</dt>
            <dd>{data.version}</dd>
            <dt>Database</dt>
            <dd>
              <Badge tone={data.database_status === "ok" ? "success" : "danger"}>
                {data.database_status}
              </Badge>
            </dd>
            <dt>Secrets</dt>
            <dd>
              <Badge tone={data.secrets_enabled ? "success" : "warning"}>
                {data.secrets_enabled ? "enabled" : "disabled"}
              </Badge>
            </dd>
          </dl>
        </div>
        <div className="panel">
          <div className="panel-heading">
            <h2>Recent activity</h2>
            <Button tone="ghost" onClick={() => navigate("/dashboard/activity")}>
              View all
            </Button>
          </div>
          <EventList events={data.recent_events || []} compact />
        </div>
      </section>
    </>
  );
}

function MemoriesPage({ navigate }: { navigate: (path: string) => void }) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [memoriesList, setMemoriesList] = useState<Memory[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    category_id: "",
    title: "",
    summary: "",
    body: "",
    tags: "",
    confidence: 3,
    auto_prefetch_level: "normal",
  });

  async function load() {
    const [categoryRows, memoryRows] = await Promise.all([
      api<Category[]>("/dashboard/api/categories"),
      api<{ memories: Memory[] }>(
        `/dashboard/api/memories?q=${encodeURIComponent(query)}&category=${encodeURIComponent(category)}`,
      ),
    ]);
    setCategories(categoryRows);
    setMemoriesList(memoryRows.memories);
    setForm((current) => ({
      ...current,
      category_id: current.category_id || categoryRows[0]?.id || "",
    }));
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function search(event?: FormEvent) {
    event?.preventDefault();
    setError("");
    try {
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api<Memory>("/dashboard/api/memories", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          tags: splitTags(form.tags),
          confidence: Number(form.confidence),
        }),
      });
      setForm({
        ...form,
        title: "",
        summary: "",
        body: "",
        tags: "",
        confidence: 3,
        auto_prefetch_level: "normal",
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Memory"
        title="Memories"
        body="Create searchable context that agents can retrieve deterministically."
      />
      {error && <div className="alert">{error}</div>}
      <section className="work-grid">
        <form className="panel stack" onSubmit={create}>
          <div className="panel-heading">
            <h2>Create memory</h2>
          </div>
          <Field label="Category">
            <select
              value={form.category_id}
              onChange={(e) => setForm({ ...form, category_id: e.target.value })}
              required
            >
              {categories.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Title">
            <input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              required
            />
          </Field>
          <Field label="Summary" hint="Short version used for quick review and prefetch.">
            <input value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
          </Field>
          <Field label="Body">
            <textarea
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
              required
            />
          </Field>
          <div className="form-row">
            <Field label="Confidence">
              <input
                type="number"
                min="1"
                max="5"
                value={form.confidence}
                onChange={(e) => setForm({ ...form, confidence: Number(e.target.value) })}
              />
            </Field>
            <Field label="Prefetch">
              <select
                value={form.auto_prefetch_level}
                onChange={(e) => setForm({ ...form, auto_prefetch_level: e.target.value })}
              >
                {["never", "low", "normal", "high", "pinned"].map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Tags">
            <input
              value={form.tags}
              placeholder="comma-separated"
              onChange={(e) => setForm({ ...form, tags: e.target.value })}
            />
          </Field>
          <Button icon={Plus}>Create memory</Button>
        </form>
        <div className="panel">
          <div className="panel-heading">
            <h2>Memory library</h2>
          </div>
          <form className="filters" onSubmit={search}>
            <div className="searchbox">
              <Search size={16} />
              <input value={query} placeholder="Search memories" onChange={(e) => setQuery(e.target.value)} />
            </div>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {categories.map((item) => (
                <option key={item.id} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
            <Button icon={Search} tone="secondary">
              Search
            </Button>
          </form>
          {memoriesList.length === 0 ? (
            <EmptyState title="No memories found" body="Create a memory or adjust the current search." />
          ) : (
            <div className="list-table">
              {memoriesList.map((memory) => (
                <button
                  key={memory.id}
                  className="list-row"
                  onClick={() => navigate(`/dashboard/memories/${memory.id}`)}
                >
                  <div>
                    <strong>{memory.title}</strong>
                    <span>{memory.summary || memory.body.slice(0, 160)}</span>
                  </div>
                  <div className="row-meta">
                    <Badge>{memory.category_name}</Badge>
                    <Badge tone={memory.auto_prefetch_level === "pinned" ? "success" : "neutral"}>
                      {memory.auto_prefetch_level}
                    </Badge>
                    <span>{memory.updated_at}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}

function MemoryDetailPage({ id, navigate }: { id: string; navigate: (path: string) => void }) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [memory, setMemory] = useState<Memory | null>(null);
  const [revisions, setRevisions] = useState<Memory[]>([]);
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [form, setForm] = useState<any>(null);

  async function load() {
    const [categoryRows, detail] = await Promise.all([
      api<Category[]>("/dashboard/api/categories"),
      api<{ memory: Memory; revisions: Memory[] }>(`/dashboard/api/memories/${id}`),
    ]);
    setCategories(categoryRows);
    setMemory(detail.memory);
    setRevisions(detail.revisions);
    setForm({
      category_id: detail.memory.category_id,
      title: detail.memory.title,
      summary: detail.memory.summary || "",
      body: detail.memory.body,
      tags: detail.memory.tags_text || "",
      confidence: detail.memory.confidence,
      auto_prefetch_level: detail.memory.auto_prefetch_level,
    });
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [id]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api(`/dashboard/api/memories/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...form,
          tags: splitTags(form.tags),
          confidence: Number(form.confidence),
        }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function restore(revisionId: string) {
    await api(`/dashboard/api/memories/${id}/revisions/${revisionId}/restore`, { method: "POST" });
    await load();
  }

  async function archive() {
    await api(`/dashboard/api/memories/${id}/archive`, { method: "POST" });
    await load();
  }

  async function remove(confirmTitle: string) {
    await api(`/dashboard/api/memories/${id}`, {
      method: "DELETE",
      body: JSON.stringify({ confirm_title: confirmTitle }),
    });
    navigate("/dashboard/memories");
  }

  if (error) return <div className="alert">{error}</div>;
  if (!memory || !form) return <div className="loading">Loading memory</div>;

  return (
    <>
      <PageHeader
        eyebrow="Memory detail"
        title={memory.title}
        body="Review, edit, archive, delete, or restore a previous revision."
        action={
          <Button tone="secondary" onClick={() => navigate("/dashboard/memories")}>
            Back to memories
          </Button>
        }
      />
      <section className="work-grid">
        <form className="panel stack" onSubmit={save}>
          <div className="panel-heading">
            <h2>Edit memory</h2>
          </div>
          <Field label="Category">
            <select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}>
              {categories.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Title">
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Summary">
            <input value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
          </Field>
          <Field label="Body">
            <textarea value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
          </Field>
          <div className="form-row">
            <Field label="Confidence">
              <input
                type="number"
                min="1"
                max="5"
                value={form.confidence}
                onChange={(e) => setForm({ ...form, confidence: Number(e.target.value) })}
              />
            </Field>
            <Field label="Prefetch">
              <select
                value={form.auto_prefetch_level}
                onChange={(e) => setForm({ ...form, auto_prefetch_level: e.target.value })}
              >
                {["never", "low", "normal", "high", "pinned"].map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Tags">
            <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          </Field>
          <div className="button-row">
            <Button icon={Pencil}>Save memory</Button>
            <Button type="button" tone="secondary" icon={Archive} onClick={archive}>
              Archive
            </Button>
            <Button type="button" tone="danger" icon={Trash2} onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          </div>
        </form>
        <div className="panel">
          <div className="panel-heading">
            <h2>Revisions</h2>
          </div>
          {revisions.length === 0 ? (
            <EmptyState title="No revisions yet" body="Revisions appear after edits or restores." icon={RotateCcw} />
          ) : (
            <div className="list-table compact">
              {revisions.map((revision) => (
                <div className="list-row static" key={revision.id}>
                  <div>
                    <strong>{revision.title}</strong>
                    <span>{revision.summary || revision.body.slice(0, 140)}</span>
                  </div>
                  <div className="row-meta">
                    <span>{(revision as any).changed_by || ""}</span>
                    <span>{(revision as any).change_reason || ""}</span>
                    <Button tone="secondary" icon={RotateCcw} onClick={() => restore(revision.id)}>
                      Restore
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
      {confirmDelete && (
        <ConfirmModal
          title="Delete memory"
          label="Type the memory title to delete it."
          expected={memory.title}
          onClose={() => setConfirmDelete(false)}
          onConfirm={remove}
        />
      )}
    </>
  );
}

function SecretsPage() {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [valueTypes, setValueTypes] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<{ name: string; value: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Secret | null>(null);
  const [editing, setEditing] = useState<Secret | null>(null);
  const [filters, setFilters] = useState({ query: "", service: "", host: "", scope: "" });
  const [form, setForm] = useState({
    name: "",
    value: "",
    description: "",
    value_type: "text",
    service: "",
    host: "",
    scope: "",
    tags: "",
  });

  async function load() {
    const params = new URLSearchParams(filters);
    const data = await api<{ secrets_enabled: boolean; value_types: string[]; secrets: Secret[] }>(
      `/dashboard/api/secrets?${params}`,
    );
    setEnabled(data.secrets_enabled);
    setValueTypes(data.value_types);
    setSecrets(data.secrets);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/dashboard/api/secrets", {
        method: "POST",
        body: JSON.stringify({ ...form, tags: splitTags(form.tags) }),
      });
      setForm({ ...form, name: "", value: "", description: "", tags: "" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    const data = new FormData(event.target as HTMLFormElement);
    await api(`/dashboard/api/secrets/${editing.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: data.get("name"),
        value: data.get("value") || null,
        description: data.get("description") || null,
        value_type: data.get("value_type"),
        service: data.get("service") || null,
        host: data.get("host") || null,
        scope: data.get("scope") || null,
        tags: splitTags(String(data.get("tags") || "")),
      }),
    });
    setEditing(null);
    await load();
  }

  async function reveal(secret: Secret) {
    setRevealed(await api(`/dashboard/api/secrets/${secret.id}/reveal`, { method: "POST" }));
    await load();
  }

  async function remove(confirmName: string) {
    if (!confirmDelete) return;
    await api(`/dashboard/api/secrets/${confirmDelete.id}`, {
      method: "DELETE",
      body: JSON.stringify({ confirm_name: confirmName }),
    });
    setConfirmDelete(null);
    await load();
  }

  return (
    <>
      <PageHeader
        eyebrow="Secrets"
        title="Secrets"
        body="Store encrypted values and reveal them only through deliberate dashboard or API actions."
      />
      {!enabled && <div className="alert">Secret storage is disabled until an encryption key is configured.</div>}
      {error && <div className="alert">{error}</div>}
      <section className="work-grid">
        <form className="panel stack" onSubmit={create}>
          <div className="panel-heading">
            <h2>Create secret</h2>
          </div>
          <Field label="Name">
            <input
              value={form.name}
              placeholder="CUSTOM_API_KEY_HERE"
              onChange={(e) => setForm({ ...form, name: e.target.value.toUpperCase() })}
              required
            />
          </Field>
          <Field label="Value">
            <input
              type="password"
              value={form.value}
              onChange={(e) => setForm({ ...form, value: e.target.value })}
              required
            />
          </Field>
          <Field label="Description">
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <div className="form-row">
            <Field label="Type">
              <select value={form.value_type} onChange={(e) => setForm({ ...form, value_type: e.target.value })}>
                {valueTypes.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Scope">
              <input value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} />
            </Field>
          </div>
          <div className="form-row">
            <Field label="Service">
              <input value={form.service} onChange={(e) => setForm({ ...form, service: e.target.value })} />
            </Field>
            <Field label="Host">
              <input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
            </Field>
          </div>
          <Field label="Tags">
            <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          </Field>
          <Button icon={Plus} disabled={!enabled}>
            Create secret
          </Button>
        </form>
        <div className="panel">
          <div className="panel-heading">
            <h2>Secret vault</h2>
          </div>
          <form
            className="filters"
            onSubmit={(event) => {
              event.preventDefault();
              load().catch((err) => setError(err.message));
            }}
          >
            <div className="searchbox">
              <Search size={16} />
              <input
                value={filters.query}
                placeholder="Search metadata"
                onChange={(e) => setFilters({ ...filters, query: e.target.value })}
              />
            </div>
            <input placeholder="Service" value={filters.service} onChange={(e) => setFilters({ ...filters, service: e.target.value })} />
            <input placeholder="Host" value={filters.host} onChange={(e) => setFilters({ ...filters, host: e.target.value })} />
            <Button tone="secondary" icon={Search}>
              Filter
            </Button>
          </form>
          {secrets.length === 0 ? (
            <EmptyState title="No secrets found" body="Create a secret or adjust the current metadata filters." icon={Lock} />
          ) : (
            <div className="data-table">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Service</th>
                    <th>Scope</th>
                    <th>Last revealed</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {secrets.map((secret) => (
                    <tr key={secret.id}>
                      <td>
                        <code>{secret.name}</code>
                        <small>{secret.description || ""}</small>
                      </td>
                      <td>{secret.value_type}</td>
                      <td>{secret.service || ""}</td>
                      <td>{secret.scope || ""}</td>
                      <td>{secret.last_revealed_at || ""}</td>
                      <td>
                        <div className="table-actions">
                          <Button tone="secondary" icon={Eye} onClick={() => reveal(secret)}>
                            Reveal
                          </Button>
                          <Button tone="ghost" icon={Pencil} onClick={() => setEditing(secret)}>
                            Edit
                          </Button>
                          <Button tone="danger" icon={Trash2} onClick={() => setConfirmDelete(secret)}>
                            Delete
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
      {revealed && (
        <Modal title={revealed.name} onClose={() => setRevealed(null)}>
          <div className="secret-reveal">
            <span>This value is shown only for this reveal action.</span>
            <code>{revealed.value}</code>
            <Button icon={Copy} onClick={() => navigator.clipboard.writeText(revealed.value)}>
              Copy value
            </Button>
          </div>
        </Modal>
      )}
      {confirmDelete && (
        <ConfirmModal
          title="Delete secret"
          label="Type the secret name to delete it."
          expected={confirmDelete.name}
          onClose={() => setConfirmDelete(null)}
          onConfirm={remove}
        />
      )}
      {editing && (
        <Modal title={`Edit ${editing.name}`} onClose={() => setEditing(null)}>
          <form className="stack" onSubmit={saveEdit}>
            <Field label="Name">
              <input name="name" defaultValue={editing.name} required />
            </Field>
            <Field label="New value">
              <input name="value" type="password" placeholder="Leave blank to keep current" />
            </Field>
            <Field label="Description">
              <input name="description" defaultValue={editing.description || ""} />
            </Field>
            <div className="form-row">
              <Field label="Type">
                <select name="value_type" defaultValue={editing.value_type}>
                  {valueTypes.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Scope">
                <input name="scope" defaultValue={editing.scope || ""} />
              </Field>
            </div>
            <div className="form-row">
              <Field label="Service">
                <input name="service" defaultValue={editing.service || ""} />
              </Field>
              <Field label="Host">
                <input name="host" defaultValue={editing.host || ""} />
              </Field>
            </div>
            <Field label="Tags">
              <input name="tags" defaultValue={editing.tags_text || ""} />
            </Field>
            <Button icon={Pencil}>Save secret</Button>
          </form>
        </Modal>
      )}
    </>
  );
}

function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [defaultScopes, setDefaultScopes] = useState<string[]>([]);
  const [createdKey, setCreatedKey] = useState("");
  const [confirmDisable, setConfirmDisable] = useState<ApiKey | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", actor: "", description: "", scopes: [] as string[] });

  async function load() {
    const data = await api<{ default_scopes: string[]; keys: ApiKey[] }>("/dashboard/api/api-keys");
    setDefaultScopes(data.default_scopes);
    setKeys(data.keys);
    setForm((current) => ({
      ...current,
      scopes: current.scopes.length ? current.scopes : data.default_scopes,
    }));
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const data = await api<{ id: string; value: string }>("/dashboard/api/api-keys", {
        method: "POST",
        body: JSON.stringify(form),
      });
      setCreatedKey(data.value);
      setForm({ ...form, name: "", actor: "", description: "" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function disable(confirmName: string) {
    if (!confirmDisable) return;
    await api(`/dashboard/api/api-keys/${confirmDisable.id}/disable`, {
      method: "POST",
      body: JSON.stringify({ confirm_name: confirmName }),
    });
    setConfirmDisable(null);
    await load();
  }

  async function enable(key: ApiKey) {
    await api(`/dashboard/api/api-keys/${key.id}/enable`, { method: "POST" });
    await load();
  }

  function toggleScope(scope: string) {
    setForm((current) => ({
      ...current,
      scopes: current.scopes.includes(scope)
        ? current.scopes.filter((item) => item !== scope)
        : [...current.scopes, scope],
    }));
  }

  return (
    <>
      <PageHeader
        eyebrow="Access"
        title="API keys"
        body="Create scoped bearer keys for agents and disable keys when access should stop."
      />
      {error && <div className="alert">{error}</div>}
      {createdKey && (
        <div className="secret-once">
          <div>
            <strong>Copy this API key now</strong>
            <span>It will not be shown again.</span>
          </div>
          <code>{createdKey}</code>
          <Button icon={Copy} onClick={() => navigator.clipboard.writeText(createdKey)}>
            Copy key
          </Button>
        </div>
      )}
      <section className="work-grid">
        <form className="panel stack" onSubmit={create}>
          <div className="panel-heading">
            <h2>Create key</h2>
          </div>
          <Field label="Name">
            <input value={form.name} placeholder="Local agent" onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </Field>
          <Field label="Actor">
            <input value={form.actor} placeholder="local-agent" onChange={(e) => setForm({ ...form, actor: e.target.value })} required />
          </Field>
          <Field label="Description">
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <div className="scope-grid">
            {[...defaultScopes, "admin"].map((scope) => (
              <label key={scope} className="check-card">
                <input
                  type="checkbox"
                  checked={form.scopes.includes(scope)}
                  onChange={() => toggleScope(scope)}
                />
                <span>{scope}</span>
              </label>
            ))}
          </div>
          <Button icon={Plus}>Create API key</Button>
        </form>
        <div className="panel">
          <div className="panel-heading">
            <h2>Existing keys</h2>
          </div>
          {keys.length === 0 ? (
            <EmptyState title="No API keys" body="Create a key before connecting an agent." icon={KeyRound} />
          ) : (
            <div className="data-table">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Actor</th>
                    <th>Prefix</th>
                    <th>Status</th>
                    <th>Scopes</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {keys.map((key) => (
                    <tr key={key.id}>
                      <td>{key.name}</td>
                      <td>{key.actor}</td>
                      <td>
                        <code>{key.key_prefix}</code>
                      </td>
                      <td>
                        <Badge tone={key.enabled ? "success" : "danger"}>
                          {key.enabled ? "enabled" : "disabled"}
                        </Badge>
                      </td>
                      <td>
                        <div className="tag-row">
                          {key.scopes.map((scope) => (
                            <Badge key={scope}>{scope}</Badge>
                          ))}
                        </div>
                      </td>
                      <td>
                        {key.enabled ? (
                          <Button tone="danger" onClick={() => setConfirmDisable(key)}>
                            Disable
                          </Button>
                        ) : (
                          <Button tone="secondary" onClick={() => enable(key)}>
                            Enable
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
      {confirmDisable && (
        <ConfirmModal
          title="Disable API key"
          label="Type the key name to disable it."
          expected={confirmDisable.name}
          onClose={() => setConfirmDisable(null)}
          onConfirm={disable}
        />
      )}
    </>
  );
}

function CategoriesPage() {
  const [categoriesList, setCategoriesList] = useState<Category[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", description: "" });

  async function load() {
    setCategoriesList(await api<Category[]>("/dashboard/api/categories"));
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    await api("/dashboard/api/categories", {
      method: "POST",
      body: JSON.stringify({
        name: form.name,
        description: form.description,
        allow_auto_prefetch: true,
        agent_can_create: true,
        agent_can_write: true,
      }),
    });
    setForm({ name: "", description: "" });
    await load();
  }

  return (
    <>
      <PageHeader
        eyebrow="Taxonomy"
        title="Categories"
        body="Control the high-level memory buckets agents and dashboard users can choose from."
      />
      {error && <div className="alert">{error}</div>}
      <section className="work-grid">
        <form className="panel stack" onSubmit={create}>
          <div className="panel-heading">
            <h2>Create category</h2>
          </div>
          <Field label="Name">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </Field>
          <Field label="Description">
            <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Button icon={Plus}>Create category</Button>
        </form>
        <div className="panel">
          <div className="panel-heading">
            <h2>Available categories</h2>
          </div>
          <div className="category-grid">
            {categoriesList.map((category) => (
              <div className="category-card" key={category.id}>
                <strong>{category.name}</strong>
                <p>{category.description}</p>
                <div className="tag-row">
                  <Badge tone={category.allow_auto_prefetch ? "success" : "neutral"}>prefetch</Badge>
                  <Badge tone={category.agent_can_write ? "success" : "neutral"}>agent write</Badge>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

function ActivityPage() {
  const [events, setEvents] = useState<Dict[]>([]);
  const [filters, setFilters] = useState({ actor: "", event_type: "" });
  const [error, setError] = useState("");

  async function load() {
    const params = new URLSearchParams(filters);
    const data = await api<{ events: Dict[] }>(`/dashboard/api/activity?${params}`);
    setEvents(data.events);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  return (
    <>
      <PageHeader
        eyebrow="Audit"
        title="Activity"
        body="Inspect dashboard and agent activity without exposing secret values."
      />
      {error && <div className="alert">{error}</div>}
      <section className="panel">
        <form
          className="filters"
          onSubmit={(event) => {
            event.preventDefault();
            load().catch((err) => setError(err.message));
          }}
        >
          <input placeholder="Actor" value={filters.actor} onChange={(e) => setFilters({ ...filters, actor: e.target.value })} />
          <input
            placeholder="Event type"
            value={filters.event_type}
            onChange={(e) => setFilters({ ...filters, event_type: e.target.value })}
          />
          <Button icon={Search} tone="secondary">
            Filter
          </Button>
        </form>
        <EventList events={events} />
      </section>
    </>
  );
}

function EventList({ events, compact = false }: { events: Dict[]; compact?: boolean }) {
  if (!events.length) {
    return <EmptyState title="No activity yet" body="Events appear as dashboard users and agents act." icon={Activity} />;
  }
  return (
    <div className={`event-list ${compact ? "compact" : ""}`}>
      {events.map((event) => (
        <div className="event-row" key={event.id}>
          <Badge tone={event.success ? "success" : "danger"}>{event.event_type}</Badge>
          <div>
            <strong>{event.message || event.target_id || event.action}</strong>
            <span>
              {event.actor || "unknown"} · {event.created_at}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function ConfirmModal({
  title,
  label,
  expected,
  onClose,
  onConfirm,
}: {
  title: string;
  label: string;
  expected: string;
  onClose: () => void;
  onConfirm: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      {error && <div className="alert">{error}</div>}
      <div className="confirm-box">
        <p>{label}</p>
        <code>{expected}</code>
        <input value={value} onChange={(event) => setValue(event.target.value)} autoFocus />
        <div className="button-row">
          <Button tone="danger" icon={Trash2} onClick={() => onConfirm(value).catch((err) => setError(err.message))}>
            Confirm
          </Button>
          <Button tone="secondary" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function App() {
  const { path, navigate } = useRoute();
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Session>("/dashboard/api/session").then(setSession).catch((err) => setError(err.message));
  }, []);

  async function logout() {
    await api("/dashboard/api/logout", { method: "POST" });
    setSession(await api<Session>("/dashboard/api/session"));
    navigate("/login");
  }

  const page = useMemo(() => {
    if (!session?.has_admin) return <AuthPage mode="setup" onSession={setSession} />;
    if (!session.user) return <AuthPage mode="login" onSession={setSession} />;
    if (path.startsWith("/dashboard/memories/")) {
      return <MemoryDetailPage id={path.split("/").pop() || ""} navigate={navigate} />;
    }
    if (path.startsWith("/dashboard/memories")) return <MemoriesPage navigate={navigate} />;
    if (path.startsWith("/dashboard/secrets")) return <SecretsPage />;
    if (path.startsWith("/dashboard/api-keys")) return <ApiKeysPage />;
    if (path.startsWith("/dashboard/categories")) return <CategoriesPage />;
    if (path.startsWith("/dashboard/activity")) return <ActivityPage />;
    return <OverviewPage navigate={navigate} />;
  }, [session, path]);

  if (error) return <main className="auth-shell"><div className="alert">{error}</div></main>;
  if (!session) return <main className="auth-shell"><div className="loading">Loading Glyph Hold</div></main>;
  if (!session.has_admin || !session.user) return page;

  return (
    <Shell session={session} path={path} navigate={navigate} onLogout={logout}>
      {page}
    </Shell>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
