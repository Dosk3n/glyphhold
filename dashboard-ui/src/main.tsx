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
  Settings,
  FolderOpen,
  Upload,
  Trash2,
} from "lucide-react";
import "./styles.css";
import "./design-system.css";
import {
  SpacesPage,
  SettingsPage,
  MemoryReviewsPage,
  MemoryLibrary,
  MemoryRecord,
  MigrationPage,
  SecretLibrary,
} from "./v2";

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
  { label: "Spaces & access", path: "/dashboard/spaces", icon: FolderOpen },
  { label: "Secrets", path: "/dashboard/secrets", icon: Lock },
  { label: "Activity", path: "/dashboard/activity", icon: Activity },
  { label: "Agent API keys", path: "/dashboard/api-keys", icon: KeyRound },
  { label: "Categories", path: "/dashboard/categories", icon: Layers3 },
  { label: "Settings", path: "/dashboard/settings", icon: Settings },
  { label: "Migration", path: "/dashboard/migration", icon: Upload },
];

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const method = (options.method || "GET").toUpperCase();
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (
    !["GET", "HEAD", "OPTIONS"].includes(method) &&
    (path.startsWith("/dashboard/api/") || path.startsWith("/api/v2/"))
  ) {
    const csrfCookie = document.cookie
      .split("; ")
      .find((item) => item.startsWith("glyphhold_csrf="))
      ?.split("=", 2)[1];
    if (csrfCookie) headers.set("X-CSRF-Token", decodeURIComponent(csrfCookie));
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

function joinList(value?: string[] | null): string {
  return (value || []).join(", ");
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

function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

function ResultCount({ count, noun }: { count: number; noun: string }) {
  return (
    <span className="result-count">
      {count} {noun}
      {count === 1 ? "" : "s"}
    </span>
  );
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
  const ref = React.useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
      <dialog ref={ref} className="modal" aria-label={title} onCancel={onClose} onClose={onClose}>
        <div className="modal-header">
          <h2>{title}</h2>
          <Button tone="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
        {children}
      </dialog>
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
      await api(
        mode === "setup" ? "/dashboard/api/setup" : "/dashboard/api/login",
        {
          method: "POST",
          body: JSON.stringify(form),
        },
      );
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
          <img src="/dashboard-assets/glyphhold-logo.png" alt="" />
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
                onChange={(e) =>
                  setForm({ ...form, confirm_password: e.target.value })
                }
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
  const [reviewMenu, setReviewMenu] = useState({enabled: false, pending: 0});
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const config = await api<Dict>("/dashboard/api/advanced/settings");
        if(!active) return;
        if(!config.enabled) { setReviewMenu({enabled: false, pending: 0}); return; }
        const data = await api<Dict>("/dashboard/api/advanced/proposals/pending-count");
        if(active) setReviewMenu({enabled: true, pending: Number(data.count) || 0});
      } catch { /* Keep the last known menu state during a temporary connection failure. */ }
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener("glyphhold:memory-reviews-changed", refresh);
    return () => { active = false; clearInterval(timer); window.removeEventListener("glyphhold:memory-reviews-changed", refresh); };
  }, [path]);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand-button" onClick={() => navigate("/dashboard")}>
          <div className="brand-icon"><img src="/dashboard-assets/glyphhold-logo.png" alt="" /></div>
          <div>
            <strong>Glyph Hold</strong>
            <span>Shared agent memory</span>
          </div>
        </button>
        <div className="nav-group-label">Workspace</div>
        <nav aria-label="Main navigation">
          {navItems.map((item, index) => {
            const Icon = item.icon;
            const active =
              item.path === "/dashboard"
                ? path === "/dashboard"
                : path.startsWith(item.path);
            return (
              <React.Fragment key={item.path}>
              {index === 5 && <div className="nav-group-label manage">Manage</div>}
              <button
                aria-current={active ? "page" : undefined}
                className={active ? "active" : ""}
                onClick={() => navigate(item.path)}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
              {index === 1 && reviewMenu.enabled && <button className={path === "/dashboard/memory-reviews" ? "active" : ""} aria-current={path === "/dashboard/memory-reviews" ? "page" : undefined} onClick={() => navigate("/dashboard/memory-reviews")}>
                <Check size={18} /><span>Memory reviews</span>{reviewMenu.pending > 0 && <span className="nav-review-count" aria-label={`${reviewMenu.pending} awaiting approval`}>{reviewMenu.pending}</span>}
              </button>}
              </React.Fragment>
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
      <div className="dashboard-main">
        <header className="dashboard-topbar"><span>Workspace / <strong>{path === "/dashboard/memory-reviews" ? "Memory reviews" : navItems.find(item => item.path !== "/dashboard" && path.startsWith(item.path))?.label || "Overview"}</strong></span><span className="instance-label">Glyph Hold 2</span></header>
        <main className="content-shell">{children}</main>
      </div>
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
    api<Dict>("/dashboard/api/overview")
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <div className="alert">{error}</div>;
  if (!data) return <div className="loading">Loading dashboard</div>;

  const stats = [
    {
      label: "Memories",
      value: data.memory_count,
      icon: BookOpen,
      path: "/dashboard/memories",
    },
    {
      label: "Secrets",
      value: data.secret_count,
      icon: Lock,
      path: "/dashboard/secrets",
    },
    {
      label: "Agent API keys",
      value: data.api_key_count,
      icon: KeyRound,
      path: "/dashboard/api-keys",
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Status"
        title="Overview"
        body="Manage durable agent memory, local secrets, API keys, and audit activity from one place."
      />
      <section className="stats-grid">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <button
              key={stat.label}
              className="stat-card"
              onClick={() => navigate(stat.path)}
            >
              <Icon size={22} />
              <span>{stat.label}</span>
              <strong>{stat.value}</strong>
              <ChevronRight size={18} />
            </button>
          );
        })}
        <div className="stat-card runtime-card status-card">
          <Activity size={22} />
          <span>Runtime</span>
          <dl className="runtime-list">
            <div>
              <dt>Version</dt>
              <dd>{data.version}</dd>
            </div>
            <div>
              <dt>Database</dt>
              <dd>
                <Badge
                  tone={data.database_status === "ok" ? "success" : "danger"}
                >
                  {data.database_status}
                </Badge>
              </dd>
            </div>
            <div>
              <dt>Secrets</dt>
              <dd>
                <Badge tone={data.secrets_enabled ? "success" : "warning"}>
                  {data.secrets_enabled ? "enabled" : "disabled"}
                </Badge>
              </dd>
            </div>
          </dl>
        </div>
      </section>
      <section className="panel activity-panel">
        <div className="panel-heading">
          <h2>Recent Activity</h2>
          <Button tone="ghost" onClick={() => navigate("/dashboard/activity")}>
            View all
          </Button>
        </div>
        <EventList events={data.recent_events || []} compact />
      </section>
    </>
  );
}

