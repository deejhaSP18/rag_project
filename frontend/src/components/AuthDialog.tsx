import { useEffect, useRef, useState, type FormEvent } from "react";

interface Props {
  onSubmit: (username: string, password: string, register: boolean) => Promise<void>;
  onClose: () => void;
}

export function AuthDialog({ onSubmit, onClose }: Props) {
  const [register, setRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSubmit(username, password, register);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal" onSubmit={submit} aria-labelledby="auth-title">
        <h2 id="auth-title">{register ? "Create an account" : "Sign in"}</h2>
        <p className="modal-sub">
          {register ? "Your conversations will follow you across browsers." : "Admins can manage documents and indexing."}
        </p>
        <label>Username
          <input ref={first} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label>Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={register ? "new-password" : "current-password"} required minLength={register ? 8 : 1} />
        </label>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="btn-primary" type="submit" disabled={busy}>{busy ? "Please wait…" : register ? "Create account" : "Sign in"}</button>
        <button className="link-btn" type="button" onClick={() => { setRegister(!register); setError(""); }}>
          {register ? "Have an account? Sign in" : "New here? Create an account"}
        </button>
      </form>
    </div>
  );
}
