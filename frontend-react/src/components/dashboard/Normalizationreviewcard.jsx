import { useEffect, useRef, useState } from "react";
import { useAuth } from "../AuthContext";
import { jsonHeaders, outlineBtn, typeLabel } from "./dashboardApi";

// { management: { ssh_version: 2 } } -> [["management.ssh_version", "2"]]
function flatten(obj, prefix = "") {
  return Object.entries(obj ?? {}).flatMap(([k, v]) => {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) return flatten(v, path);
    return [[path, Array.isArray(v) ? JSON.stringify(v) : String(v)]];
  });
}

// One doubtful item. Dual-call disagreements get one-click candidate values;
// every item also accepts a typed "canonical.path = JSON value" line, or a reject.
function ReviewItem({ r, disagreement, state, busy, error, onResolve }) {
  const [text, setText] = useState("");

  if (state) {
    return (
      <li className="px-3 py-2 text-xs flex items-center justify-between gap-3">
        <span className="text-gray-400 break-all">{r.command}</span>
        <span className={state === "approved" ? "text-white" : "text-gray-500"}>{state.toUpperCase()}</span>
      </li>
    );
  }

  const candidates = disagreement
    ? [["A", disagreement.call_a], ["B", disagreement.call_b]]
    : [];

  return (
    <li className="px-3 py-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <span className="text-gray-100 break-all">{r.command}</span>
        <span className="text-[10px] text-gray-500">AI confidence {Math.round((r.confidence ?? 0) * 100)}%</span>
      </div>
      <p className="text-[11px] text-gray-400 mb-3 break-words">{r.proposed_meaning || "No explanation given."}</p>

      {candidates.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {candidates.map(([label, value]) => (
            <button key={label} type="button" disabled={busy}
              onClick={() => onResolve("approve", `${r.command} = ${JSON.stringify(value)}`)}
              className={outlineBtn}>
              USE {label}: {JSON.stringify(value)}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <input value={text} onChange={(e) => setText(e.target.value)}
          placeholder="management.ssh_version = 2"
          aria-label={`Mapping for ${r.command}`}
          className="flex-1 min-w-[12rem] bg-black border border-gray-700 px-3 py-2 text-xs focus:outline-none focus:border-white" />
        <button type="button" disabled={busy || !text.trim()}
          onClick={() => onResolve("approve", text.trim())} className={outlineBtn}>
          APPROVE
        </button>
        <button type="button" disabled={busy} onClick={() => onResolve("reject")} className={outlineBtn}>
          REJECT
        </button>
      </div>
      {error && <p role="alert" className="text-red-400 text-[11px] mt-2">{error}</p>}
    </li>
  );
}

export default function NormalizationReviewCard({ entry, framework, onAudited }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const { file, device, item, error, key } = entry;

  const reviewItems = item?.normalization_review ?? [];
  const disagreements = item?.dual_call_disagreements ?? [];
  const baseline = item?.baseline_json ?? item?.partial_baseline;
  const hasReport = Boolean(item?.compliance_report);
  const schemaFailed = Boolean(item?.errors?.length);

  const [decisions, setDecisions] = useState({});   // memory_id -> "approved" | "rejected"
  const [busyId, setBusyId] = useState(null);
  const [errors, setErrors] = useState({});
  const [audit, setAudit] = useState({ running: false, error: "" });
  const started = useRef(false);

  const pending = reviewItems.filter((r) => !decisions[r.memory_id]);
  const ready = Boolean(item) && !error && !schemaFailed && !hasReport && pending.length === 0;

  // POST /api/normalization-reviews/<id>/ : the human decision for one doubtful item.
  const resolve = async (r, decision, humanCommand) => {
    setBusyId(r.memory_id);
    setErrors((e) => ({ ...e, [r.memory_id]: "" }));
    try {
      const body = decision === "approve" ? { decision, human_command: humanCommand } : { decision };
      const res = await fetch(`/api/normalization-reviews/${r.memory_id}/`, {
        method: "POST", headers: jsonHeaders(token), body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
      setDecisions((d) => ({ ...d, [r.memory_id]: decision === "approve" ? "approved" : "rejected" }));
    } catch (err) {
      setErrors((e) => ({ ...e, [r.memory_id]: err.message }));
    }
    setBusyId(null);
  };

  // POST /api/uploads/<id>/audit/ : re-applies approved mappings, then builds the report.
  const runAudit = async () => {
    started.current = true;
    setAudit({ running: true, error: "" });
    try {
      const res = await fetch(`/api/uploads/${item.id}/audit/`, {
        method: "POST", headers: jsonHeaders(token), body: JSON.stringify({ framework }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
      // The serializer has no review list; clear it so the report card does not say "waiting".
      onAudited(key, { ...item, ...data, id: item.id, normalization_review: [] });
      setAudit({ running: false, error: "" });
    } catch (err) {
      started.current = false;
      setAudit({ running: false, error: err.message });
    }
  };

  // The report is generated by itself once nothing is waiting for a human.
  useEffect(() => {
    if (ready && !started.current && !audit.error) runAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  const rows = flatten(baseline);
  const flagged = new Set(reviewItems.map((r) => r.command));

  return (
    <div className="border border-gray-800 bg-black/50 p-5 mb-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <h3 className="text-sm break-all">{device ? `${device.device_id} · ${device.hostname}` : file}</h3>
        <span className="text-[10px] text-gray-500">
          {device ? `${device.vendor} ${typeLabel(device.device_type)}` : ""}
          {framework ? ` · ${framework}` : ""}
        </span>
      </div>
      <p className="text-[10px] text-gray-600 mb-4 break-all">{file}</p>

      {error && (
        <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2">
          Normalization failed: {error}
        </p>
      )}

      {schemaFailed && (
        <div role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2 mb-4">
          <p className="mb-1">The normalized output did not pass schema validation, so no report is built from it.</p>
          <ul className="list-disc pl-5 text-gray-400">{item.errors.map((er, i) => <li key={i}>{String(er)}</li>)}</ul>
        </div>
      )}

      {item && !error && rows.length > 0 && (
        <details open={!hasReport} className="mb-4">
          <summary className="text-xs text-gray-300 cursor-pointer mb-2">
            NORMALIZED FORM ({rows.length} fields)
          </summary>
          <div className="border border-gray-800 overflow-x-auto">
            <table className="w-full text-xs text-left">
              <tbody className="divide-y divide-gray-800">
                {rows.map(([path, value]) => (
                  <tr key={path} className={flagged.has(path) ? "bg-gray-900" : ""}>
                    <td className="px-3 py-1.5 text-gray-400 whitespace-nowrap">{path}</td>
                    <td className="px-3 py-1.5 text-gray-100 break-all">{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {item && !error && !schemaFailed && (
        <div className="mb-2">
          <h4 className="text-xs tracking-widest mb-2">HUMAN REVIEW</h4>

          {reviewItems.length === 0 ? (
            <p className="text-xs text-gray-400">The AI had no doubts. Nothing needs approval.</p>
          ) : (
            <>
              <p className="text-[10px] text-gray-500 mb-2">
                {pending.length > 0
                  ? `${pending.length} of ${reviewItems.length} item(s) need your decision. The report is generated after the last one.`
                  : "All items reviewed."}
                {" "}Approved mappings are applied when the report is generated; a rejected item stays unchanged.
              </p>
              <ul className="divide-y divide-gray-800 border border-gray-800">
                {reviewItems.map((r) => (
                  <ReviewItem key={r.memory_id} r={r}
                    disagreement={disagreements.find((d) => d.field === r.command)}
                    state={decisions[r.memory_id]} busy={busyId === r.memory_id}
                    error={errors[r.memory_id]}
                    onResolve={(decision, cmd) => resolve(r, decision, cmd)} />
                ))}
              </ul>
            </>
          )}

          {audit.running && <p className="text-xs text-gray-400 mt-3">Generating report...</p>}
          {hasReport && <p className="text-xs text-gray-300 mt-3">Report generated below.</p>}
          {audit.error && (
            <div className="mt-3">
              <p role="alert" className="text-red-400 text-xs mb-2">Could not generate the report: {audit.error}</p>
              <button type="button" onClick={runAudit} className={outlineBtn}>RETRY REPORT</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}