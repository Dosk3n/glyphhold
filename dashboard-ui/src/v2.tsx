import React, { FormEvent, useEffect, useState } from "react";
import {
  BookOpen,
  BrainCircuit,
  FolderOpen,
  KeyRound,
  Plus,
  RefreshCw,
  Settings,
  ShieldCheck,
  Upload,
} from "lucide-react";

type Row = Record<string, any>;
export async function v2api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  const csrf = document.cookie
    .split("; ")
    .find((c) => c.startsWith("glyphhold_csrf="))
    ?.split("=")[1];
  if (csrf && !["GET", "HEAD"].includes(options.method || "GET"))
    headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  const response = await fetch(
    path.startsWith("/") ? path : `/api/v2/${path}`,
    { credentials: "same-origin", ...options, headers },
  );
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : JSON.stringify(data?.detail || `HTTP ${response.status}`),
    );
  return data;
}
const send = (path: string, body: any, method = "POST") =>
  v2api(path, {
    method,
    headers:
      method === "POST"
        ? {
            "Idempotency-Key":
              globalThis.crypto?.randomUUID?.() ||
              `${Date.now()}-${Math.random()}`,
          }
        : undefined,
    body: JSON.stringify(body),
  });
const items = (data: any, key: string): Row[] =>
  Array.isArray(data) ? data : data?.[key] || [];
const message = (e: any) => e?.message || "The request failed.";
const pretty = (value: any) => JSON.stringify(value, null, 2);
const stamp = (value: string) =>
  value ? new Date(value).toLocaleString() : "Not yet";
function Heading({
  title,
  body,
  icon: Icon = FolderOpen,
  action,
}: {
  title: string;
  body: string;
  icon?: any;
  action?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">
          <Icon size={14} /> GLYPH HOLD 2
        </span>
        <h1>{title}</h1>
        <p>{body}</p>
      </div>
      {action && <div className="page-action">{action}</div>}
    </header>
  );
}
function CreateDialog({title, onClose, children}: {title: string; onClose: () => void; children: React.ReactNode}) {
  const ref = React.useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className="modal create-dialog" aria-label={title} onCancel={onClose} onClose={onClose}>
    <div className="modal-header"><h2>{title}</h2><Button type="button" secondary onClick={onClose}>Close</Button></div>
    {children}
  </dialog>;
}

function Field({
  name,
  children,
  hint,
}: {
  name: string;
  children: React.ReactNode;
  hint?: string;
}) {
  const labelId = React.useId();
  const control = React.isValidElement(children)
    ? React.cloneElement(children as React.ReactElement<any>, {
        "aria-labelledby": labelId,
        "aria-describedby": hint ? `${labelId}-hint` : undefined,
      })
    : children;
  return (
    <label className="field">
      <span id={labelId}>{name}</span>
      {control}
      {hint && <small id={`${labelId}-hint`}>{hint}</small>}
    </label>
  );
}
function Button({
  children,
  secondary,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { secondary?: boolean }) {
  return (
    <button className={`btn ${secondary ? "secondary" : "primary"}`} {...props}>
      {children}
    </button>
  );
}
function Notice({ error, success }: { error?: string; success?: string }) {
  return (
    <>
      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}
      {success && (
        <div className="v2-success" role="status">
          {success}
        </div>
      )}
    </>
  );
}
function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="empty-state">
      <BookOpen size={26} />
      <p>{children}</p>
    </div>
  );
}
function SpaceSelect({
  spaces,
  value,
  onChange,
  all,
  ...accessibility
}: {
  spaces: Row[];
  value: string;
  onChange: (id: string) => void;
  all?: boolean;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
}) {
  return (
    <select
      {...accessibility}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {all && <option value="">All permitted spaces</option>}
      {spaces.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name}
        </option>
      ))}
    </select>
  );
}

export function SpacesPage() {
  const [editingSpace, setEditingSpace] = useState<Row | null>(null);
  const [spaces, setSpaces] = useState<Row[]>([]),
    [keys, setKeys] = useState<Row[]>([]),
    [guidance, setGuidance] = useState<Row[]>([]);
  const [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  const [form, setForm] = useState({ name: "", description: "" }),
    [selected, setSelected] = useState(""),
    [connection, setConnection] = useState<Row | null>(null);
  const [statement, setStatement] = useState(""),
    [spaceId, setSpaceId] = useState("");
  async function load() {
    const [cap, k, g] = await Promise.all([
      v2api("capabilities"),
      v2api("/dashboard/api/api-keys"),
      v2api("guidance"),
    ]);
    setSpaces(cap.spaces);
    setKeys(k.keys);
    setGuidance(items(g, "guidance"));
    setSpaceId(
      (current) => current || cap.default_space_id || cap.spaces[0]?.id || "",
    );
  }
  useEffect(() => {
    load().catch((e) => setError(message(e)));
  }, []);
  useEffect(() => {
    setConnection(null);
    if (selected)
      v2api(`connections/${selected}`)
        .then(setConnection)
        .catch((e) => setError(message(e)));
  }, [selected]);
  async function perform(fn: () => Promise<any>, text: string) {
    setError("");
    setSuccess("");
    try {
      await fn();
      await load();
      setSuccess(text);
    } catch (e) {
      setError(message(e));
    }
  }
  return (
    <>
      <Heading
        title="Spaces & access"
        body="Give every memory a home. Connection defaults guide agents; grants control what they can access."
      />
      <Notice error={error} success={success} />
      <section className="v2-two-column">
        <div className="panel stack">
          <div className="panel-heading">
            <h2>Your spaces</h2>
            <span className="badge">{spaces.length} spaces</span>
          </div>
          {spaces.map((s) => (
            <div className="v2-space-card" key={s.id}>
              <FolderOpen size={23} />
              <div>
                <strong>{s.name}</strong>
                <p>{s.description || "No description yet."}</p>
                <small>{s.id}</small>
              </div>
              <div className="stack">
                <span className="badge">
                  {s.can_write ? "Read & write" : "Read"}
                </span>
                <Button secondary onClick={() => setEditingSpace({ ...s })}>
                  Edit
                </Button>
              </div>
            </div>
          ))}
          <form
            className="stack v2-section"
            onSubmit={(e) => {
              e.preventDefault();
              perform(async () => {
                await send("spaces", form);
                setForm({ name: "", description: "" });
              }, "Space created.");
            }}
          >
            <h3>Create a space</h3>
            <Field name="Name">
              <input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Work, Personal, General…"
              />
            </Field>
            <Field
              name="Description"
              hint="Explain what belongs here. Advanced Memory uses these definitions."
            >
              <textarea
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
              />
            </Field>
            <Button>
              <Plus size={16} />
              Create space
            </Button>
          </form>
        </div>
        <div className="panel stack">
          <h2>Connection permissions</h2>
          <p className="muted">
            Choose an API key to set its normal space and explicit access.
            General requires a grant too.
          </p>
          <Field name="Connection">
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">Choose an API key</option>
              {keys.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name} · {k.actor}
                </option>
              ))}
            </select>
          </Field>
          {connection && (
            <form
              className="stack"
              onSubmit={(e) => {
                e.preventDefault();
                perform(
                  () =>
                    send(
                      `connections/${selected}`,
                      {
                        default_space_id: connection.default_space_id,
                        grants: connection.grants,
                      },
                      "PUT",
                    ),
                  "Connection access saved.",
                );
              }}
            >
              <Field name="Default space">
                <SpaceSelect
                  all
                  spaces={spaces}
                  value={connection.default_space_id || ""}
                  onChange={(id) =>
                    setConnection({ ...connection, default_space_id: id })
                  }
                />
              </Field>
              <div className="v2-grants">
                <div className="v2-grant-row">
                  <strong>Space</strong>
                  <strong>Read</strong>
                  <strong>Write</strong>
                </div>
                {spaces.map((s) => {
                  const grant = (connection.grants || []).find(
                    (g: Row) => g.space_id === s.id,
                  ) || { space_id: s.id, can_read: false, can_write: false };
                  const toggle = (field: string, checked: boolean) => {
                    const next = { ...grant, [field]: checked };
                    if (field === "can_write" && checked) next.can_read = true;
                    if (field === "can_read" && !checked)
                      next.can_write = false;
                    setConnection({
                      ...connection,
                      grants: [
                        ...(connection.grants || []).filter(
                          (g: Row) => g.space_id !== s.id,
                        ),
                        next,
                      ],
                    });
                  };
                  return (
                    <div className="v2-grant-row" key={s.id}>
                      <span>{s.name}</span>
                      {["can_read", "can_write"].map((f) => (
                        <input
                          key={f}
                          type="checkbox"
                          aria-label={`${s.name} ${f === "can_read" ? "read" : "write"} access`}
                          checked={!!grant[f]}
                          onChange={(e) => toggle(f, e.target.checked)}
                        />
                      ))}
                    </div>
                  );
                })}
              </div>
              <Button>
                <ShieldCheck size={16} />
                Save access
              </Button>
            </form>
          )}
        </div>
      </section>
      {editingSpace && (
        <div className="modal-backdrop">
          <form
            className="modal stack"
            role="dialog"
            aria-modal="true"
            aria-label="Edit space"
            onSubmit={(e) => {
              e.preventDefault();
              perform(async () => {
                await send(
                  `spaces/${editingSpace.id}`,
                  {
                    name: editingSpace.name,
                    description: editingSpace.description,
                  },
                  "PATCH",
                );
                setEditingSpace(null);
              }, "Space updated.");
            }}
          >
            <div className="panel-heading">
              <h2>Edit space</h2>
              <Button
                secondary
                type="button"
                onClick={() => setEditingSpace(null)}
              >
                Close
              </Button>
            </div>
            <Field name="Name">
              <input
                required
                value={editingSpace.name}
                onChange={(e) =>
                  setEditingSpace({ ...editingSpace, name: e.target.value })
                }
              />
            </Field>
            <Field name="Description">
              <textarea
                value={editingSpace.description || ""}
                onChange={(e) =>
                  setEditingSpace({
                    ...editingSpace,
                    description: e.target.value,
                  })
                }
              />
            </Field>
            <Button>Save space</Button>
          </form>
        </div>
      )}
      <section className="panel stack v2-section">
        <div>
          <h2>Confirmed placement guidance</h2>
          <p className="muted">
            Record associations you have confirmed. These guide classification
            without granting access.
          </p>
        </div>
        {guidance.length ? (
          guidance.map((g) => (
            <div className="v2-guidance" key={g.id}>
              <div>
                <strong>{g.statement}</strong>
                <small>
                  {spaces.find((s) => s.id === g.space_id)?.name || g.space_id}{" "}
                  · {g.confirmed ? "Confirmed" : "Suggested"}
                </small>
              </div>
              <Button
                secondary
                onClick={() =>
                  perform(
                    () => v2api(`guidance/${g.id}`, { method: "DELETE" }),
                    "Guidance removed.",
                  )
                }
              >
                Remove
              </Button>
            </div>
          ))
        ) : (
          <Empty>No placement guidance yet.</Empty>
        )}
        <form
          className="v2-inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            perform(async () => {
              await send("guidance", {
                statement,
                space_id: spaceId,
                confirmed: true,
              });
              setStatement("");
            }, "Confirmed guidance added.");
          }}
        >
          <Field name="Space">
            <SpaceSelect
              spaces={spaces}
              value={spaceId}
              onChange={setSpaceId}
            />
          </Field>
          <Field name="Confirmed association">
            <input
              required
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              placeholder="Luxury Leisure operational systems belong in Work."
            />
          </Field>
          <Button>Add guidance</Button>
        </form>
      </section>
    </>
  );
}

