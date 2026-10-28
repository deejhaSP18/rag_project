import { useState } from "react";
import { AdminPanel } from "./AdminPanel";
import { SettingsPanel } from "./SettingsPanel";

const TABS = [["documents", "Documents"], ["settings", "Model & retrieval"]] as const;

export function AdminPage() {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("documents");
  return (
    <div className="admin-page">
      <div className="tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" type="button" aria-selected={tab === id} className={`tab${tab === id ? " on" : ""}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "documents" ? <AdminPanel /> : <SettingsPanel />}
    </div>
  );
}
