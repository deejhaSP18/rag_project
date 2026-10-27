import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { api } from "../api/client";
import type { DocumentInfo, Job } from "../api/types";
import { timeAgo } from "../lib/time";

const formatSize = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
const ACCEPT = ".md,.txt,.pdf";

export function AdminPanel() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listDocuments();
      setDocs(data.documents);
      setJobs(data.jobs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load documents");
    }
  }, []);

  const active = jobs.some((j) => j.state === "queued" || j.state === "running");
  useEffect(() => { void refresh(); }, [refresh]);
  // Poll quickly while the indexer works, slowly otherwise.
  useEffect(() => {
    const id = setInterval(() => void refresh(), active ? 1200 : 10000);
    return () => clearInterval(id);
  }, [active, refresh]);

  const run = async (action: () => Promise<unknown>) => {
    setError("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    await refresh();
  };

  const upload = async (files: FileList | File[]) => {
    setUploading(true);
    setNotice("");
    const messages: string[] = [];
    for (const file of Array.from(files)) {
      await run(async () => {
        const result = await api.uploadDocument(file);
        messages.push(
          result.status === "unchanged" ? `${result.name}: identical to the stored file, nothing to do.`
            : result.status === "replaced" ? `${result.name}: replaced the older version and re-indexing.`
            : `${result.name}: uploaded, indexing started.`,
        );
      });
    }
    setNotice(messages.join(" "));
    setUploading(false);
  };

  const onDrop = (e: DragEvent) => { e.preventDefault(); setDragging(false); void upload(e.dataTransfer.files); };

  const remove = (doc: DocumentInfo) => {
    if (window.confirm(`Delete “${doc.name}”? Its file and indexed content will be removed.`)) void run(() => api.deleteDocument(doc.name));
  };

  const running = jobs.find((j) => j.state === "running");

  return (
    <section className="admin" aria-label="Document administration">
      <div className="admin-head">
        <div>
          <h2>Documents</h2>
          <p>Upload files and they are indexed automatically, so chat can answer from them within moments.</p>
        </div>
        <button className="btn-ghost" type="button" disabled={active || docs.length === 0}
          onClick={() => void run(() => api.reindexAll())} title="Re-read every file and rebuild the whole index">
          Rebuild index
        </button>
      </div>

      <div className={`dropzone${dragging ? " over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}
        onClick={() => input.current?.click()} role="button" tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}>
        <input ref={input} type="file" accept={ACCEPT} multiple hidden
          onChange={(e) => { if (e.target.files) void upload(e.target.files); e.target.value = ""; }} />
        <strong>{uploading ? "Uploading…" : "Drop files here, or click to choose"}</strong>
        <span>Markdown, text or PDF · up to 10 MB each</span>
      </div>

      {error && <div className="form-error" role="alert">{error}</div>}
      {notice && !error && <div className="notice" role="status">{notice}</div>}

      {running && (
        <div className="job-banner" role="status">
          <span className="spinner" aria-hidden="true" />
          <div>
            <strong>Indexing {running.target}</strong>
            <span>{running.message}</span>
          </div>
          {running.total > 0 && <progress value={running.done} max={running.total} />}
        </div>
      )}

      <div className="doc-table" role="table" aria-label="Documents">
        <div className="doc-row doc-head" role="row">
          <span>File</span><span>Chunks</span><span>Status</span><span>Updated</span><span />
        </div>
        {docs.length === 0 && <div className="threads-empty">No documents yet. Upload one above.</div>}
        {docs.map((doc) => (
          <div className="doc-row" role="row" key={doc.name}>
            <span className="doc-name" title={doc.name}><span>{doc.name}</span><small>{formatSize(doc.size)}{doc.pages > 0 && ` · ${doc.pages} pages`}</small></span>
            <span>{doc.chunks}</span>
            <span><b className={`badge ${doc.status.replace(" ", "-")}`}>{doc.status}</b></span>
            <span>{timeAgo(doc.modified)}</span>
            <span className="row-actions">
              <button className="btn-ghost sm" type="button" disabled={doc.status === "indexing"}
                onClick={() => void run(() => api.trainDocument(doc.name))}>Re-index</button>
              <button className="btn-ghost sm danger" type="button" onClick={() => remove(doc)}>Delete</button>
            </span>
          </div>
        ))}
      </div>

      {jobs.length > 0 && (
        <>
          <h3>Recent jobs</h3>
          <ul className="job-list">
            {jobs.slice(0, 8).map((j) => (
              <li key={j.id}>
                <b className={`badge ${j.state}`}>{j.state}</b>
                <span>{j.kind === "reindex" ? "Rebuild" : "Index"} · {j.target}</span>
                <small>{j.message} · {timeAgo(j.finished_at ?? j.created_at)}</small>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
