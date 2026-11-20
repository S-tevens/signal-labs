// Sign-in, the signed-in user's menu and the forced password change.
// The session token lives in sessionStorage (it ends with the tab) and carries only who the person is. Their role is read
// by the platform on every request, so a change by an administrator applies immediately.
import React, { useEffect, useRef, useState } from "react";
import { LIVE, isSignedIn, login, logout, request, saveSession } from "./api";

const LAST_TENANT = "signal-labs-last-tenant";
const remembered = () => {
  try { return localStorage.getItem(LAST_TENANT) || ""; } catch { return ""; }
};

export function AuthGate({ children }) {
  const [signedIn, setSignedIn] = useState(!LIVE || isSignedIn());
  const [session, setSession] = useState(null);
  useEffect(() => {
    const out = () => { setSignedIn(false); setSession(null); };
    window.addEventListener("signal-signed-out", out);
    return () => window.removeEventListener("signal-signed-out", out);
  }, []);
  useEffect(() => {
    if (!LIVE || !signedIn) return;
    request("/v1/session").then(setSession).catch(() => {});
  }, [signedIn]);
  if (!LIVE) return children;
  if (!signedIn) return <Login onSignedIn={() => setSignedIn(true)} />;
  if (session?.must_change_password) {
    return <ChangePassword forced onDone={() => { setSession(null); request("/v1/session").then(setSession); }} />;
  }
  return children;
}

function Field({ label, children }) {
  return <label className="auth-field"><span>{label}</span>{children}</label>;
}

function Login({ onSignedIn }) {
  const [tenant, setTenant] = useState(remembered() || "t-acme");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(tenant.trim(), username.trim(), password);
      try { localStorage.setItem(LAST_TENANT, tenant.trim()); } catch { /* remembering the organization is optional */ }
      onSignedIn();
    } catch (err) {
      setError(err.message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={submit} aria-labelledby="auth-title">
        <h1 id="auth-title">Sign in to Signal Labs</h1>
        <p className="auth-sub">Secure observability that keeps your raw data on your side.</p>
        <Field label="Organization">
          <input value={tenant} onChange={(e) => setTenant(e.target.value)} autoComplete="organization" required spellCheck="false" />
        </Field>
        <Field label="Username">
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus spellCheck="false" />
        </Field>
        <Field label="Password">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </Field>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="button" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="auth-foot">Your administrator creates your account and sets your role.</p>
      </form>
    </main>
  );
}

export function ChangePassword({ forced = false, onDone, onCancel }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setError("");
    if (next !== again) { setError("The two new passwords do not match."); return; }
    setBusy(true);
    try {
      const res = await request("/v1/me/password", { method: "POST", body: { current_password: current, new_password: next } });
      saveSession({ token: res.token, expires_at: res.expires_at, user: res.user });
      onDone?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  const card = (
    <form className="auth-card" onSubmit={submit} aria-labelledby="pw-title">
      <h1 id="pw-title">{forced ? "Choose a new password" : "Change password"}</h1>
      <p className="auth-sub">{forced ? "Your administrator gave you a temporary password. Replace it to continue." : "Other devices will be signed out."}</p>
      <Field label={forced ? "Temporary password" : "Current password"}>
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required autoFocus />
      </Field>
      <Field label="New password (at least 10 characters)">
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required minLength={10} />
      </Field>
      <Field label="New password again">
        <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required minLength={10} />
      </Field>
      {error && <p className="auth-error" role="alert">{error}</p>}
      <div className="auth-actions">
        <button className="button" type="submit" disabled={busy}>{busy ? "Saving…" : "Save password"}</button>
        {forced ? <button type="button" className="button secondary" onClick={logout}>Sign out</button> : <button type="button" className="button secondary" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
  return forced ? <main className="auth-page">{card}</main> : <div className="auth-modal" role="dialog" aria-modal="true">{card}</div>;
}

// The avatar in the top bar: who is signed in, their role, and the two things a person can do about it.
export function UserMenu() {
  const [info, setInfo] = useState(null);
  const [open, setOpen] = useState(false);
  const [changing, setChanging] = useState(false);
  const ref = useRef(null);
  useEffect(() => { request("/v1/session").then(setInfo).catch(() => {}); }, []);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (e.type === "keydown" ? e.key === "Escape" : !ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  const name = info?.display_name || info?.user || "Signed in";
  const initial = (name[0] || "?").toUpperCase();
  return (
    <div className="user-menu" ref={ref}>
      <button type="button" className="top-avatar" aria-haspopup="menu" aria-expanded={open} aria-label={`Account menu for ${name}`} onClick={() => setOpen(!open)}>{initial}</button>
      {open && (
        <div className="user-menu-panel" role="menu">
          <div className="user-menu-who"><strong>{name}</strong><span>{info?.role ? `${info.role} · ${info.tenant_id}` : ""}</span></div>
          {info?.user ? (
            <>
              <button type="button" role="menuitem" onClick={() => { setOpen(false); setChanging(true); }}>Change password</button>
              <button type="button" role="menuitem" onClick={logout}>Sign out</button>
            </>
          ) : (
            <p className="user-menu-note">Using an API token. Sign in with a user account to manage your password.</p>
          )}
        </div>
      )}
      {changing && <ChangePassword onDone={() => setChanging(false)} onCancel={() => setChanging(false)} />}
    </div>
  );
}
