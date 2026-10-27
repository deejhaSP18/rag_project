import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SettingItem } from "../api/types";

type Draft = Record<string, number | string | boolean>;

export function SettingsPanel() {
  const [items, setItems] = useState<SettingItem[]>([]);
  const [draft, setDraft] = useState<Draft>({});
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const adopt = (list: SettingItem[]) => {
    setItems(list);
    setDraft(Object.fromEntries(list.map((s) => [s.key, s.value])));
  };

  useEffect(() => {
    api.getSettings().then(adopt).catch((e) => setError(e instanceof Error ? e.message : "Could not load settings"));
  }, []);

  const dirty = items.filter((s) => draft[s.key] !== s.value);

  const change = (key: string, value: number | string | boolean) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [key]: value }));
  };

  const run = async (action: () => Promise<SettingItem[]>) => {
    setBusy(true);
    setError("");
    try {
      adopt(await action());
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const save = () => run(() => api.saveSettings(Object.fromEntries(dirty.map((s) => [s.key, draft[s.key]]))));

  return (
    <section className="admin" aria-label="Model and retrieval settings">
      <div className="admin-head">
        <div>
          <h2>Model &amp; retrieval</h2>
          <p>Changes apply to the next question, no restart needed. They are saved and survive restarts.</p>
        </div>
        <button className="btn-ghost" type="button" disabled={busy || !items.some((s) => s.changed)}
          onClick={() => void run(() => api.resetSettings())}>Reset all to defaults</button>
      </div>

      {error && <div className="form-error" role="alert">{error}</div>}

      <div className="settings">
        {items.map((s) => (
          <div className="setting" key={s.key}>
            <div className="setting-text">
              <label htmlFor={s.key}>{s.label}{s.changed && <b className="badge indexing">changed</b>}</label>
              <p>{s.help}</p>
              <small>default {String(s.default)}</small>
            </div>
            <div className="setting-control">
              {s.kind === "bool" ? (
                <label className="switch">
                  <input id={s.key} type="checkbox" checked={Boolean(draft[s.key])} onChange={(e) => change(s.key, e.target.checked)} />
                  <span>{draft[s.key] ? "On" : "Off"}</span>
                </label>
              ) : s.kind === "model" ? (
                <select id={s.key} value={String(draft[s.key] ?? "")} onChange={(e) => change(s.key, e.target.value)}>
                  {s.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <>
                  <input type="range" aria-label={s.label} min={s.min} max={s.max} step={s.step}
                    value={Number(draft[s.key] ?? 0)} onChange={(e) => change(s.key, Number(e.target.value))} />
                  <input id={s.key} type="number" min={s.min} max={s.max} step={s.step}
                    value={String(draft[s.key] ?? "")} onChange={(e) => change(s.key, e.target.value === "" ? "" : Number(e.target.value))} />
                </>
              )}
              {s.changed && (
                <button className="link-btn" type="button" disabled={busy} onClick={() => change(s.key, s.default)}>default</button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="save-bar">
        {saved && dirty.length === 0 && <span className="saved" role="status">Saved. Applies to the next question.</span>}
        <button className="btn-primary" type="button" disabled={busy || dirty.length === 0} onClick={() => void save()}>
          {busy ? "Saving…" : dirty.length ? `Save ${dirty.length} change${dirty.length > 1 ? "s" : ""}` : "Save"}
        </button>
      </div>
    </section>
  );
}
