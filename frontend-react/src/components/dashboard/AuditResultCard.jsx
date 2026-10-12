import { useState } from "react";
import { useAuth } from "../AuthContext";
import { downloadBlob, jsonHeaders, typeLabel } from "./dashboardApi";

// Larger buttons than the shared outlineBtn, so they are easy to read and to hit.
const btn =
  "border border-gray-600 text-gray-200 px-5 py-3 text-sm tracking-widest hover:border-white hover:text-white transition-colors disabled:opacity-50";
const btnSolid =
  "border border-white bg-white text-black px-5 py-3 text-sm tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50";

const STATUS_STYLE = {
  Pass: "text-green-400 border-green-500/50",
  Fail: "text-red-400 border-red-500/50",
  Unknown: "text-gray-400 border-gray-600",
  Manual: "text-gray-400 border-gray-600",
};
const isUndecided = (r) => r.status === "Unknown" || r.status === "Manual";

export default function AuditResultCard({ entry }) {
  const { user, session } = useAuth();
  const token = session?.access_token;
  const { file, device, item, error } = entry;
  const report = item?.compliance_report;
  const s = report?.summary;

  const [remediation, setRemediation] = useState(null);
  const [remBusy, setRemBusy] = useState(false);
  const [remError, setRemError] = useState("");
  const [pushBusy, setPushBusy] = useState(false);
  const [pushMsg, setPushMsg] = useState(null);
  const [needsConfirm, setNeedsConfirm] = useState(false);
  const [dlError, setDlError] = useState("");
  const [filter, setFilter] = useState("all");

  const download = async () => {
    setDlError("");
    try {
      await downloadBlob(`/api/uploads/report/pdf/?ids=${item.id}`, token,
        `report_${device?.device_id ?? item.id}.pdf`);
    } catch (err) {
      setDlError(err.message);
    }
  };

  // POST /remediation/propose/ : one report for all failed rules, saved server-side.
  const loadRemediation = async () => {
    setRemBusy(true);
    setRemError("");
    try {
      const res = await fetch(`/api/uploads/${item.id}/remediation/propose/`, {
        method: "POST", headers: jsonHeaders(token), body: JSON.stringify({}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
      setRemediation(data.proposals ?? []);
    } catch (err) {
      setRemError(err.message);
    }
    setRemBusy(false);
  };

  // POST /push/ : stores the snapshot + compliance result. Nothing is sent to the device.
  const push = async (confirmUnreviewed = false) => {
    setPushBusy(true);
    setPushMsg(null);
    try {
      const res = await fetch(`/api/uploads/${item.id}/push/`, {
        method: "POST", headers: jsonHeaders(token),
        body: JSON.stringify({ uploaded_by: user?.email ?? "", confirm_unreviewed: confirmUnreviewed }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 409) setNeedsConfirm(true);
      if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
      setNeedsConfirm(false);
      const text = {
        pushed: `Pushed. Snapshot #${data.snapshot_id} saved for ${data.device_id} (hash ${data.config_hash?.slice(0, 10)}...).`,
        no_changes: `No changes since the last snapshot of ${data.device_id}. Nothing new was stored.`,
        already_pushed: `Already pushed (snapshot #${data.snapshot_id}).`,
      }[data.status] ?? "Done.";
      setPushMsg({ ok: true, text });
    } catch (err) {
      setPushMsg({ ok: false, text: err.message });
    }
    setPushBusy(false);
  };

  const undecided = (s?.unknown ?? 0) + (s?.manual ?? 0);
  const pct = (n) => (s?.total ? (n / s.total) * 100 : 0);

  const results = report?.results ?? [];
  const counts = {
    all: results.length,
    Fail: results.filter((r) => r.status === "Fail").length,
    undecided: results.filter(isUndecided).length,
    Pass: results.filter((r) => r.status === "Pass").length,
  };
  const shown = results.filter((r) =>
    filter === "all" ? true : filter === "undecided" ? isUndecided(r) : r.status === filter);

  return (
    <div className="border border-gray-800 bg-black/50 p-6 sm:p-8 mb-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h3 className="text-lg font-bold break-all">{device ? `${device.device_id} · ${device.hostname}` : file}</h3>
        <span className="text-sm text-gray-400">
          {device ? `${device.vendor} ${typeLabel(device.device_type)}` : ""}
          {report?.framework ? ` · ${report.framework}` : ""}
        </span>
      </div>
      <p className="text-sm text-gray-500 mb-6 break-all">{file}</p>

      {error && (
        <p role="alert" className="border border-red-500/60 text-red-400 text-sm px-4 py-3">
          Upload failed: {error}
        </p>
      )}

      {item && !report && !error && (
        <div className="text-sm text-gray-300 leading-relaxed">
          <p className="mb-2">Status: <span className="text-white">{item.status}</span></p>
          {item.errors?.length > 0 && (
            <ul className="list-disc pl-6 text-gray-400">{item.errors.map((er, i) => <li key={i}>{er}</li>)}</ul>
          )}
        </div>
      )}

      {s && (
        <>
          <dl className="grid grid-cols-2 sm:grid-cols-4 text-center border border-gray-800 mb-4">
            {[["PASSED", s.passed, "text-green-400"], ["FAILED", s.failed, "text-red-400"],
              ["UNDECIDED", undecided, "text-gray-300"],
              ["SCORE", `${s.total ? Math.round((100 * s.passed) / s.total) : 0}%`, "text-white"]].map(([k, v, c]) => (
              <div key={k} className="py-5 border-r border-b sm:border-b-0 border-gray-800 last:border-r-0">
                <dd className={`text-4xl font-bold ${c}`}>{v}</dd>
                <dt className="text-xs text-gray-400 tracking-wider mt-2">{k}</dt>
              </div>
            ))}
          </dl>
          <div className="flex h-3 w-full bg-gray-900 mb-3">
            <div className="bg-green-500" style={{ width: `${pct(s.passed)}%` }} />
            <div className="bg-red-500" style={{ width: `${pct(s.failed)}%` }} />
            <div className="bg-gray-600" style={{ width: `${pct(undecided)}%` }} />
          </div>
          <p className="text-sm text-gray-400 leading-relaxed mb-6">
            {s.passed} of {s.total} rules passed. {s.failed} failed ({s.critical_high} critical or high).
            Undecided rules were missing data or need a manual check.
          </p>

          {item.normalization_review?.length > 0 && (
            <p className="border border-gray-600 text-gray-200 text-sm px-4 py-3 mb-6">
              {item.normalization_review.length} item(s) are waiting for human review of the normalization.
            </p>
          )}

          <div className="flex flex-wrap gap-2 mb-3">
            {[["all", "ALL"], ["Fail", "FAILED"], ["undecided", "UNDECIDED"], ["Pass", "PASSED"]].map(([id, label]) => (
              <button key={id} type="button" onClick={() => setFilter(id)}
                className={`text-sm tracking-wider px-4 py-2 border transition-colors ${
                  filter === id ? "bg-white text-black border-white"
                                : "text-gray-300 border-gray-700 hover:border-white hover:text-white"}`}>
                {label} ({counts[id]})
              </button>
            ))}
          </div>

          <ul className="divide-y divide-gray-800 border border-gray-800 mb-6">
            {shown.length === 0 && <li className="px-5 py-5 text-sm text-gray-400">No rules in this view.</li>}
            {shown.map((r) => (
              <li key={r.rule_id} className="px-5 py-4 flex items-start gap-4">
                <span className={`shrink-0 w-24 text-center text-xs tracking-wider border py-1.5 ${
                  STATUS_STYLE[r.status] ?? "text-gray-400 border-gray-600"}`}>
                  {r.status.toUpperCase()}
                </span>
                <div className="min-w-0">
                  <p className="text-base text-gray-100 leading-snug">[{r.rule_id}] {r.name}</p>
                  <p className="text-sm text-gray-400 mt-1.5 break-words leading-relaxed">
                    {r.field}
                    <br />
                    Expected: <span className="text-gray-200">{String(r.expected)}</span>
                    {"  ·  "}
                    Actual: <span className="text-gray-200">{String(r.actual)}</span>
                  </p>
                </div>
              </li>
            ))}
          </ul>

          <div className="flex flex-wrap gap-4">
            <button type="button" onClick={download} className={btn}>DOWNLOAD REPORT</button>
            <button type="button" onClick={loadRemediation} disabled={remBusy} className={btn}>
              {remBusy ? "GENERATING..." : remediation ? "REFRESH REMEDIATION" : "REMEDIATION"}
            </button>
            <button type="button" onClick={() => push(false)} disabled={pushBusy} className={btnSolid}>
              {pushBusy ? "PUSHING..." : "PUSH"}
            </button>
          </div>

          {dlError && <p role="alert" className="text-red-400 text-sm mt-4">{dlError}</p>}
          {remBusy && (
            <p className="text-sm text-gray-400 mt-4">
              The AI writes fixes for every failed rule, so this can take a minute or more.
            </p>
          )}
          {remError && <p role="alert" className="text-red-400 text-sm mt-4">{remError}</p>}

          {pushMsg && (
            <p role="status" className={`text-sm mt-4 border px-4 py-3 ${
              pushMsg.ok ? "border-gray-500 text-gray-100" : "border-red-500/60 text-red-400"}`}>
              {pushMsg.text}
            </p>
          )}
          {needsConfirm && (
            <button type="button" onClick={() => push(true)} disabled={pushBusy} className={`${btn} mt-4`}>
              PUSH ANYWAY (REVIEW STILL PENDING)
            </button>
          )}

          {remediation && (
            <div className="mt-8 border border-gray-800 p-6">
              <h4 className="text-base font-bold tracking-widest mb-2">REMEDIATION REPORT</h4>
              <p className="text-sm text-gray-400 mb-5">
                AI-suggested commands. Review each one before applying it to a device.
              </p>
              {remediation.length === 0 && <p className="text-sm text-gray-300">Nothing to fix.</p>}
              {remediation.map((p) => (
                <div key={p.rule_id} className="mb-5 last:mb-0">
                  <p className="text-base text-gray-100">[{p.rule_id}] {p.name}</p>
                  <pre className="text-sm text-gray-200 bg-gray-950 border border-gray-800 p-4 mt-2 whitespace-pre-wrap overflow-x-auto leading-relaxed">
                    {(p.commands ?? []).join("\n") || "No commands suggested."}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// import { useState } from "react";
// import { useAuth } from "../AuthContext";
// import { downloadBlob, jsonHeaders, outlineBtn, typeLabel } from "./dashboardApi";

// const STATUS_STYLE = {
//   Pass: "text-white", Fail: "text-red-400", Unknown: "text-gray-500", Manual: "text-gray-500",
// };

// export default function AuditResultCard({ entry }) {
//   const { user, session } = useAuth();
//   const token = session?.access_token;
//   const { file, device, item, error } = entry;
//   const report = item?.compliance_report;
//   const s = report?.summary;

//   const [remediation, setRemediation] = useState(null);
//   const [remBusy, setRemBusy] = useState(false);
//   const [remError, setRemError] = useState("");
//   const [pushBusy, setPushBusy] = useState(false);
//   const [pushMsg, setPushMsg] = useState(null);
//   const [needsConfirm, setNeedsConfirm] = useState(false);
//   const [dlError, setDlError] = useState("");

//   const download = async () => {
//     setDlError("");
//     try {
//       await downloadBlob(`/api/uploads/report/pdf/?ids=${item.id}`, token,
//         `report_${device?.device_id ?? item.id}.pdf`);
//     } catch (err) {
//       setDlError(err.message);
//     }
//   };

//   // POST /remediation/propose/ : one report for all failed rules, saved server-side.
//   const loadRemediation = async () => {
//     setRemBusy(true);
//     setRemError("");
//     try {
//       const res = await fetch(`/api/uploads/${item.id}/remediation/propose/`, {
//         method: "POST", headers: jsonHeaders(token), body: JSON.stringify({}),
//       });
//       const data = await res.json().catch(() => ({}));
//       if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
//       setRemediation(data.proposals ?? []);
//     } catch (err) {
//       setRemError(err.message);
//     }
//     setRemBusy(false);
//   };

//   // POST /push/ : stores the snapshot + compliance result. Nothing is sent to the device.
//   const push = async (confirmUnreviewed = false) => {
//     setPushBusy(true);
//     setPushMsg(null);
//     try {
//       const res = await fetch(`/api/uploads/${item.id}/push/`, {
//         method: "POST", headers: jsonHeaders(token),
//         body: JSON.stringify({ uploaded_by: user?.email ?? "", confirm_unreviewed: confirmUnreviewed }),
//       });
//       const data = await res.json().catch(() => ({}));
//       if (res.status === 409) setNeedsConfirm(true);
//       if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
//       setNeedsConfirm(false);
//       const text = {
//         pushed: `Pushed. Snapshot #${data.snapshot_id} saved for ${data.device_id} (hash ${data.config_hash?.slice(0, 10)}...).`,
//         no_changes: `No changes since the last snapshot of ${data.device_id}. Nothing new was stored.`,
//         already_pushed: `Already pushed (snapshot #${data.snapshot_id}).`,
//       }[data.status] ?? "Done.";
//       setPushMsg({ ok: true, text });
//     } catch (err) {
//       setPushMsg({ ok: false, text: err.message });
//     }
//     setPushBusy(false);
//   };

//   const undecided = (s?.unknown ?? 0) + (s?.manual ?? 0);
//   const pct = (n) => (s?.total ? (n / s.total) * 100 : 0);

//   return (
//     <div className="border border-gray-800 bg-black/50 p-5 mb-4">
//       <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
//         <h3 className="text-sm break-all">{device ? `${device.device_id} · ${device.hostname}` : file}</h3>
//         <span className="text-[10px] text-gray-500">
//           {device ? `${device.vendor} ${typeLabel(device.device_type)}` : ""}
//           {report?.framework ? ` · ${report.framework}` : ""}
//         </span>
//       </div>
//       <p className="text-[10px] text-gray-600 mb-4 break-all">{file}</p>

//       {error && (
//         <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2">
//           Upload failed: {error}
//         </p>
//       )}

//       {item && !report && !error && (
//         <div className="text-xs text-gray-300 leading-relaxed">
//           <p className="mb-2">Status: <span className="text-white">{item.status}</span></p>
//           {item.errors?.length > 0 && (
//             <ul className="list-disc pl-5 text-gray-400">{item.errors.map((er, i) => <li key={i}>{er}</li>)}</ul>
//           )}
//         </div>
//       )}

//       {s && (
//         <>
//           <dl className="grid grid-cols-4 text-center border border-gray-800 mb-3">
//             {[["PASSED", s.passed, "text-white"], ["FAILED", s.failed, "text-red-400"],
//               ["UNDECIDED", undecided, "text-gray-400"],
//               ["SCORE", `${s.total ? Math.round((100 * s.passed) / s.total) : 0}%`, "text-white"]].map(([k, v, c]) => (
//               <div key={k} className="py-3 border-r border-gray-800 last:border-r-0">
//                 <dd className={`text-2xl font-bold ${c}`}>{v}</dd>
//                 <dt className="text-[10px] text-gray-500 mt-1">{k}</dt>
//               </div>
//             ))}
//           </dl>
//           <div className="flex h-2 w-full bg-gray-900 mb-2">
//             <div className="bg-white" style={{ width: `${pct(s.passed)}%` }} />
//             <div className="bg-red-500" style={{ width: `${pct(s.failed)}%` }} />
//             <div className="bg-gray-600" style={{ width: `${pct(undecided)}%` }} />
//           </div>
//           <p className="text-[10px] text-gray-500 mb-4">
//             {s.passed} of {s.total} rules passed. {s.failed} failed ({s.critical_high} critical or high).
//             Undecided rules were missing data or need a manual check.
//           </p>

//           {item.normalization_review?.length > 0 && (
//             <p className="border border-gray-700 text-gray-300 text-xs px-3 py-2 mb-4">
//               {item.normalization_review.length} item(s) are waiting for human review of the normalization.
//             </p>
//           )}

//           <ul className="divide-y divide-gray-800 border border-gray-800 mb-4">
//             {report.results.map((r) => (
//               <li key={r.rule_id} className="px-3 py-2 text-xs flex items-start gap-3">
//                 <span className={`w-16 shrink-0 ${STATUS_STYLE[r.status] ?? "text-gray-400"}`}>
//                   {r.status.toUpperCase()}
//                 </span>
//                 <div className="min-w-0">
//                   <p className="text-gray-200">[{r.rule_id}] {r.name}</p>
//                   <p className="text-[10px] text-gray-500 mt-0.5 break-words">
//                     {r.field}. Expected: {String(r.expected)}. Actual: {String(r.actual)}
//                   </p>
//                 </div>
//               </li>
//             ))}
//           </ul>

//           <div className="flex flex-wrap gap-3">
//             <button type="button" onClick={download} className={outlineBtn}>DOWNLOAD REPORT</button>
//             <button type="button" onClick={loadRemediation} disabled={remBusy} className={outlineBtn}>
//               {remBusy ? "GENERATING..." : remediation ? "REFRESH REMEDIATION" : "REMEDIATION"}
//             </button>
//             <button type="button" onClick={() => push(false)} disabled={pushBusy}
//               className="border border-white bg-white text-black px-4 py-2 text-xs tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50">
//               {pushBusy ? "PUSHING..." : "PUSH"}
//             </button>
//           </div>

//           {dlError && <p role="alert" className="text-red-400 text-xs mt-3">{dlError}</p>}
//           {remBusy && (
//             <p className="text-[10px] text-gray-500 mt-3">
//               The AI writes fixes for every failed rule, so this can take a minute or more.
//             </p>
//           )}
//           {remError && <p role="alert" className="text-red-400 text-xs mt-3">{remError}</p>}

//           {pushMsg && (
//             <p role="status" className={`text-xs mt-3 border px-3 py-2 ${
//               pushMsg.ok ? "border-gray-500 text-gray-200" : "border-red-500/60 text-red-400"}`}>
//               {pushMsg.text}
//             </p>
//           )}
//           {needsConfirm && (
//             <button type="button" onClick={() => push(true)} disabled={pushBusy} className={`${outlineBtn} mt-3`}>
//               PUSH ANYWAY (REVIEW STILL PENDING)
//             </button>
//           )}

//           {remediation && (
//             <div className="mt-5 border border-gray-800 p-4">
//               <h4 className="text-xs tracking-widest mb-1">REMEDIATION REPORT</h4>
//               <p className="text-[10px] text-gray-500 mb-3">
//                 AI-suggested commands. Review each one before applying it to a device.
//               </p>
//               {remediation.length === 0 && <p className="text-xs text-gray-400">Nothing to fix.</p>}
//               {remediation.map((p) => (
//                 <div key={p.rule_id} className="mb-3">
//                   <p className="text-xs text-gray-200">[{p.rule_id}] {p.name}</p>
//                   <pre className="text-[11px] text-gray-300 bg-gray-950 border border-gray-800 p-2 mt-1 whitespace-pre-wrap overflow-x-auto">
//                     {(p.commands ?? []).join("\n") || "No commands suggested."}
//                   </pre>
//                 </div>
//               ))}
//             </div>
//           )}
//         </>
//       )}
//     </div>
//   );
// }