import { useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { useAuth } from "../AuthContext";
import {
  authHeaders, downloadBlob, labelClass, outlineBtn, primaryBtn, selectClass,
} from "./dashboardApi";
import SectionHeader from "./SectionHeader";
import DeviceUploadRow from "./DeviceUploadRow";
import NormalizationReviewCard from "./NormalizationReviewCard";
import AuditResultCard from "./AuditResultCard";

const FALLBACK_FRAMEWORKS = [
  { id: "CIS", label: "CIS Benchmark" },
  { id: "NIST", label: "NIST SP 800-53" },
];

export default function AuditorSection({ devices, devicesLoading }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const nextRow = useRef(2);
  const nextEntry = useRef(1);
  const [rows, setRows] = useState([{ id: 1, deviceId: "", file: null }]);
  const [frameworks, setFrameworks] = useState(FALLBACK_FRAMEWORKS);
  const [framework, setFramework] = useState("CIS");
  const [runFramework, setRunFramework] = useState("CIS");   // the benchmark used for this run
  const [entries, setEntries] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dlError, setDlError] = useState("");

  // GET /api/frameworks/ ; falls back to CIS and NIST if it is unavailable.
  useEffect(() => {
    if (!token) return;
    let live = true;
    fetch("/api/frameworks/", { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((list) => { if (live && Array.isArray(list) && list.length) setFrameworks(list); })
      .catch(() => {});
    return () => { live = false; };
  }, [token]);

  const updateRow = (id, patch) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const addRow = () => setRows((rs) => [...rs, { id: nextRow.current++, deviceId: "", file: null }]);
  const removeRow = (id) => setRows((rs) => rs.filter((r) => r.id !== id));

  // Step 1: normalize only. One POST per device, one at a time (the local model
  // handles one request at a time). The report comes later, after human review.
  const normalize = async () => {
    const ready = rows.filter((r) => r.deviceId && r.file);
    if (!ready.length) return setError("Choose a device and a configuration file for at least one row.");
    setError("");
    setBusy(true);
    setEntries([]);
    setRunFramework(framework);
    const out = [];

    for (const r of ready) {
      const device = devices.find((d) => d.device_id === r.deviceId);
      try {
        const fd = new FormData();
        fd.append("config", r.file);
        fd.append("device_id", r.deviceId);   // the backend takes the vendor from the device
        const res = await fetch("/api/normalize/", { method: "POST", headers: authHeaders(token), body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
        for (const item of data.results ?? []) {
          out.push({ key: nextEntry.current++, file: r.file.name, device, item,
                     error: item.status === "failed" ? item.error : null });
        }
      } catch (err) {
        out.push({ key: nextEntry.current++, file: r.file.name, device, error: err.message });
      }
      setEntries([...out]);
    }
    setBusy(false);
  };

  // Called by a review card once its report has been generated.
  const onAudited = (key, item) =>
    setEntries((es) => es.map((e) => (e.key === key ? { ...e, item } : e)));

  const withReport = entries.filter((e) => e.item?.compliance_report);
  const totals = withReport.reduce((t, e) => {
    const s = e.item.compliance_report.summary;
    return { passed: t.passed + s.passed, failed: t.failed + s.failed,
             undecided: t.undecided + (s.unknown ?? 0) + (s.manual ?? 0) };
  }, { passed: 0, failed: 0, undecided: 0 });

  const downloadAll = async () => {
    setDlError("");
    try {
      await downloadBlob(`/api/uploads/report/pdf/?ids=${withReport.map((e) => e.item.id).join(",")}`,
        token, "compliance_report.pdf");
    } catch (err) {
      setDlError(err.message);
    }
  };

  return (
    <section>
      <SectionHeader title="AUTOMATE COMPLIANCE REVIEW">
        Pick a registered device and a benchmark, then upload its configuration. The AI normalizes it,
        you approve anything it is unsure about, and the report is generated after that.
      </SectionHeader>

      <div className="border border-gray-800 p-6">
        <h2 className="text-sm tracking-widest border-b border-gray-800 pb-4 mb-6">1. SELECT DEVICE AND BENCHMARK</h2>

        <label htmlFor="framework" className={labelClass}>BENCHMARK TO AUDIT AGAINST</label>
        <select id="framework" value={framework} onChange={(e) => setFramework(e.target.value)}
          className={`${selectClass} mb-6`}>
          {frameworks.map((f) => <option key={f.id} value={f.id}>{f.label ?? f.id}</option>)}
        </select>

        {rows.map((row, i) => (
          <DeviceUploadRow
            key={row.id} index={i} row={row} devices={devices} devicesLoading={devicesLoading}
            canRemove={rows.length > 1}
            onDevice={(deviceId) => updateRow(row.id, { deviceId })}
            onFile={(file) => updateRow(row.id, { file })}
            onRemove={() => removeRow(row.id)}
          />
        ))}

        <button type="button" onClick={addRow}
          className="w-full flex items-center justify-center gap-2 border border-gray-700 text-gray-400 py-3 text-xs tracking-widest hover:border-white hover:text-white transition-colors mb-4">
          <Plus className="w-4 h-4" /> ADD ANOTHER DEVICE
        </button>

        {error && (
          <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2 mb-4">{error}</p>
        )}

        <button type="button" onClick={normalize} disabled={busy} className={primaryBtn}>
          {busy ? "NORMALIZING..." : "NORMALIZE CONFIGURATIONS"}
        </button>
      </div>

      {entries.length > 0 && (
        <div className="mt-10">
          <h2 className="text-sm tracking-widest border-b border-gray-800 pb-4 mb-6">
            2. NORMALIZATION AND HUMAN REVIEW
          </h2>
          {entries.map((entry) => (
            <NormalizationReviewCard key={entry.key} entry={entry}
              framework={runFramework} onAudited={onAudited} />
          ))}
        </div>
      )}

      {withReport.length > 0 && (
        <div className="mt-10">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 pb-4 mb-6">
            <h2 className="text-sm tracking-widest">3. COMPLIANCE REPORT</h2>
            <button type="button" onClick={downloadAll} className={outlineBtn}>DOWNLOAD REPORT (PDF)</button>
          </div>
          {dlError && <p role="alert" className="text-red-400 text-xs mb-4">{dlError}</p>}

          <dl className="grid grid-cols-4 text-center border border-gray-800 mb-6">
            {[["DEVICES AUDITED", withReport.length], ["RULES PASSED", totals.passed],
              ["RULES FAILED", totals.failed], ["UNDECIDED", totals.undecided]].map(([k, v]) => (
              <div key={k} className="py-4 border-r border-gray-800 last:border-r-0">
                <dd className="text-2xl font-bold">{v}</dd>
                <dt className="text-[10px] text-gray-500 mt-1">{k}</dt>
              </div>
            ))}
          </dl>

          {withReport.map((entry) => <AuditResultCard key={entry.key} entry={entry} />)}
        </div>
      )}
    </section>
  );
}

// import { useEffect, useRef, useState } from "react";
// import { Plus } from "lucide-react";
// import { useAuth } from "../AuthContext";
// import {
//   authHeaders, downloadBlob, labelClass, outlineBtn, primaryBtn, selectClass,
// } from "./dashboardApi";
// import SectionHeader from "./SectionHeader";
// import DeviceUploadRow from "./DeviceUploadRow";
// import AuditResultCard from "./AuditResultCard";

// const FALLBACK_FRAMEWORKS = [
//   { id: "CIS", label: "CIS Benchmark" },
//   { id: "NIST", label: "NIST SP 800-53" },
// ];

// export default function AuditorSection({ devices, devicesLoading }) {
//   const { session } = useAuth();
//   const token = session?.access_token;
//   const nextId = useRef(2);
//   const [rows, setRows] = useState([{ id: 1, deviceId: "", file: null }]);
//   const [frameworks, setFrameworks] = useState(FALLBACK_FRAMEWORKS);
//   const [framework, setFramework] = useState("CIS");
//   const [results, setResults] = useState([]);
//   const [busy, setBusy] = useState(false);
//   const [error, setError] = useState("");
//   const [dlError, setDlError] = useState("");

//   // GET /api/frameworks/ ; falls back to CIS and NIST if it is unavailable.
//   useEffect(() => {
//     if (!token) return;
//     let live = true;
//     fetch("/api/frameworks/", { headers: authHeaders(token) })
//       .then((r) => (r.ok ? r.json() : Promise.reject()))
//       .then((list) => { if (live && Array.isArray(list) && list.length) setFrameworks(list); })
//       .catch(() => {});
//     return () => { live = false; };
//   }, [token]);

//   const updateRow = (id, patch) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
//   const addRow = () => setRows((rs) => [...rs, { id: nextId.current++, deviceId: "", file: null }]);
//   const removeRow = (id) => setRows((rs) => rs.filter((r) => r.id !== id));

//   // One POST per device row, one at a time (the local model handles one request at a time).
//   const analyze = async () => {
//     const ready = rows.filter((r) => r.deviceId && r.file);
//     if (!ready.length) return setError("Choose a device and a configuration file for at least one row.");
//     setError("");
//     setBusy(true);
//     setResults([]);
//     const out = [];

//     for (const r of ready) {
//       const device = devices.find((d) => d.device_id === r.deviceId);
//       try {
//         const fd = new FormData();
//         fd.append("config", r.file);
//         fd.append("device_id", r.deviceId);   // the backend takes vendor and type from the device
//         fd.append("framework", framework);
//         const res = await fetch("/api/uploads/", { method: "POST", headers: authHeaders(token), body: fd });
//         const data = await res.json().catch(() => ({}));
//         if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
//         for (const item of data.results ?? []) {
//           out.push({ file: r.file.name, device, item, error: item.status === "failed" ? item.error : null });
//         }
//       } catch (err) {
//         out.push({ file: r.file.name, device, error: err.message });
//       }
//       setResults([...out]);
//     }
//     setBusy(false);
//   };

//   const withReport = results.filter((e) => e.item?.compliance_report);
//   const totals = withReport.reduce((t, e) => {
//     const s = e.item.compliance_report.summary;
//     return { passed: t.passed + s.passed, failed: t.failed + s.failed,
//              undecided: t.undecided + (s.unknown ?? 0) + (s.manual ?? 0) };
//   }, { passed: 0, failed: 0, undecided: 0 });

//   const downloadAll = async () => {
//     setDlError("");
//     try {
//       await downloadBlob(`/api/uploads/report/pdf/?ids=${withReport.map((e) => e.item.id).join(",")}`,
//         token, "compliance_report.pdf");
//     } catch (err) {
//       setDlError(err.message);
//     }
//   };

//   return (
//     <section>
//       <SectionHeader title="AUTOMATE COMPLIANCE REVIEW">
//         Pick a registered device, choose a benchmark and upload its configuration. The vendor and
//         type come from the device's registration.
//       </SectionHeader>

//       <div className="border border-gray-800 p-6">
//         <h2 className="text-sm tracking-widest border-b border-gray-800 pb-4 mb-6">UPLOAD CONFIGURATIONS</h2>

//         <label htmlFor="framework" className={labelClass}>COMPLIANCE FRAMEWORK</label>
//         <select id="framework" value={framework} onChange={(e) => setFramework(e.target.value)}
//           className={`${selectClass} mb-6`}>
//           {frameworks.map((f) => <option key={f.id} value={f.id}>{f.label ?? f.id}</option>)}
//         </select>

//         {rows.map((row, i) => (
//           <DeviceUploadRow
//             key={row.id} index={i} row={row} devices={devices} devicesLoading={devicesLoading}
//             canRemove={rows.length > 1}
//             onDevice={(deviceId) => updateRow(row.id, { deviceId })}
//             onFile={(file) => updateRow(row.id, { file })}
//             onRemove={() => removeRow(row.id)}
//           />
//         ))}

//         <button type="button" onClick={addRow}
//           className="w-full flex items-center justify-center gap-2 border border-gray-700 text-gray-400 py-3 text-xs tracking-widest hover:border-white hover:text-white transition-colors mb-4">
//           <Plus className="w-4 h-4" /> ADD ANOTHER DEVICE
//         </button>

//         {error && (
//           <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2 mb-4">{error}</p>
//         )}

//         <button type="button" onClick={analyze} disabled={busy} className={primaryBtn}>
//           {busy ? "ANALYZING..." : "ANALYZE CONFIGURATIONS"}
//         </button>
//       </div>

//       {results.length > 0 && (
//         <div className="mt-10">
//           <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 pb-4 mb-6">
//             <h2 className="text-sm tracking-widest">COMPLIANCE REPORT</h2>
//             {withReport.length > 0 && (
//               <button type="button" onClick={downloadAll} className={outlineBtn}>DOWNLOAD REPORT (PDF)</button>
//             )}
//           </div>
//           {dlError && <p role="alert" className="text-red-400 text-xs mb-4">{dlError}</p>}

//           {withReport.length > 0 && (
//             <dl className="grid grid-cols-4 text-center border border-gray-800 mb-6">
//               {[["DEVICES AUDITED", withReport.length], ["RULES PASSED", totals.passed],
//                 ["RULES FAILED", totals.failed], ["UNDECIDED", totals.undecided]].map(([k, v]) => (
//                 <div key={k} className="py-4 border-r border-gray-800 last:border-r-0">
//                   <dd className="text-2xl font-bold">{v}</dd>
//                   <dt className="text-[10px] text-gray-500 mt-1">{k}</dt>
//                 </div>
//               ))}
//             </dl>
//           )}

//           {results.map((entry, i) => <AuditResultCard key={i} entry={entry} />)}
//         </div>
//       )}
//     </section>
//   );
// }