function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [defaultScopes, setDefaultScopes] = useState<string[]>([]);
  const [createdKey, setCreatedKey] = useState("");
  const [confirmDisable, setConfirmDisable] = useState<ApiKey | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    name: "",
    actor: "",
    description: "",
    scopes: [] as string[],
  });

  async function load() {
    const data = await api<{ default_scopes: string[]; keys: ApiKey[] }>(
      "/dashboard/api/api-keys",
    );
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
      const data = await api<{ id: string; value: string }>(
        "/dashboard/api/api-keys",
        {
          method: "POST",
          body: JSON.stringify(form),
        },
      );
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
        title="Agent API keys"
        body="Create scoped bearer keys, then assign their default space and grants in Spaces & access before connecting an agent."
      />
      {error && <div className="alert">{error}</div>}
      {createdKey && (
        <div className="secret-once">
          <div>
            <strong>Copy this API key now</strong>
            <span>It will not be shown again. <a href="/dashboard/spaces">Set its space access</a> before connecting an agent.</span>
          </div>
          <code>{createdKey}</code>
          <Button
            icon={Copy}
            onClick={() => navigator.clipboard.writeText(createdKey)}
          >
            Copy key
          </Button>
        </div>
      )}
      <section className="resource-grid">
        <div className="panel resource-panel">
          <div className="panel-heading">
            <div>
              <h2>Existing keys</h2>
              <p>Review active and disabled agent credentials.</p>
            </div>
            <ResultCount count={keys.length} noun="key" />
          </div>
          {keys.length === 0 ? (
            <EmptyState
              title="No API keys"
              body="Create a key before connecting an agent."
              icon={KeyRound}
            />
          ) : (
            <div className="api-key-list">
              {keys.map((key) => (
                <article
                  className={`api-key-row ${key.enabled ? "" : "disabled"}`}
                  key={key.id}
                >
                  <div className="api-key-main">
                    <div>
                      <strong>{key.name}</strong>
                      <span>{key.description || "No description"}</span>
                    </div>
                    <Badge tone={key.enabled ? "success" : "danger"}>
                      {key.enabled ? "enabled" : "disabled"}
                    </Badge>
                  </div>
                  <dl className="api-key-meta">
                    <div>
                      <dt>Actor</dt>
                      <dd>{key.actor}</dd>
                    </div>
                    <div>
                      <dt>Prefix</dt>
                      <dd>
                        <code>{key.key_prefix}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>Created</dt>
                      <dd>{key.created_at}</dd>
                    </div>
                    <div>
                      <dt>Last used</dt>
                      <dd>{key.last_used_at || "Never"}</dd>
                    </div>
                  </dl>
                  <div className="tag-row">
                    {key.scopes.map((scope) => (
                      <Badge key={scope}>{scope}</Badge>
                    ))}
                  </div>
                  <div className="row-actions">
                    {key.enabled ? (
                      <Button
                        tone="danger"
                        onClick={() => setConfirmDisable(key)}
                      >
                        Disable
                      </Button>
                    ) : (
                      <Button tone="secondary" onClick={() => enable(key)}>
                        Enable
                      </Button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
        <form className="panel stack side-panel compact-form" onSubmit={create}>
          <div className="panel-heading">
            <div>
              <h2>Create key</h2>
              <p>Use scoped keys for agents and integrations.</p>
            </div>
          </div>
          <Field label="Name">
            <input
              value={form.name}
              placeholder="Local agent"
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </Field>
          <Field label="Actor">
            <input
              value={form.actor}
              placeholder="local-agent"
              onChange={(e) => setForm({ ...form, actor: e.target.value })}
              required
            />
          </Field>
          <Field label="Description">
            <input
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
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
  const [creating, setCreating] = useState(false);
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
    try {
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
    setCreating(false);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create category"); }
  }

  return (
    <>
      <PageHeader
        eyebrow="Taxonomy"
        title="Categories"
        body="Classify what a memory describes. Spaces and connection grants control access; categories organise content."
        action={<Button icon={Plus} onClick={() => setCreating(true)}>New category</Button>}
      />
      {error && <div className="alert">{error}</div>}
      <section>
        {creating && <Modal title="Create category" onClose={() => setCreating(false)}>{error && <div className="alert">{error}</div>}<form className="stack" onSubmit={create}>
          <Field label="Name">
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </Field>
          <Field label="Description">
            <textarea
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
          </Field>
          <Button icon={Plus}>Create category</Button>
        </form></Modal>}
        <div className="panel">
          <div className="panel-heading">
            <h2>Available categories</h2>
          </div>
          <div className="category-grid">
            {categoriesList.map((category) => (
              <div className="category-card" key={category.id}>
                <strong>{category.name}</strong>
                <p>{category.description}</p>

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
    const data = await api<{ events: Dict[] }>(
      `/dashboard/api/activity?${params}`,
    );
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
          className="filters activity-filters"
          onSubmit={(event) => {
            event.preventDefault();
            load().catch((err) => setError(err.message));
          }}
        >
          <input
            placeholder="Filter by agent or user"
            aria-label="Filter activity by actor"
            value={filters.actor}
            onChange={(e) => setFilters({ ...filters, actor: e.target.value })}
          />
          <input
            placeholder="Event type, e.g. memory.create"
            aria-label="Filter activity by event type"
            value={filters.event_type}
            onChange={(e) =>
              setFilters({ ...filters, event_type: e.target.value })
            }
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

function EventList({
  events,
  compact = false,
}: {
  events: Dict[];
  compact?: boolean;
}) {
  if (!events.length) {
    return (
      <EmptyState
        title="No activity yet"
        body="Events appear as dashboard users and agents act."
        icon={Activity}
      />
    );
  }
  return (
    <div className={`event-list ${compact ? "compact" : ""}`}>
      {events.map((event) => (
        <div className="event-row" key={event.id}>
          <Badge tone={event.success ? "success" : "danger"}>
            {(event.event_type || "event").replace(/[._]/g, " ")}
          </Badge>
          <div>
            <strong>{event.message || event.target_id || event.action}</strong>
            <span>
              {event.actor || "Unknown actor"} · {new Date(event.created_at).toLocaleString()}
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
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          autoFocus
        />
        <div className="button-row">
          <Button
            tone="danger"
            icon={Trash2}
            onClick={() =>
              onConfirm(value).catch((err) => setError(err.message))
            }
          >
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
    api<Session>("/dashboard/api/session")
      .then(setSession)
      .catch((err) => setError(err.message));
  }, []);

  async function logout() {
    await api("/dashboard/api/logout", { method: "POST" });
    setSession(await api<Session>("/dashboard/api/session"));
    navigate("/login");
  }

  const page = useMemo(() => {
    if (!session?.has_admin)
      return <AuthPage mode="setup" onSession={setSession} />;
    if (!session.user) return <AuthPage mode="login" onSession={setSession} />;
    if (path === "/dashboard/memory-reviews") return <MemoryReviewsPage />;
    if (path.startsWith("/dashboard/memories/")) {
      return (
        <MemoryRecord id={path.split("/").pop() || ""} navigate={navigate} />
      );
    }
    if (path.startsWith("/dashboard/memories"))
      return <MemoryLibrary navigate={navigate} />;
    if (path.startsWith("/dashboard/spaces")) return <SpacesPage />;
    if (path.startsWith("/dashboard/settings")) return <SettingsPage />;
    if (path.startsWith("/dashboard/migration")) return <MigrationPage />;
    if (path.startsWith("/dashboard/secrets")) return <SecretLibrary />;
    if (path.startsWith("/dashboard/api-keys")) return <ApiKeysPage />;
    if (path.startsWith("/dashboard/categories")) return <CategoriesPage />;
    if (path.startsWith("/dashboard/activity")) return <ActivityPage />;
    return <OverviewPage navigate={navigate} />;
  }, [session, path]);

  if (error)
    return (
      <main className="auth-shell">
        <div className="alert">{error}</div>
      </main>
    );
  if (!session)
    return (
      <main className="auth-shell">
        <div className="loading">Loading Glyph Hold</div>
      </main>
    );
  if (!session.has_admin || !session.user) return page;

  return (
    <Shell session={session} path={path} navigate={navigate} onLogout={logout}>
      {page}
    </Shell>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