export function MemoryLibrary({
  navigate,
}: {
  navigate: (path: string) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [offset, setOffset] = useState(0),
    [hasMore, setHasMore] = useState(false);
  const [spaces, setSpaces] = useState<Row[]>([]),
    [categories, setCategories] = useState<Row[]>([]),
    [memories, setMemories] = useState<Row[]>([]),
    [space, setSpace] = useState("");
  const [query, setQuery] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const empty = {
    title: "",
    summary: "",
    body: "",
    category_id: "",
    space_id: "",
    tags: "",
    auto_prefetch_level: "normal",
  };
  const [form, setForm] = useState(empty);
  async function load(selected = space, search = query, pageOffset = 0) {
    const data = search
      ? await send("search", {
          query: search,
          space_id: selected || undefined,
          broaden: !selected,
          limit: 100,
          max_chars: 100000,
        })
      : await v2api(
          `memories?limit=100&offset=${pageOffset}${selected ? `&space_id=${encodeURIComponent(selected)}` : ""}`,
        );
    const rows = items(data, "memories").length
      ? items(data, "memories")
      : items(data, "results");
    setMemories((current) => (pageOffset ? [...current, ...rows] : rows));
    setOffset(pageOffset);
    setHasMore(!search && rows.length === 100);
  }
  useEffect(() => {
    Promise.all([v2api("capabilities"), v2api("/dashboard/api/categories")])
      .then(async ([cap, cats]) => {
        setSpaces(cap.spaces);
        setCategories(cats);
        setForm((f) => ({
          ...f,
          category_id: cats[0]?.id || "",
          space_id: cap.default_space_id || cap.spaces[0]?.id || "",
        }));
        await load();
      })
      .catch((e) => setError(message(e)));
  }, []);
  async function create(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const memory = await send("memories", {
        ...form,
        tags: form.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      setForm({
        ...empty,
        category_id: form.category_id,
        space_id: form.space_id,
      });
      navigate(`/dashboard/memories/${memory.memory?.id || memory.id}`);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Memories"
        body="Search durable knowledge across permitted spaces. Open a record to inspect its evidence and history."
        icon={BookOpen}
        action={<Button onClick={() => setCreating(true)}><Plus size={15} /> New memory</Button>}
      />
      <Notice error={error} />
      <section className="memory-library-layout">
        <div className="panel resource-panel">
          <div className="panel-heading">
            <h2>Memory library</h2>
            <span className="badge">{memories.length} records</span>
          </div>
          <form
            className="filters resource-filters"
            onSubmit={(e) => {
              e.preventDefault();
              setError("");
              load().catch((e) => setError(message(e)));
            }}
          >
            <input
              aria-label="Search memories"
              placeholder="Search memories…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <SpaceSelect
              spaces={spaces}
              value={space}
              all
              onChange={(id) => {
                setSpace(id);
                load(id).catch((e) => setError(message(e)));
              }}
            />
            <Button secondary>Search</Button>
          </form>
          {!memories.length ? (
            <Empty>No memories found. Add context or adjust your search.</Empty>
          ) : (
            <div className="list-table">
              {memories.map((m) => (
                <button
                  key={m.id}
                  className="list-row resource-row"
                  onClick={() => navigate(`/dashboard/memories/${m.id}`)}
                >
                  <div className="row-main">
                    <strong>{m.title}</strong>
                    <span>{m.summary || m.body?.slice(0, 160)}</span>
                  </div>
                  <div className="row-meta memory-metadata">
                    <div className="memory-badges"><span className="badge">
                      {spaces.find((s) => s.id === m.space_id)?.name ||
                        m.space_id}
                    </span>
                    {m.record_type && m.record_type !== "fact" && (
                      <span className="badge">{m.record_type}</span>
                    )}
                    {m.stale ? (
                      <span className="badge danger">Needs refresh</span>
                    ) : null}
                    </div>
                    <small className="memory-updated">
                      v{m.version} · <time dateTime={m.updated_at}>{stamp(m.updated_at)}</time>
                    </small>
                  </div>
                </button>
              ))}
            </div>
          )}
          {hasMore && (
            <Button
              secondary
              onClick={() =>
                load(space, query, offset + 100).catch((e) =>
                  setError(message(e)),
                )
              }
            >
              Load more memories
            </Button>
          )}
        </div>
        {creating && <CreateDialog title="Create memory" onClose={() => setCreating(false)}><Notice error={error} /><form className="stack compact-form" onSubmit={create}>
          <Field name="Owning space">
            <SpaceSelect
              spaces={spaces.filter((s) => s.can_write)}
              value={form.space_id}
              onChange={(id) => setForm({ ...form, space_id: id })}
            />
          </Field>
          <Field name="Category">
            <select
              value={form.category_id}
              onChange={(e) =>
                setForm({ ...form, category_id: e.target.value })
              }
            >
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          {(["title", "summary", "body", "tags"] as const).map((f) => (
            <Field
              key={f}
              name={f[0].toUpperCase() + f.slice(1)}
              hint={f === "tags" ? "Separate tags with commas." : undefined}
            >
              {f === "body" ? (
                <textarea
                  required
                  value={form[f]}
                  onChange={(e) => setForm({ ...form, [f]: e.target.value })}
                />
              ) : (
                <input
                  required={f === "title"}
                  value={form[f]}
                  onChange={(e) => setForm({ ...form, [f]: e.target.value })}
                />
              )}
            </Field>
          ))}
          <Field name="Recall priority">
            <select
              value={form.auto_prefetch_level}
              onChange={(e) =>
                setForm({ ...form, auto_prefetch_level: e.target.value })
              }
            >
              {["never", "low", "normal", "high", "pinned"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </Field>
          <Button disabled={busy}>
            {busy ? "Creating…" : "Create memory"}
          </Button>
        </form></CreateDialog>}
      </section>
    </>
  );
}

const advancedBase = "/dashboard/api/advanced";
export function SettingsPage() {
  const [tab, setTab] = useState(window.location.hash === "#secrets" ? "secrets" : "advanced");
  return (
    <>
      <Heading
        title="Settings"
        body="Optional integrations extend Glyph Hold. Core memory works without an AI subscription or an external vault."
        icon={Settings}
      />
      <div className="v2-tabs" role="tablist" aria-label="Settings sections">
        <button
          role="tab"
          aria-selected={tab === "advanced"}
          onClick={() => setTab("advanced")}
        >
          <BrainCircuit size={18} />
          Advanced Memory
        </button>
        <button
          role="tab"
          aria-selected={tab === "secrets"}
          onClick={() => setTab("secrets")}
        >
          <KeyRound size={18} />
          Secret storage
        </button>
        <button role="tab" aria-selected={tab === "access"} onClick={() => setTab("access")}>Agent access</button>
      </div>
      <div className="settings-content">
        {tab === "advanced" ? <AdvancedSettings /> : tab === "secrets" ? <SecretProviderSettings /> : <section className="panel stack"><h2>Agent access</h2><p className="muted">Each agent connects with its own API key. Its default space guides recall and saves; explicit permissions control which other spaces it can read or write. Secret access is granted separately.</p><div className="button-row"><a className="btn secondary" href="/dashboard/api-keys">Manage agent API keys</a><a className="btn secondary" href="/dashboard/spaces">Manage space permissions</a></div></section>}
      </div>
    </>
  );
}
function AdvancedSettings() {
  const [config, setConfig] = useState<Row | null>(null),
    [status, setStatus] = useState<Row>({}),
    [spaces, setSpaces] = useState<Row[]>([]),
    [jobs, setJobs] = useState<Row[]>([]);
  const [error, setError] = useState(""),
    [success, setSuccess] = useState(""),
    [busy, setBusy] = useState(false);
  async function refresh() {
    await Promise.all([
      v2api(`${advancedBase}/settings`).then(c => {setConfig(c); window.dispatchEvent(new Event("glyphhold:memory-reviews-changed"));}),
      v2api(`${advancedBase}/status`).then(setStatus),
      v2api("capabilities").then((cap) => setSpaces(cap.spaces)),
      v2api(`${advancedBase}/jobs`).then((data) =>
        setJobs(items(data, "jobs")),
      ),
    ]);
  }
  useEffect(() => {
    refresh().catch((e) => setError(message(e)));
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => {
      Promise.all([
        v2api(`${advancedBase}/status`),
        v2api(`${advancedBase}/jobs`),
      ])
        .then(([s, j]) => {
          setStatus(s);
          setJobs(items(j, "jobs"));
        })
        .catch((e) => setError(message(e)));
    }, 6000);
    return () => clearInterval(timer);
  }, []);
  async function action(fn: () => Promise<any>, text: string, reload = true) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
      if (reload) await refresh();
      setSuccess(text);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const update = (key: string, value: any) =>
    setConfig((c) => ({ ...c, [key]: value }));
  if (!config)
    return (
      <>
        <Notice error={error} />
        <div className="loading">Loading Advanced Memory settings…</div>
      </>
    );
  const options = (count: number) =>
    Array.from({ length: count }, (_, n) => (
      <option key={n} value={n}>
        {String(n).padStart(2, "0")}
      </option>
    ));
  const login = status.login || {};
  return (
    <>
      <Notice error={error} success={success} />
      <div className="v2-two-column">
        <form
          className="panel stack"
          onSubmit={(e) => {
            e.preventDefault();
            action(
              () =>
                send(
                  `${advancedBase}/settings`,
                  Object.fromEntries(
                    Object.entries(config).filter(
                      ([key]) =>
                        !["next_run", "generation", "paused_reason"].includes(
                          key,
                        ),
                    ),
                  ),
                  "PUT",
                ),
              "Advanced Memory settings saved.",
            );
          }}
        >
          <div className="v2-toggle-heading">
            <div>
              <h2>Advanced Memory</h2>
              <p className="muted">
                An AI reviews saved knowledge, maintains profiles and proposes
                evidence-backed improvements.
              </p>
            </div>
            <label className="v2-switch">
              <input
                type="checkbox"
                checked={!!config.enabled}
                onChange={(e) => update("enabled", e.target.checked)}
                aria-label="Enable Advanced Memory"
              />
              <span />
            </label>
          </div>
          <details className="advanced-help"><summary>What Advanced Memory does</summary><p>Your connected AI reviews saved knowledge, updates profiles from their sources and proposes improvements. Original memories remain recoverable. Changes between spaces require review, and unchanged knowledge does not trigger an AI call.</p></details>
          <div className="v2-callout">
            {config.enabled
              ? "Enabled when saved. Scheduled jobs use your connected Codex allowance."
              : "Off by default. Memory storage and recall work normally without background consolidation."}
          </div>
          <fieldset className="v2-fieldset">
            <legend>Permitted spaces</legend>
            <div className="scope-grid">
              {spaces.map((s) => (
                <label className="check-card" key={s.id}>
                  <input
                    type="checkbox"
                    checked={(config.space_ids || []).includes(s.id)}
                    onChange={(e) =>
                      update(
                        "space_ids",
                        e.target.checked
                          ? [...(config.space_ids || []), s.id]
                          : (config.space_ids || []).filter(
                              (id: string) => id !== s.id,
                            ),
                      )
                    }
                  />
                  <span>{s.name}</span>
                </label>
              ))}
            </div>
            <small className="muted">
              Existing-record moves require review. Uncertainty never routes a
              memory into General.
            </small>
          </fieldset>
          <div className="v2-section stack">
            <h3>Schedule</h3>
            <div className="form-row">
              <Field name="Frequency">
                <select
                  value={config.frequency}
                  onChange={(e) => update("frequency", e.target.value)}
                >
                  {["hourly", "daily", "weekly"].map((f) => (
                    <option key={f} value={f}>
                      {f[0].toUpperCase() + f.slice(1)}
                    </option>
                  ))}
                </select>
              </Field>
              {config.frequency === "weekly" && (
                <Field name="Day">
                  <select
                    value={config.weekday}
                    onChange={(e) => update("weekday", Number(e.target.value))}
                  >
                    {[
                      "Monday",
                      "Tuesday",
                      "Wednesday",
                      "Thursday",
                      "Friday",
                      "Saturday",
                      "Sunday",
                    ].map((d, i) => (
                      <option value={i} key={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
            </div>
            <div className="form-row">
              {config.frequency !== "hourly" && (
                <Field name="Hour">
                  <select
                    value={config.hour}
                    onChange={(e) => update("hour", Number(e.target.value))}
                  >
                    {options(24)}
                  </select>
                </Field>
              )}
              <Field
                name={
                  config.frequency === "hourly"
                    ? "Minute past each hour"
                    : "Minute"
                }
              >
                <select
                  value={config.minute}
                  onChange={(e) => update("minute", Number(e.target.value))}
                >
                  {options(60)}
                </select>
              </Field>
            </div>
            <Field
              name="Timezone"
              hint="Uses local scheduled time and accounts for daylight saving."
            >
              <input
                required
                list="gh-timezones"
                value={config.timezone}
                onChange={(e) => update("timezone", e.target.value)}
              />
              <datalist id="gh-timezones">
                {[
                  "Europe/London",
                  "UTC",
                  "Europe/Paris",
                  "America/New_York",
                  "America/Chicago",
                  "America/Los_Angeles",
                  "Asia/Tokyo",
                  "Australia/Sydney",
                ].map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </Field>
          </div>
          <div className="v2-section stack">
            <h3>Model & allowance</h3>
            <Field
              name="Codex model"
              hint="Choose a model available to your subscription. A smaller model can conserve allowance."
            >
              <select
                value={config.model || ""}
                onChange={(e) => update("model", e.target.value)}
              >
                <option value="">Codex default</option>
                {config.model && !(status.models || []).some((m: any) => (m.id || m) === config.model) && (
                  <option value={config.model}>{config.model} (saved model)</option>
                )}
                {(status.models || []).filter((m: any) => typeof m === "string" ? m : m.id).map((m: any) => (
                  <option key={m.id || m} value={m.id || m}>
                    {m.label || m.id || m}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              name="Reasoning level"
              hint="Available levels depend on the chosen model. Unsupported combinations are reported by the worker."
            >
              <select
                value={config.reasoning || "low"}
                onChange={(e) => update("reasoning", e.target.value)}
              >
                {(status.reasoning_levels?.length
                  ? status.reasoning_levels
                  : ["low", "medium", "high", "xhigh"]
                ).map((v: any) => (
                  <option key={v.id || v} value={v.id || v}>
                    {v.label || v}
                  </option>
                ))}
              </select>
            </Field>
            <details className="advanced-limits"><summary>Batch and resource limits</summary><div className="stack">
            <div className="form-row">
              <Field name="Memories per batch">
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={config.batch_size}
                  onChange={(e) => update("batch_size", Number(e.target.value))}
                />
              </Field>
              <Field name="Run timeout (seconds)">
                <input
                  type="number"
                  min="30"
                  max="900"
                  value={config.timeout_seconds}
                  onChange={(e) =>
                    update("timeout_seconds", Number(e.target.value))
                  }
                />
              </Field>
            </div>
            <Field name="Maximum context characters">
              <input
                type="number"
                min="4000"
                max="200000"
                value={config.max_context_chars}
                onChange={(e) =>
                  update("max_context_chars", Number(e.target.value))
                }
              />
            </Field>
            </div></details>
            <Field name="Apply policy">
              <select
                value={config.execution_policy}
                onChange={(e) => update("execution_policy", e.target.value)}
              >
                <option value="review">Review every proposed change</option>
                <option value="automatic">
                  Automatically apply permitted reversible changes
                </option>
              </select>
            </Field>
          </div>
          <Button disabled={busy}>Save settings</Button>
        </form>
        <div className="stack">
          <section className="panel stack">
            <div className="panel-heading">
              <h2>Codex connection</h2>
              <span
                className={`badge ${status.authenticated ? "success" : "neutral"}`}
              >
                {status.authenticated ? "Connected" : "Sign-in required"}
              </span>
            </div>
            <p className="muted">
              Use your ChatGPT subscription through the official Codex CLI on
              this server. No API credits required.
            </p>
            {status.paused_reason && (
              <div className="alert">{status.paused_reason}</div>
            )}
            <dl className="v2-status">
              <div>
                <dt>CLI</dt>
                <dd>{status.installed ? "Installed" : "Unavailable"}</dd>
              </div>
              <div>
                <dt>Authentication</dt>
                <dd>{status.auth_mode || "Not connected"}</dd>
              </div>
              <div>
                <dt>Worker</dt>
                <dd>
                  {jobs.some((j) => (j.state || j.status) === "running")
                    ? "Processing"
                    : status.worker_running
                      ? "Idle"
                      : "Stopped"}
                </dd>
              </div>
              <div>
                <dt>Next run</dt>
                <dd>
                  {status.next_run || config.next_run
                    ? stamp(status.next_run || config.next_run)
                    : "Not scheduled"}
                  <small>{config.timezone}</small>
                </dd>
              </div>
            </dl>
            {login.state && login.state !== "idle" && (
              <div className="v2-callout">
                <strong>{login.state}</strong>
                <p>{login.message}</p>
                {login.url && /^https:\/\//.test(login.url) && (
                  <a href={login.url} target="_blank" rel="noreferrer">
                    Open official sign-in page ↗
                  </a>
                )}
                {login.code && (
                  <div className="v2-device-code">
                    <code>{login.code}</code>
                    <Button
                      secondary
                      type="button"
                      onClick={() => navigator.clipboard.writeText(login.code)}
                    >
                      Copy
                    </Button>
                  </div>
                )}
              </div>
            )}
            <div className="button-row">
              {!status.authenticated ? (
                <Button
                  type="button"
                  disabled={busy || !status.installed}
                  onClick={() =>
                    action(
                      () => send(`${advancedBase}/auth/login`, {}),
                      "Sign-in started. Follow the instructions above.",
                    )
                  }
                >
                  Connect Codex
                </Button>
              ) : (
                <Button
                  secondary
                  disabled={busy}
                  onClick={() =>
                    action(
                      () => send(`${advancedBase}/auth/logout`, {}),
                      "Codex disconnected.",
                    )
                  }
                >
                  Disconnect
                </Button>
              )}
              {["pending", "running", "waiting"].includes(login.state) && (
                <Button
                  secondary
                  onClick={() =>
                    action(
                      () => send(`${advancedBase}/auth/cancel`, {}),
                      "Sign-in cancelled.",
                    )
                  }
                >
                  Cancel sign-in
                </Button>
              )}
              <Button
                secondary
                onClick={() => action(refresh, "Status refreshed.", false)}
              >
                <RefreshCw size={15} />
                Refresh
              </Button>
            </div>
          </section>
          <section className="panel stack"><h2>Memory reviews</h2><p className="muted">Review suggestions, start a review and manage previous runs on the Memory reviews page.</p><a className="btn secondary" href="/dashboard/memory-reviews">Open memory reviews</a></section>
        </div>
      </div>
    </>
  );
}

export function MemoryReviewsPage() {
  const [config, setConfig] = useState<Row | null>(null), [status, setStatus] = useState<Row>({}), [spaces, setSpaces] = useState<Row[]>([]), [jobs, setJobs] = useState<Row[]>([]), [proposals, setProposals] = useState<Row[]>([]);
  const [error, setError] = useState(""), [success, setSuccess] = useState(""), [busy, setBusy] = useState(false), [detail, setDetail] = useState<Row | null>(null), [fullReview, setFullReview] = useState(false);
  async function refresh() {
    const [c, s, cap, j, p] = await Promise.all([v2api(`${advancedBase}/settings`), v2api(`${advancedBase}/status`), v2api("capabilities"), v2api(`${advancedBase}/jobs`), v2api(`${advancedBase}/proposals`)]);
    setConfig(c); setStatus(s); setSpaces(cap.spaces); setJobs(items(j, "jobs")); setProposals(items(p, "proposals"));
  }
  useEffect(() => { refresh().catch(e => setError(message(e))); const timer = window.setInterval(() => refresh().catch(e => setError(message(e))), 6000); return () => clearInterval(timer); }, []);
  async function action(fn: () => Promise<any>, text: string, reload = true) {
    setBusy(true); setError(""); setSuccess("");
    try { await fn(); if(reload) await refresh(); window.dispatchEvent(new Event("glyphhold:memory-reviews-changed")); setSuccess(text); } catch(e) { setError(message(e)); } finally { setBusy(false); }
  }
  const proposalState = (p: Row) => p.state || p.status || "pending";
  if(!config) return <><Notice error={error}/><div className="loading">Loading memory reviews…</div></>;
  return <><Heading title="Memory reviews" body="Review suggested improvements, approve changes and manage Advanced Memory runs." icon={BrainCircuit} /><div className="settings-content memory-activity">
    <Notice error={error} success={success}/>
    <div className="v2-callout">Review changes to your memories here. Configure the AI connection, model and schedule in <a href="/dashboard/settings">Settings</a>.</div>
      <section className="panel stack v2-section">
        <h2>Proposed improvements</h2>
        {!proposals.length ? (
          <Empty>No proposals to review.</Empty>
        ) : (
          proposals.map((p) => (
            <article className="v2-proposal" key={p.id}>
              <div className="panel-heading">
                <h3>
                  {p.operation ||
                    p.payload?.operation ||
                    p.type ||
                    p.kind ||
                    "Memory improvement"}
                </h3>
                <span className="badge">{proposalState(p)}</span>
              </div>
              <p>
                {p.reason ||
                  p.reasoning ||
                  p.explanation ||
                  p.question ||
                  p.payload?.reason}
              </p>
              {p.payload?.title && <h4>{p.payload.title}</h4>}
              {p.payload?.body && (
                <p className="v2-proposed-body">{p.payload.body}</p>
              )}
              {p.payload?.uncertainty && (
                <div className="v2-callout">{p.payload.uncertainty}</div>
              )}
              {p.payload?.destination_space_id && (
                <p>
                  Proposed destination:{" "}
                  <strong>
                    {spaces.find((s) => s.id === p.payload.destination_space_id)
                      ?.name || p.payload.destination_space_id}
                  </strong>
                </p>
              )}
              {p.payload?.operation === "move" && <div className="v2-callout"><strong>Subject links change on approval</strong><p>Existing subject links will be replaced with the destination links listed below. Memory history is retained.</p>{p.payload.subject_ids?.length ? <div className="tag-row">{p.payload.subject_ids.map((sid: string) => <code key={sid}>{sid}</code>)}</div> : <p>No destination subject links. You can assign destination subjects after the move.</p>}</div>}
              {p.payload?.operation === "question" && (
                <p>
                  <a href="/dashboard/spaces">Add confirmed guidance</a>, then
                  dismiss this question and run another review.
                </p>
              )}
              <details>
                <summary>Evidence & proposed changes</summary>
                <pre className="v2-json">{pretty(p)}</pre>
              </details>
              {["pending", "proposed"].includes(proposalState(p)) && (
                <div className="button-row">
                  {p.payload?.operation !== "question" && (
                    <Button
                      disabled={busy || !config.enabled}
                      onClick={() =>
                        action(
                          () =>
                            send(
                              `${advancedBase}/proposals/${p.id}/approve`,
                              {},
                            ),
                          "Proposal approved.",
                        )
                      }
                    >
                      Approve
                    </Button>
                  )}
                  <Button
                    secondary
                    disabled={busy}
                    onClick={() =>
                      action(
                        () =>
                          send(`${advancedBase}/proposals/${p.id}/reject`, {}),
                        "Proposal rejected.",
                      )
                    }
                  >
                    Reject
                  </Button>
                </div>
              )}
            </article>
          ))
        )}
      </section>
          <section className="panel stack">
            <h2>Run a review</h2>
            <p className="muted">
              Only changed knowledge is processed. A run without relevant
              changes skips the AI call.
            </p>
            <label className="check-card">
              <input
                type="checkbox"
                checked={fullReview}
                onChange={(e) => setFullReview(e.target.checked)}
              />
              <span>Review existing memories too</span>
            </label>
            <Button
              disabled={busy || !config.enabled || !status.authenticated}
              onClick={() =>
                action(
                  () =>
                    send(`${advancedBase}/jobs`, { full_review: fullReview }),
                  "Memory review queued.",
                )
              }
            >
              Run now
            </Button>
            <small className="muted">
              Reviews use the saved Advanced Memory settings. If allowance or authentication is
              unavailable, jobs remain pending without switching to API billing.
            </small>
          </section>
      <section className="panel stack v2-section">
        <h2>Run history</h2>
        {!jobs.length ? (
          <Empty>No Advanced Memory runs yet.</Empty>
        ) : (
          jobs.map((j) => (
            <div className="v2-run" key={j.id}>
              <div>
                <strong>{j.status || j.state}</strong>
                <small>
                  {stamp(j.created_at || j.started_at)} ·{" "}
                  {j.model || "Codex default"}
                </small>
                {j.error && <p className="v2-error-text">{j.error}</p>}
              </div>
              <div className="button-row">
                <Button
                  secondary
                  onClick={() =>
                    action(
                      async () =>
                        setDetail(await v2api(`${advancedBase}/jobs/${j.id}`)),
                      "",
                      false,
                    )
                  }
                >
                  Details
                </Button>
                {["queued", "running", "pending"].includes(
                  j.state || j.status,
                ) && (
                  <Button
                    secondary
                    onClick={() =>
                      action(
                        () => send(`${advancedBase}/jobs/${j.id}/cancel`, {}),
                        "Run cancelled.",
                      )
                    }
                  >
                    Cancel
                  </Button>
                )}
                {["paused", "failed", "blocked", "cancelled"].includes(
                  j.state || j.status,
                ) && (
                  <Button
                    secondary
                    onClick={() =>
                      action(
                        () => send(`${advancedBase}/jobs/${j.id}/resume`, {}),
                        "Run resumed.",
                      )
                    }
                  >
                    Resume
                  </Button>
                )}
              </div>
            </div>
          ))
        )}
      </section>
      {detail && (
        <CreateDialog title="Run details" onClose={() => setDetail(null)}><pre className="v2-json">{pretty(detail)}</pre></CreateDialog>
      )}
  </div></>;
}

function SecretProviderSettings() {
  const base = "/dashboard/api/providers/secrets";
  const [config, setConfig] = useState<Row | null>(null), [folders, setFolders] = useState<Row[]>([]);
  const [error, setError] = useState(""), [success, setSuccess] = useState(""), [busy, setBusy] = useState(false), [folderName, setFolderName] = useState("");
  async function load() {
    const c = await v2api(base);
    setConfig({...c, client_id: "", client_secret: "", master_password: ""});
  }
  useEffect(() => {
    load().catch((e) => setError(message(e)));
  }, []);
  async function action(fn: () => Promise<any>, text: string) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
      setSuccess(text);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const update = (k: string, v: any) => setConfig((c) => ({ ...c, [k]: v }));
  if (!config)
    return (
      <>
        <Notice error={error} />
        <div className="loading">Loading secret provider…</div>
      </>
    );
  return (
    <>
      <Notice error={error} success={success} />
      <section className="v2-two-column">
        <form
          className="panel stack"
          onSubmit={(e) => {
            e.preventDefault();
            action(async () => {
              const payload = { ...config };
              delete payload.client_secret_configured;
              delete payload.master_password_configured;
              if (!payload.client_secret) delete payload.client_secret;
              if (!payload.master_password) delete payload.master_password;
              await send(base, payload, "PUT");
              await load();
            }, "Secret provider settings saved.");
          }}
        >
          <div className="v2-toggle-heading">
            <div>
              <h2>Bitwarden / Vaultwarden</h2>
              <p className="muted">
                Search and use your Bitwarden or Vaultwarden secrets directly.
              </p>
            </div>
            <label className="v2-switch">
              <input
                type="checkbox"
                checked={!!config.enabled}
                onChange={(e) => update("enabled", e.target.checked)}
                aria-label="Enable external secret provider"
              />
              <span />
            </label>
          </div>
          <div className="v2-callout">
            {config.enabled
              ? "Vaultwarden is selected. All accessible vault items are available directly; existing built-in secrets remain accessible."
              : "Built-in encrypted secret storage is active."}
          </div>
          <Field name="Server URL">
            <input
              type="url"
              value={config.server_url || ""}
              placeholder="https://vault.example.com"
              onChange={(e) => update("server_url", e.target.value)}
            />
          </Field>
          <Field
            name="Personal API client ID"
            hint={
              config.client_id_configured
                ? "A client ID is saved. Leave blank to retain it."
                : undefined
            }
          >
            <input
              autoComplete="off"
              value={config.client_id || ""}
              placeholder={
                config.client_id_configured ? "Saved client ID" : "user.…"
              }
              onChange={(e) => update("client_id", e.target.value)}
            />
          </Field>
          <Field
            name="Personal API client secret"
            hint={
              config.client_secret_configured
                ? "A secret is stored. Leave blank to retain it."
                : "Encrypted before storage."
            }
          >
            <input
              type="password"
              autoComplete="new-password"
              value={config.client_secret || ""}
              onChange={(e) => update("client_secret", e.target.value)}
              placeholder={
                config.client_secret_configured
                  ? "•••••••• (saved)"
                  : "Enter client secret"
              }
            />
          </Field>
          <Field
            name="Master password"
            hint={
              config.master_password_configured
                ? "A password is stored. Leave blank to retain it."
                : "Used to unlock your encrypted vault automatically."
            }
          >
            <input
              type="password"
              autoComplete="new-password"
              value={config.master_password || ""}
              onChange={(e) => update("master_password", e.target.value)}
              placeholder={
                config.master_password_configured
                  ? "•••••••• (saved)"
                  : "Enter master password"
              }
            />
          </Field>
          <label className="check-card">
            <input
              type="checkbox"
              checked={!!config.write_enabled}
              onChange={(e) => update("write_enabled", e.target.checked)}
            />
            <span>Allow creating and updating external vault items</span>
          </label>
          <div className="button-row">
            <Button disabled={busy}>Save provider settings</Button>
            <Button
              secondary
              type="button"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  const result = await send(`${base}/test`, {});
                  setSuccess(
                    result.message || "Vault connection and unlock succeeded.",
                  );
                }, "Vault connection and unlock succeeded.")
              }
            >
              Test saved connection
            </Button>
          </div>
          <small className="muted">
            Save your details before testing the connection. You can test while the integration is disabled. Credentials are encrypted using this installation’s persistent key.
            Secrets are shared independently of memory spaces. API key secret permissions control agent access.
          </small>
        </form>
        <section className="panel stack">
          <h2>Optional default folder</h2>
          <p className="muted">All accessible vault folders and unfiled items are searchable. Folders organise secrets independently of memory spaces.</p>
          <Button secondary disabled={busy || !config.enabled} onClick={() => action(async () => setFolders(items(await v2api(`${base}/folders`), "folders")), "Folders loaded.")}>Load vault folders</Button>
          <Field name="Default folder for new secrets" hint="An agent can choose a different folder when saving. Save changes using Save provider settings.">
            <select value={config.default_folder_id || ""} onChange={e => update("default_folder_id", e.target.value || null)}>
              <option value="">Unfiled</option>
              {config.default_folder_id && !folders.some(f => f.id === config.default_folder_id) && <option value={config.default_folder_id}>Saved folder — load folders to see its name</option>}
              {folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </Field>
          <form className="v2-inline-form" onSubmit={e => {e.preventDefault(); action(async () => { await send(`${base}/folders`, {name: folderName}); setFolderName(""); setFolders(items(await v2api(`${base}/folders`), "folders")); }, "Folder created.");}}>
            <Field name="New folder"><input required value={folderName} onChange={e => setFolderName(e.target.value)} /></Field>
            <Button disabled={busy || !config.enabled || !config.write_enabled}>Create folder</Button>
          </form>
          <p className="muted">Existing built-in secrets remain in Secrets. Agents can check for a matching vault item and transfer a secret directly, without exporting a plaintext file.</p>
        </section>
      </section>
    </>
  );
}

export function MemoryRecord({
  id,
  navigate,
}: {
  id: string;
  navigate: (path: string) => void;
}) {
  const [subjects, setSubjects] = useState<Row[]>([]),
    [subjectName, setSubjectName] = useState(""),
    [subjectKind, setSubjectKind] = useState("person");
  const [memory, setMemory] = useState<Row | null>(null),
    [form, setForm] = useState<Row>({}),
    [spaces, setSpaces] = useState<Row[]>([]),
    [categories, setCategories] = useState<Row[]>([]),
    [revisions, setRevisions] = useState<Row[]>([]);
  const [target, setTarget] = useState(""),
    [error, setError] = useState(""),
    [success, setSuccess] = useState(""),
    [busy, setBusy] = useState(false);
  async function load() {
    const [m, cap, c, r] = await Promise.all([
      v2api(`memories/${id}`),
      v2api("capabilities"),
      v2api("/dashboard/api/categories"),
      v2api(`memories/${id}/revisions`),
    ]);
    setMemory(m);
    setForm({
      category_id: m.category_id,
      title: m.title,
      summary: m.summary || "",
      body: m.body,
      tags: (m.tags || []).join(", "),
      subject_ids: m.subject_ids || [],
      auto_prefetch_level: m.auto_prefetch_level || "normal",
    });
    setSpaces(cap.spaces);
    setTarget(m.space_id);
    setCategories(c);
    setRevisions(r.revisions);
    setSubjects(
      items(
        await v2api(`subjects?space_id=${encodeURIComponent(m.space_id)}`),
        "subjects",
      ),
    );
  }
  useEffect(() => {
    setMemory(null);
    load().catch((e) => setError(message(e)));
  }, [id]);
  async function action(fn: () => Promise<any>, text: string) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
      await load();
      setSuccess(text);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  if (!memory)
    return (
      <>
        <Notice error={error} />
        <div className="loading">Loading memory…</div>
      </>
    );
  const refs = memory.source_refs || [];
  return (
    <>
      <Heading
        title={memory.title}
        body={`Owned by ${spaces.find((s) => s.id === memory.space_id)?.name || memory.space_id} · version ${memory.version} · ${memory.record_type || "memory"}`}
        icon={BookOpen}
      />
      <Notice error={error} success={success} />
      <Button secondary onClick={() => navigate("/dashboard/memories")}>
        ← All memories
      </Button>
      <section className="v2-two-column v2-section">
        <form
          className="panel stack"
          onSubmit={(e) => {
            e.preventDefault();
            action(
              () =>
                send(
                  `memories/${id}`,
                  {
                    ...form,
                    tags: form.tags
                      .split(",")
                      .map((t: string) => t.trim())
                      .filter(Boolean),
                    expected_version: memory.version,
                    change_reason: "Dashboard edit",
                  },
                  "PATCH",
                ),
              "Memory saved.",
            );
          }}
        >
          <h2>Edit memory</h2>
          <Field name="Category">
            <select
              value={form.category_id || ""}
              onChange={(e) =>
                setForm({ ...form, category_id: e.target.value })
              }
            >
              {categories.map((c) => (
                <option value={c.id} key={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          {["title", "summary", "body", "tags"].map((f) => (
            <Field key={f} name={f[0].toUpperCase() + f.slice(1)}>
              {f === "body" ? (
                <textarea
                  required
                  value={form[f]}
                  onChange={(e) => setForm({ ...form, [f]: e.target.value })}
                />
              ) : (
                <input
                  required={f === "title"}
                  value={form[f]}
                  onChange={(e) => setForm({ ...form, [f]: e.target.value })}
                />
              )}
            </Field>
          ))}
          <Field name="Recall priority">
            <select
              value={form.auto_prefetch_level}
              onChange={(e) =>
                setForm({ ...form, auto_prefetch_level: e.target.value })
              }
            >
              {["never", "low", "normal", "high", "pinned"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </Field>
          <fieldset className="v2-fieldset">
            <legend>Confirmed subjects</legend>
            <p className="muted">
              Attach this record to a known person, server or topic only when
              the evidence establishes the identity.
            </p>
            {subjects.length ? (
              <div className="scope-grid">
                {subjects.map((subject) => (
                  <label className="check-card" key={subject.id}>
                    <input
                      type="checkbox"
                      checked={(form.subject_ids || []).includes(subject.id)}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          subject_ids: e.target.checked
                            ? [...(form.subject_ids || []), subject.id]
                            : (form.subject_ids || []).filter(
                                (sid: string) => sid !== subject.id,
                              ),
                        })
                      }
                    />
                    <span>
                      {subject.name}
                      <small className="v2-block">
                        {subject.kind}
                        {subject.aliases?.length
                          ? ` · ${subject.aliases.join(", ")}`
                          : ""}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <small className="muted">
                No subjects registered in this space yet.
              </small>
            )}
          </fieldset>
          <div className="button-row">
            <Button disabled={busy}>Save memory</Button>
            <Button
              secondary
              type="button"
              disabled={busy}
              onClick={() =>
                action(
                  load,
                  "Latest version loaded. Unsaved edits have been replaced.",
                )
              }
            >
              Reload latest
            </Button>
          </div>
          <small className="muted">
            Saves check the version you opened. If another agent edits this
            memory, reload and reconcile your changes.
          </small>
        </form>
        <div className="stack">
          <section className="panel stack">
            <h2>Register a subject</h2>
            <p className="muted">
              Use a stable identity for a person, server or topic. Check
              existing subjects before creating another with a similar name.
            </p>
            <Field name="Subject name">
              <input
                value={subjectName}
                onChange={(e) => setSubjectName(e.target.value)}
              />
            </Field>
            <Field name="Subject kind">
              <select
                value={subjectKind}
                onChange={(e) => setSubjectKind(e.target.value)}
              >
                {[
                  "person",
                  "server",
                  "organisation",
                  "service",
                  "topic",
                  "project",
                ].map((kind) => (
                  <option key={kind}>{kind}</option>
                ))}
              </select>
            </Field>
            <Button
              secondary
              disabled={busy || !subjectName.trim()}
              onClick={async () => {
                setError("");
                setBusy(true);
                try {
                  const subject = await send("subjects", {
                    name: subjectName,
                    kind: subjectKind,
                    space_id: memory.space_id,
                    aliases: [],
                  });
                  setSubjects((current) => [...current, subject]);
                  setForm((current) => ({
                    ...current,
                    subject_ids: [...(current.subject_ids || []), subject.id],
                  }));
                  setSubjectName("");
                  setSuccess(
                    "Subject registered and selected. Save the memory to confirm its association.",
                  );
                } catch (e) {
                  setError(message(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Register & select subject
            </Button>
          </section>
          <section className="panel stack">
            <h2>Evidence & freshness</h2>
            <dl className="v2-status">
              <div>
                <dt>Last verified</dt>
                <dd>{stamp(memory.last_verified_at)}</dd>
              </div>
              <div>
                <dt>Last modified</dt>
                <dd>{stamp(memory.updated_at)}</dd>
              </div>
              <div>
                <dt>Derived state</dt>
                <dd>
                  {memory.stale ? "Needs refresh" : "Current"}
                  {memory.archived ? " · Archived" : ""}
                </dd>
              </div>
            </dl>
            <Button
              secondary
              disabled={busy}
              onClick={() =>
                action(
                  () =>
                    send(
                      `memories/${id}`,
                      {
                        expected_version: memory.version,
                        last_verified_at: new Date().toISOString(),
                        change_reason: "Explicitly verified by dashboard user",
                      },
                      "PATCH",
                    ),
                  "Memory marked verified.",
                )
              }
            >
              Mark verified now
            </Button>
            <h3>Supporting memories</h3>
            {refs.length ? (
              refs.map((r: Row, i: number) => (
                <button
                  className="v2-source-link"
                  key={r.id || r.memory_id || i}
                  onClick={() =>
                    navigate(`/dashboard/memories/${r.id || r.memory_id}`)
                  }
                >
                  {r.id || r.memory_id} · v{r.version}
                </button>
              ))
            ) : (
              <p className="muted">No derived source references.</p>
            )}
            <details>
              <summary>Provenance & metadata</summary>
              <pre className="v2-json">
                {pretty({
                  id: memory.id,
                  source: memory.source,
                  provenance: memory.provenance,
                  metadata: memory.metadata,
                })}
              </pre>
            </details>
          </section>
          <section className="panel stack">
            <h2>Owning space</h2>
            <p className="muted">
              Moving changes who can access this record. Its identity and
              history are retained.
            </p>
            <SpaceSelect
              spaces={spaces.filter((s) => s.can_write)}
              value={target}
              onChange={setTarget}
            />
            <Button
              secondary
              disabled={busy || target === memory.space_id}
              onClick={() => {
                if (
                  window.confirm(
                    memory.subject_ids?.length
                      ? "Move this memory to the selected space? Its access permissions will change. Move will remove the current space’s subject links; you can assign destination subjects afterwards. History is retained."
                      : "Move this memory to the selected space? Its access permissions will change.",
                  )
                )
                  action(
                    () =>
                      send(`memories/${id}/move`, {
                        space_id: target,
                        expected_version: memory.version,
                        ...(memory.subject_ids?.length ? { subject_ids: [] } : {}),
                      }),
                    "Memory moved.",
                  );
              }}
            >
              Move memory
            </Button>
            <Button
              secondary
              disabled={busy || !!memory.archived}
              onClick={() =>
                action(
                  () =>
                    send(`memories/${id}/archive`, {
                      expected_version: memory.version,
                    }),
                  "Memory archived. It remains in history.",
                )
              }
            >
              Archive memory
            </Button>
          </section>
        </div>
      </section>
      <section className="panel stack v2-section">
        <h2>Revision history</h2>
        {!revisions.length ? (
          <Empty>No previous revisions yet.</Empty>
        ) : (
          revisions.map((r) => {
            const snapshot =
              typeof r.snapshot === "string"
                ? JSON.parse(r.snapshot)
                : r.snapshot || r;
            return (
              <article className="v2-proposal" key={r.id}>
                <div className="panel-heading">
                  <div>
                    <strong>{snapshot.title || `Version ${r.version}`}</strong>
                    <small className="v2-block">
                      Version {r.version} · {stamp(r.created_at)} ·{" "}
                      {r.change_reason || r.reason || "Memory update"}
                    </small>
                  </div>
                  <Button
                    secondary
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          "Restore this revision as a new version?",
                        )
                      )
                        action(
                          () =>
                            send(`memories/${id}/restore`, {
                              revision_id: r.id,
                              expected_version: memory.version,
                            }),
                          "Revision restored as a new version.",
                        );
                    }}
                  >
                    Restore
                  </Button>
                </div>
                <details>
                  <summary>View revision</summary>
                  <pre className="v2-json">{pretty(snapshot)}</pre>
                </details>
              </article>
            );
          })
        )}
      </section>
    </>
  );
}

export function MigrationPage() {
  const [spaces, setSpaces] = useState<Row[]>([]),
    [namespace, setNamespace] = useState(""),
    [spaceId, setSpaceId] = useState("space_import_review"),
    [document, setDocument] = useState("");
  const [preview, setPreview] = useState<Row | null>(null),
    [result, setResult] = useState<Row | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    v2api("capabilities")
      .then((c) => setSpaces(c.spaces))
      .catch((e) => setError(message(e)));
  }, []);
  const invalidate = () => {
    setPreview(null);
    setResult(null);
  };
  async function run(apply: boolean) {
    setError("");
    setBusy(true);
    try {
      const payload = {
        namespace,
        space_id: spaceId || undefined,
        document: JSON.parse(document),
      };
      const r = await send(`migration/${apply ? "apply" : "preview"}`, payload);
      if (apply) setResult(r);
      else setPreview(r);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function exportData() {
    setError("");
    try {
      const data = await v2api("migration/export");
      const url = URL.createObjectURL(
        new Blob([pretty(data)], { type: "application/json" }),
      );
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = `glyphhold-export-${new Date().toISOString().slice(0, 10)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(message(e));
    }
  }
  return (
    <>
      <Heading
        title="Migration"
        body="Bring existing memories together with traceable imports and a preview before changes are applied."
        icon={Upload}
      />
      <Notice
        error={error}
        success={
          result
            ? `Import completed. ${result.new ?? Object.keys(result.mappings || {}).length} new records imported.`
            : ""
        }
      />
      <section className="v2-two-column">
        <form
          className="panel stack"
          onSubmit={(e) => {
            e.preventDefault();
            run(false);
          }}
        >
          <h2>Import memories</h2>
          <Field
            name="Source namespace"
            hint="A stable unique name for this installation. Reuse it when retrying an import to avoid duplicates."
          >
            <input
              required
              value={namespace}
              placeholder="home-glyphhold-v1"
              onChange={(e) => {
                setNamespace(e.target.value);
                invalidate();
              }}
            />
          </Field>
          <Field
            name="Destination space"
            hint="Import Review keeps uncertain ownership restricted until reviewed."
          >
            <SpaceSelect
              spaces={spaces}
              value={spaceId}
              onChange={(id) => {
                setSpaceId(id);
                invalidate();
              }}
            />
          </Field>
          <Field name="Choose a JSON export">
            <input
              type="file"
              accept=".json,application/json"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setDocument(await f.text());
                  invalidate();
                }
              }}
            />
          </Field>
          <Field name="Export document">
            <textarea
              className="v2-import-text"
              required
              value={document}
              placeholder='{"memories": [], "categories": [], "revisions": []}'
              onChange={(e) => {
                setDocument(e.target.value);
                invalidate();
              }}
            />
          </Field>
          <Button disabled={busy}>
            {busy ? "Checking…" : "Preview import"}
          </Button>
        </form>
        <section className="panel stack">
          <h2>Import preview</h2>
          {preview ? (
            <>
              <dl className="v2-status">
                {["total", "new", "existing", "conflicts"].map((k) => (
                  <div key={k}>
                    <dt>{k[0].toUpperCase() + k.slice(1)}</dt>
                    <dd>
                      {Array.isArray(preview[k])
                        ? preview[k].length
                        : (preview[k] ?? 0)}
                    </dd>
                  </div>
                ))}
              </dl>
              {preview.errors?.length > 0 && (
                <div className="alert">
                  <pre className="v2-json">{pretty(preview.errors)}</pre>
                </div>
              )}
              <details>
                <summary>Full preview</summary>
                <pre className="v2-json">{pretty(preview)}</pre>
              </details>
              <Button
                disabled={busy || !preview.can_apply || !!result}
                onClick={() => run(true)}
              >
                Apply reviewed import
              </Button>
              {result && (
                <details open>
                  <summary>Import results</summary>
                  <pre className="v2-json">{pretty(result)}</pre>
                </details>
              )}
            </>
          ) : (
            <Empty>Choose an export and preview it before importing.</Empty>
          )}
          <div className="v2-callout">
            Original records are retained by the source installation. Secret
            values require a separate, explicit transfer; they are excluded from
            memory exports.
          </div>
        </section>
      </section>
      <EncryptedSecretTransfer />
      <section className="panel v2-section">
        <div className="panel-heading">
          <div>
            <h2>Export this installation</h2>
            <p className="muted">
              Download memories, categories and revisions for migration.
            </p>
          </div>
          <Button secondary onClick={exportData}>
            Download export
          </Button>
        </div>
      </section>
    </>
  );
}

export function SecretLibrary() {
  const [creating, setCreating] = useState(false);
  const [secrets, setSecrets] = useState<Row[]>([]),
    [folders, setFolders] = useState<Row[]>([]),
    [activeProvider, setActiveProvider] = useState("builtin"),
    [fields, setFields] = useState<Record<string, string>>({}),
    [types, setTypes] = useState<string[]>([]),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("");
  const [error, setError] = useState(""),
    [success, setSuccess] = useState(""),
    [busy, setBusy] = useState(false),
    [revealed, setRevealed] = useState<Row | null>(null),
    [editing, setEditing] = useState<Row | null>(null),
    [value, setValue] = useState("");
  const [form, setForm] = useState({
    name: "",
    folder_id: "",
    description: "",
    value: "",
    value_type: "password",
  });
  async function load(space = filter, search = query) {
    const data = await v2api(`secrets?query=${encodeURIComponent(search)}${space ? `&provider_name=${encodeURIComponent(space)}` : ""}`);
    setSecrets(data.secrets);
    setTypes(data.value_types || ["text", "password", "api_key", "ssh_key"]);
    setActiveProvider(data.active_provider || "builtin");
    if (data.active_provider === "vaultwarden") setFolders(items(await v2api("secrets/folders"), "folders"));

  }
  useEffect(() => {
    load().catch((e) => setError(message(e)));
  }, []);
  useEffect(() => {
    if (!revealed) return;
    const timer = window.setTimeout(
      () => setRevealed(null),
      (revealed.expires_in_seconds || 60) * 1000,
    );
    return () => clearTimeout(timer);
  }, [revealed]);
  async function action(fn: () => Promise<any>, text = "") {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
      await load();
      setSuccess(text);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Secrets"
        body="Search your active secret provider and existing built-in secrets. Values are revealed only by an explicit action."
        icon={KeyRound}
        action={<Button onClick={() => setCreating(true)}><Plus size={15} /> New secret</Button>}
      />
      <Notice error={error} success={success} />
      <section className="secret-library-layout">
        <section className="panel resource-panel">
          <div className="panel-heading">
            <h2>Secrets</h2>
            <span className="badge">{secrets.length} secrets</span>
          </div>
          <form
            className="filters resource-filters"
            onSubmit={(e) => {
              e.preventDefault();
              action(() => load());
            }}
          >
            <input
              aria-label="Search secret metadata"
              placeholder="Search names, websites or hostnames…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select aria-label="Secret provider" value={filter} onChange={e => { setFilter(e.target.value); action(() => load(e.target.value)); }}>
              <option value="">All providers</option><option value="builtin">Built-in</option><option value="vaultwarden">Vaultwarden</option>
            </select>
            <Button secondary>Search</Button>
          </form>
          {!secrets.length ? (
            <Empty>
              No secrets in this view. New secrets use your active provider. Vaultwarden entries appear automatically when connected.
            </Empty>
          ) : (
            secrets.map((s) => (
              <article className="v2-proposal v2-section" key={s.id}>
                <div className="panel-heading">
                  <div>
                    <strong>{s.name}</strong>
                    <p className="muted">{s.description}</p>
                    {s.websites?.length > 0 && <p className="muted">{s.websites.join(" · ")}</p>}
                  </div>
                  <span className="badge">
                    {s.provider === "builtin" ? "Built-in" : "Vaultwarden"}
                  </span>
                </div>
                <div className="tag-row">
                  {s.provider === "vaultwarden" && <span className="badge">{s.folder_name || "Unfiled"}</span>}
                  <span className="badge">{s.value_type}</span>
                  <small className="muted">
                    {typeof s.version === "number" ? `v${s.version} · ` : ""}{s.updated_at ? stamp(s.updated_at) : ""}
                  </small>
                </div>
                {s.fields?.length > 0 && <Field name={`Field for ${s.name}`}><select value={fields[s.id] || s.default_field || ""} onChange={e => setFields({...fields, [s.id]: e.target.value})}><option value="">Choose a field</option>{s.fields.map((f: string) => <option key={f} value={f}>{f}</option>)}</select></Field>}
                <div className="button-row v2-section">
                  <Button
                    secondary
                    disabled={busy}
                    onClick={() =>
                      action(async () =>
                        setRevealed(await send(`secrets/${encodeURIComponent(s.id)}/reveal`, {field: fields[s.id] || s.default_field || undefined})),
                      )
                    }
                  >
                    Reveal
                  </Button>
                  <Button
                    secondary
                    disabled={busy}
                    onClick={() => {
                      setEditing({...s, selected_field: fields[s.id] || s.default_field || ""});
                      setValue("");
                    }}
                  >
                    Edit
                  </Button>
                  {!s.direct && <Button
                    secondary
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Remove the GH2 secret reference “${s.name}”? External vault items will be retained.`,
                        )
                      )
                        action(
                          () =>
                            v2api(
                              `secrets/${s.id}?expected_version=${s.version}`,
                              { method: "DELETE" },
                            ),
                          "Secret removed.",
                        );
                    }}
                  >
                    Remove
                  </Button>}
                </div>
              </article>
            ))
          )}
        </section>
        {creating && <CreateDialog title="Create secret" onClose={() => { setCreating(false); setForm(f => ({...f, value: ""})); }}><Notice error={error} /><form
          className="stack compact-form"
          onSubmit={(e) => {
            e.preventDefault();
            action(async () => {
              const {folder_id, ...rest} = form;
              await send("secrets", {...rest, ...(folder_id ? {folder_id: folder_id === "__unfiled" ? null : folder_id} : {})});
              setForm((f) => ({ ...f, name: "", value: "", description: "" }));
              setCreating(false);
            }, "Secret saved.");
          }}
        >
          {activeProvider === "vaultwarden" && <Field name="Folder (optional)"><select value={form.folder_id} onChange={e => setForm({...form, folder_id:e.target.value})}><option value="">Use configured default</option><option value="__unfiled">Unfiled</option>{folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></Field>}
          <Field name="Name">
            <input
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <Field name="Description">
            <input
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
          </Field>
          <Field name="Value type">
            <select
              value={form.value_type}
              onChange={(e) => setForm({ ...form, value_type: e.target.value })}
            >
              {types.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </Field>
          <Field name="Secret value">
            <textarea
              className="v2-secret-input"
              autoComplete="off"
              required
              value={form.value}
              onChange={(e) => setForm({ ...form, value: e.target.value })}
            />
          </Field>
          <small className="muted">
            New secrets use your configured provider. Existing built-in secrets remain available.
          </small>
          <Button disabled={busy}>Save secret</Button>
        </form></CreateDialog>}
      </section>
      {revealed && (
        <div className="modal-backdrop">
          <div
            className="modal stack"
            role="dialog"
            aria-modal="true"
            aria-label="Revealed secret"
          >
            <div className="panel-heading">
              <h2>{revealed.name}</h2>
              <Button secondary onClick={() => setRevealed(null)}>
                Close
              </Button>
            </div>
            <p className="muted">
              This display closes automatically after{" "}
              {revealed.expires_in_seconds || 60} seconds.
            </p>
            <pre className="v2-json">{revealed.value}</pre>
            <Button
              onClick={() => navigator.clipboard.writeText(revealed.value)}
            >
              Copy value
            </Button>
          </div>
        </div>
      )}
      {editing && (
        <div className="modal-backdrop">
          <form
            className="modal stack"
            role="dialog"
            aria-modal="true"
            aria-label="Edit secret"
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                await send(
                  `secrets/${encodeURIComponent(editing.id)}`,
                  {
                    expected_version: editing.version,
                    ...(editing.direct ? {field: editing.selected_field || undefined} : {description: editing.description || ""}),
                    ...(value ? { value } : {}),
                  },
                  "PATCH",
                );
                setEditing(null);
                setValue("");
              }, "Secret updated.");
            }}
          >
            <div className="panel-heading">
              <h2>Edit {editing.name}</h2>
              <Button secondary type="button" onClick={() => setEditing(null)}>
                Close
              </Button>
            </div>
            {editing.direct ? <Field name="Item field"><select required value={editing.selected_field} onChange={e => setEditing({...editing, selected_field:e.target.value})}><option value="">Choose a field</option>{(editing.fields || []).map((f:string) => <option key={f} value={f}>{f}</option>)}</select></Field> : <Field name="Description"><input value={editing.description || ""} onChange={e => setEditing({...editing, description:e.target.value})}/></Field>}
            <Field
              name="Replacement value"
              hint="Leave blank to retain the existing value."
            >
              <textarea
                className="v2-secret-input"
                autoComplete="off"
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            </Field>
            <Button disabled={busy}>Save changes</Button>
          </form>
        </div>
      )}
    </>
  );
}

function EncryptedSecretTransfer() {
  const [namespace, setNamespace] = useState(""),
    [password, setPassword] = useState(""),
    [packageData, setPackageData] = useState<Row | null>(null),
    [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState<Row | null>(null),
    [result, setResult] = useState<Row | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const resetPreview = () => {
    setPreview(null);
    setResult(null);
  };
  async function process(apply: boolean) {
    setError("");
    setBusy(true);
    try {
      const data = await send(
        `/dashboard/api/providers/secrets/migration/${apply ? "apply" : "preview"}`,
        { package: packageData, password, namespace },
      );
      if (apply) {
        setResult(data);
        setPassword("");
        setPackageData(null);
      } else setPreview(data);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel stack v2-section">
      <div>
        <h2>Transfer encrypted secrets</h2>
        <p className="muted">
          Import a password-protected secret transfer package separately from
          memories. Source vault credentials and secret values are never shown
          in the preview.
        </p>
      </div>
      <Notice
        error={error}
        success={result ? "Encrypted secret transfer completed." : ""}
      />
      <form
        className="v2-link-form"
        onSubmit={(e) => {
          e.preventDefault();
          process(false);
        }}
      >
        <Field name="Secret transfer package">
          <input
            type="file"
            required
            accept=".json,application/json"
            onChange={async (e) => {
              setError("");
              resetPreview();
              setPackageData(null);
              const f = e.target.files?.[0];
              if (!f) return;
              try {
                setPackageData(JSON.parse(await f.text()));
                setFileName(f.name);
              } catch {
                setError("Choose a valid encrypted JSON transfer package.");
              }
            }}
          />
        </Field>
        <Field
          name="Transfer password"
          hint="Used only for this transfer. Never saved in Settings."
        >
          <input
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              resetPreview();
            }}
          />
        </Field>
        <Field name="Source namespace">
          <input
            required
            placeholder="home-glyphhold-v1-secrets"
            value={namespace}
            onChange={(e) => {
              setNamespace(e.target.value);
              resetPreview();
            }}
          />
        </Field>
        <Button disabled={busy || !packageData}>Preview secret transfer</Button>
      </form>
      {preview && (
        <div className="stack">
          <div className="v2-callout">
            {preview.new ?? 0} new · {preview.existing ?? 0} already imported ·{" "}
            {Array.isArray(preview.conflicts)
              ? preview.conflicts.length
              : (preview.conflicts ?? 0)}{" "}
            conflicts · {fileName}
          </div>
          {preview.items?.length > 0 && (
            <div className="tag-row">
              {preview.items.map((i: Row, n: number) => (
                <span className="badge" key={n}>
                  {i.name} · {i.value_type}
                </span>
              ))}
            </div>
          )}
          <details>
            <summary>Transfer preview</summary>
            <pre className="v2-json">{pretty(preview)}</pre>
          </details>
          <Button
            disabled={
              busy ||
              !!result ||
              !packageData ||
              (preview.conflicts?.length || 0) > 0 ||
              preview.can_apply === false
            }
            onClick={() => process(true)}
          >
            Apply reviewed secret transfer
          </Button>
        </div>
      )}
    </section>
  );
}
