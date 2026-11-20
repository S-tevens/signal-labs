// Users and roles: the administrator's screen. Every change is audited by the platform with who made it.
import React, { useEffect, useState } from "react";
import { request } from "./api";

const ROLE_HELP = {
  viewer: "Reads the fleet, incidents, evidence and proof.",
  auditor: "Everything a viewer can, plus the audit log. Cannot act.",
  operator: "Responds to incidents: AI summaries and simulated actions.",
  admin: "Everything, plus users, roles and collector enrollment.",
};

function phrase() {
  const words = ["amber", "river", "signal", "harbor", "copper", "meadow", "lantern", "falcon", "cedar", "orbit", "velvet", "summit"];
  const pick = () => words[crypto.getRandomValues(new Uint32Array(1))[0] % words.length];
  return `${pick()}-${pick()}-${pick()}-${crypto.getRandomValues(new Uint32Array(1))[0] % 90 + 10}`;
}

function when(iso) {
  if (!iso) return "Never";
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (s < 90) return "Just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export default function UsersAdmin() {
  const [list, setList] = useState(null);
  const [roles, setRoles] = useState(["viewer", "auditor", "operator", "admin"]);
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [reset, setReset] = useState({ user: null, password: "" });
  const [form, setForm] = useState({ username: "", display_name: "", role: "viewer", temporary_password: phrase() });

  async function load() {
    try {
      const [users, matrix, session] = await Promise.all([request("/v1/users"), request("/v1/rbac"), request("/v1/session")]);
      setList(users);
      setRoles(Object.keys(matrix.roles));
      setMe(session.user);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => { load(); }, []);

  async function change(username, body, message) {
    setBusy(username);
    setNote("");
    setError("");
    try {
      await request(`/v1/users/${encodeURIComponent(username)}`, { method: "PATCH", body });
      setNote(message);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }

  async function submitReset(e) {
    e.preventDefault();
    setBusy(reset.user);
    setError("");
    try {
      await request(`/v1/users/${encodeURIComponent(reset.user)}/password`, { method: "POST", body: { temporary_password: reset.password } });
      setNote(`Password reset for ${reset.user}. Share the temporary password with them privately. They sign in and must choose a new one. Their other sessions have ended.`);
      setReset({ user: null, password: "" });
      await load();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setBusy("");
    }
  }

  async function create(e) {
    e.preventDefault();
    setBusy("new");
    setError("");
    try {
      await request("/v1/users", { method: "POST", body: form });
      setNote(`${form.display_name} can sign in now with the temporary password you set, and must choose a new one at first sign-in.`);
      setForm({ username: "", display_name: "", role: "viewer", temporary_password: phrase() });
      await load();
    } catch (e2) {
      setError(e2.message);
    } finally {
      setBusy("");
    }
  }

  if (!list && error) return <section className="users-page"><p className="users-error" role="alert">{error}</p></section>;
  if (!list) return <section className="users-page"><p className="muted">Loading users…</p></section>;
  return (
    <section className="users-page">
      {error && <p className="users-error" role="alert">{error}</p>}
      {note && <p className="users-note" role="status">{note}</p>}
      <div className="users-card">
        <h2>People in your organization</h2>
        <div className="users-table-wrap">
          <table className="users-table">
            <thead><tr><th>Person</th><th>Role</th><th>Status</th><th>Last sign-in</th><th>Actions</th></tr></thead>
            <tbody>
              {list.map((u) => (
                <tr key={u.username} className={u.active ? undefined : "row-offline"}>
                  <td><strong>{u.display_name}</strong><small>{u.username}{u.username === me ? " (you)" : ""}</small></td>
                  <td>
                    <select value={u.role} disabled={busy === u.username} aria-label={`Role for ${u.display_name}`}
                      onChange={(e) => change(u.username, { role: e.target.value }, `${u.display_name} is now ${e.target.value}. It applies on their next action, with no new sign-in.`)}>
                      {roles.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>
                    {u.active ? <span className="users-chip ok">Active</span> : <span className="users-chip off">Disabled</span>}
                    {u.locked && <span className="users-chip warn">Locked</span>}
                    {u.must_change_password && <span className="users-chip warn">Temporary password</span>}
                  </td>
                  <td>{when(u.last_login)}</td>
                  <td className="users-actions">
                    <button type="button" className="button small secondary" disabled={busy === u.username || u.username === me}
                      title={u.username === me ? "You cannot disable your own account" : undefined}
                      onClick={() => change(u.username, { active: !u.active }, `${u.display_name} ${u.active ? "is disabled and signed out" : "can sign in again"}.`)}>
                      {u.active ? "Disable" : "Enable"}
                    </button>
                    <button type="button" className="button small secondary" onClick={() => setReset({ user: u.username, password: phrase() })}>Reset password</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {reset.user && (
          <form className="users-inline" onSubmit={submitReset}>
            <label>Temporary password for <strong>{reset.user}</strong>
              <input value={reset.password} onChange={(e) => setReset({ ...reset, password: e.target.value })} minLength={10} required spellCheck="false" />
            </label>
            <button className="button small" type="submit" disabled={busy === reset.user}>Reset and sign out everywhere</button>
            <button className="button small secondary" type="button" onClick={() => setReset({ user: null, password: "" })}>Cancel</button>
          </form>
        )}
      </div>
      <div className="users-grid">
        <form className="users-card" onSubmit={create}>
          <h2>Add a person</h2>
          <label>Full name<input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required maxLength={80} /></label>
          <label>Username<input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value.toLowerCase() })} required pattern="[a-z0-9][a-z0-9._\-]{1,39}" title="Lower-case letters, digits, dot, dash or underscore" spellCheck="false" /></label>
          <label>Role
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {roles.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label>Temporary password
            <span className="users-pw">
              <input value={form.temporary_password} onChange={(e) => setForm({ ...form, temporary_password: e.target.value })} minLength={10} required spellCheck="false" />
              <button type="button" className="button small secondary" onClick={() => setForm({ ...form, temporary_password: phrase() })}>New</button>
            </span>
          </label>
          <button className="button" type="submit" disabled={busy === "new"}>Add person</button>
        </form>
        <div className="users-card">
          <h2>What each role can do</h2>
          <dl className="users-roles">
            {roles.map((r) => <React.Fragment key={r}><dt>{r}</dt><dd>{ROLE_HELP[r] || ""}</dd></React.Fragment>)}
          </dl>
          <p className="muted">Changes apply to the person's next action and are recorded in the audit log with your name.</p>
        </div>
      </div>
    </section>
  );
}
