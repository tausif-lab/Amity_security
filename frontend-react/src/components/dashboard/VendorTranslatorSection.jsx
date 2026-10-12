import { useRef, useState } from "react";
import { useAuth } from "../AuthContext";
import { ACCEPT, downloadBlob } from "./dashboardApi";
import SectionHeader from "./SectionHeader";

// Larger than the shared label/select/button styles, so everything is easy to read.
const label = "block text-xs text-gray-400 tracking-wider mb-2";
const select =
  "w-full bg-black border border-gray-700 text-base px-4 py-4 focus:outline-none focus:border-white transition-colors cursor-pointer";
const btn =
  "border border-gray-600 text-gray-200 px-5 py-3 text-sm tracking-widest hover:border-white hover:text-white transition-colors disabled:opacity-50";
const btnSolid =
  "w-full border border-white bg-white text-black py-4 text-sm tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50";

const STATUS_STYLE = {
  Pass: "text-green-400 border-green-500/50",
  Fail: "text-red-400 border-red-500/50",
  Unknown: "text-gray-400 border-gray-600",
  Manual: "text-gray-400 border-gray-600",
};
const isUndecided = (r) => r.status === "Unknown" || r.status === "Manual";

export default function VendorTranslatorSection() {
  const { session } = useAuth();
  const token = session?.access_token;
  const [source, setSource] = useState("cisco");
  const [target, setTarget] = useState("junos");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const inputRef = useRef(null);

  // POST /api/translate/upload (FastAPI, port 8001 through the Vite proxy)
  const translate = async () => {
    if (!file) return setError("Choose a configuration file first.");
    setError("");
    setResult(null);
    setFilter("all");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(
        `/api/translate/upload?source_vendor=${source}&target_vendor=${target}`,
        { method: "POST", body: fd },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `server returned ${res.status}`);
      setResult(data);
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  const download = async () => {
    try {
      await downloadBlob(
        `/api/translate/download?target_vendor=${result.download_target_vendor}&source_stem=${result.download_source_stem}`,
        token, `${result.download_source_stem}_${result.download_target_vendor}.txt`);
    } catch (err) {
      setError(err.message);
    }
  };

  const handoff = result?.ai_engine_handoff;
  const report = handoff?.compliance_report;
  const summary = report?.summary;
  const rules = report?.results ?? [];

  const undecided = (summary?.unknown ?? 0) + (summary?.manual ?? 0);
  const pct = (n) => (summary?.total ? (n / summary.total) * 100 : 0);
  const counts = {
    all: rules.length,
    Fail: rules.filter((r) => r.status === "Fail").length,
    undecided: rules.filter(isUndecided).length,
    Pass: rules.filter((r) => r.status === "Pass").length,
  };
  const shown = rules.filter((r) =>
    filter === "all" ? true : filter === "undecided" ? isUndecided(r) : r.status === filter);

  return (
    <section>
      <SectionHeader title="NETWORK CONFIG TRANSLATION">
        Convert a device configuration from one vendor format to another, then check the result.
      </SectionHeader>

      <div className="border border-gray-800 p-6 sm:p-8 grid grid-cols-2 gap-6">
        <div className="col-span-2 sm:col-span-1">
          <label htmlFor="src" className={label}>SOURCE VENDOR</label>
          <select id="src" value={source} onChange={(e) => setSource(e.target.value)} className={select}>
            <option value="cisco">Cisco</option>
          </select>
        </div>
        <div className="col-span-2 sm:col-span-1">
          <label htmlFor="tgt" className={label}>TARGET VENDOR</label>
          <select id="tgt" value={target} onChange={(e) => setTarget(e.target.value)} className={select}>
            <option value="junos">Junos / Juniper</option>
            <option value="cisco">Cisco (passthrough)</option>
          </select>
        </div>

        <div className="col-span-2">
          <span className={label}>CONFIGURATION FILE</span>
          <input ref={inputRef} type="file" accept={ACCEPT} className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="flex">
            <button type="button" onClick={() => inputRef.current?.click()}
              className="flex-1 text-left border border-gray-700 text-base px-4 py-4 text-gray-300 hover:border-white hover:text-white transition-colors truncate">
              {file ? file.name : "Choose file..."}
            </button>
            <button type="button" onClick={() => inputRef.current?.click()}
              className="border border-l-0 border-gray-700 bg-gray-900 px-8 text-sm tracking-wider hover:text-white transition-colors">
              BROWSE
            </button>
          </div>
        </div>

        {error && (
          <p role="alert" className="col-span-2 border border-red-500/60 text-red-400 text-sm px-4 py-3">{error}</p>
        )}

        <button type="button" onClick={translate} disabled={busy} className={`col-span-2 ${btnSolid}`}>
          {busy ? "TRANSLATING..." : "TRANSLATE & ANALYZE"}
        </button>
      </div>

      {result && (
        <div className="mt-10 border border-gray-800 p-6 sm:p-8">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-5">
            <h2 className="text-lg font-bold tracking-widest">TRANSLATED CONFIGURATION</h2>
            <button type="button" onClick={download} className={btn}>DOWNLOAD .TXT</button>
          </div>

          {typeof result.overall_confidence === "number" && (
            <p className="text-base text-gray-300 mb-4">
              Translation confidence:{" "}
              <span className="text-white font-bold">{Math.round(result.overall_confidence * 100)}%</span>
            </p>
          )}
          {result.warnings?.length > 0 && (
            <div className="border border-gray-700 px-5 py-4 mb-5">
              <p className="text-xs text-gray-400 tracking-wider mb-2">WARNINGS</p>
              <ul className="list-disc pl-6 text-sm text-gray-200 space-y-1.5 leading-relaxed">
                {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
          )}

          <pre className="border border-gray-800 p-5 text-sm text-gray-200 leading-relaxed whitespace-pre-wrap overflow-x-auto max-h-[32rem] overflow-y-auto mb-10">
            {result.normalized_config || "(no commands produced)"}
          </pre>

          <div className="border-t border-gray-800 pt-8">
            <h2 className="text-lg font-bold tracking-widest mb-1">COMPLIANCE CHECK OF THE TRANSLATED CONFIG</h2>

            {!summary && (
              <p className="text-sm text-gray-400 mt-3">
                Compliance check unavailable{handoff?.error ? `: ${handoff.error}` : "."}
              </p>
            )}

            {summary && (
              <>
                <p className="text-sm text-gray-400 mb-5">
                  {report?.framework ? `Checked against ${report.framework}. ` : ""}
                  {summary.passed} of {summary.total} rules passed.
                </p>

                <dl className="grid grid-cols-2 sm:grid-cols-4 text-center border border-gray-800 mb-4">
                  {[["PASSED", summary.passed, "text-green-400"], ["FAILED", summary.failed, "text-red-400"],
                    ["UNDECIDED", undecided, "text-gray-300"],
                    ["SCORE", `${summary.total ? Math.round((100 * summary.passed) / summary.total) : 0}%`, "text-white"]].map(([k, v, c]) => (
                    <div key={k} className="py-5 border-r border-b sm:border-b-0 border-gray-800 last:border-r-0">
                      <dd className={`text-4xl font-bold ${c}`}>{v}</dd>
                      <dt className="text-xs text-gray-400 tracking-wider mt-2">{k}</dt>
                    </div>
                  ))}
                </dl>

                <div className="flex h-3 w-full bg-gray-900 mb-3">
                  <div className="bg-green-500" style={{ width: `${pct(summary.passed)}%` }} />
                  <div className="bg-red-500" style={{ width: `${pct(summary.failed)}%` }} />
                  <div className="bg-gray-600" style={{ width: `${pct(undecided)}%` }} />
                </div>
                <p className="text-sm text-gray-400 leading-relaxed mb-6">
                  {summary.failed} failed
                  {summary.critical_high != null ? ` (${summary.critical_high} critical or high)` : ""}.
                  Undecided rules were missing data or need a manual check.
                </p>

                {rules.length > 0 && (
                  <>
                    <div className="flex flex-wrap gap-2 mb-3">
                      {[["all", "ALL"], ["Fail", "FAILED"], ["undecided", "UNDECIDED"], ["Pass", "PASSED"]].map(([id, text]) => (
                        <button key={id} type="button" onClick={() => setFilter(id)}
                          className={`text-sm tracking-wider px-4 py-2 border transition-colors ${
                            filter === id ? "bg-white text-black border-white"
                                          : "text-gray-300 border-gray-700 hover:border-white hover:text-white"}`}>
                          {text} ({counts[id]})
                        </button>
                      ))}
                    </div>

                    <ul className="divide-y divide-gray-800 border border-gray-800">
                      {shown.length === 0 && <li className="px-5 py-5 text-sm text-gray-400">No rules in this view.</li>}
                      {shown.map((r) => (
                        <li key={r.rule_id} className="px-5 py-4 flex items-start gap-4">
                          <span className={`shrink-0 w-24 text-center text-xs tracking-wider border py-1.5 ${
                            STATUS_STYLE[r.status] ?? "text-gray-400 border-gray-600"}`}>
                            {String(r.status).toUpperCase()}
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
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
// import { useRef, useState } from "react";
// import { useAuth } from "../AuthContext";
// import { ACCEPT, downloadBlob, labelClass, outlineBtn, primaryBtn, selectClass } from "./dashboardApi";
// import SectionHeader from "./SectionHeader";

// export default function VendorTranslatorSection() {
//   const { session } = useAuth();
//   const token = session?.access_token;
//   const [source, setSource] = useState("cisco");
//   const [target, setTarget] = useState("junos");
//   const [file, setFile] = useState(null);
//   const [busy, setBusy] = useState(false);
//   const [result, setResult] = useState(null);
//   const [error, setError] = useState("");
//   const inputRef = useRef(null);

//   // POST /api/translate/upload (FastAPI, port 8001 through the Vite proxy)
//   const translate = async () => {
//     if (!file) return setError("Choose a configuration file first.");
//     setError("");
//     setResult(null);
//     setBusy(true);
//     try {
//       const fd = new FormData();
//       fd.append("file", file);
//       const res = await fetch(
//         `/api/translate/upload?source_vendor=${source}&target_vendor=${target}`,
//         { method: "POST", body: fd },
//       );
//       const data = await res.json().catch(() => ({}));
//       if (!res.ok) throw new Error(data.detail || `server returned ${res.status}`);
//       setResult(data);
//     } catch (err) {
//       setError(err.message);
//     }
//     setBusy(false);
//   };

//   const download = async () => {
//     try {
//       await downloadBlob(
//         `/api/translate/download?target_vendor=${result.download_target_vendor}&source_stem=${result.download_source_stem}`,
//         token, `${result.download_source_stem}_${result.download_target_vendor}.txt`);
//     } catch (err) {
//       setError(err.message);
//     }
//   };

//   const handoff = result?.ai_engine_handoff;
//   const summary = handoff?.compliance_report?.summary;

//   return (
//     <section>
//       <SectionHeader title="NETWORK CONFIG TRANSLATION">
//         Convert a device configuration from one vendor format to another, then check the result.
//       </SectionHeader>

//       <div className="border border-gray-800 p-6 grid grid-cols-2 gap-6">
//         <div className="col-span-2 sm:col-span-1">
//           <label htmlFor="src" className={labelClass}>SOURCE VENDOR</label>
//           <select id="src" value={source} onChange={(e) => setSource(e.target.value)} className={selectClass}>
//             <option value="cisco">Cisco</option>
//           </select>
//         </div>
//         <div className="col-span-2 sm:col-span-1">
//           <label htmlFor="tgt" className={labelClass}>TARGET VENDOR</label>
//           <select id="tgt" value={target} onChange={(e) => setTarget(e.target.value)} className={selectClass}>
//             <option value="junos">Junos / Juniper</option>
//             <option value="cisco">Cisco (passthrough)</option>
//           </select>
//         </div>

//         <div className="col-span-2">
//           <span className={labelClass}>CONFIGURATION FILE</span>
//           <input ref={inputRef} type="file" accept={ACCEPT} className="hidden"
//             onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
//           <div className="flex">
//             <button type="button" onClick={() => inputRef.current?.click()}
//               className="flex-1 text-left border border-gray-700 text-sm px-4 py-3 text-gray-400 hover:border-white hover:text-white transition-colors truncate">
//               {file ? file.name : "Choose file..."}
//             </button>
//             <button type="button" onClick={() => inputRef.current?.click()}
//               className="border border-l-0 border-gray-700 bg-gray-900 px-6 text-xs hover:text-white transition-colors">
//               BROWSE
//             </button>
//           </div>
//         </div>

//         {error && (
//           <p role="alert" className="col-span-2 border border-red-500/60 text-red-400 text-xs px-3 py-2">{error}</p>
//         )}

//         <button type="button" onClick={translate} disabled={busy} className={`col-span-2 ${primaryBtn}`}>
//           {busy ? "TRANSLATING..." : "TRANSLATE & ANALYZE"}
//         </button>
//       </div>

//       {result && (
//         <div className="mt-8 border border-gray-800 p-5">
//           <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
//             <h2 className="text-sm tracking-widest">TRANSLATED CONFIGURATION</h2>
//             <button type="button" onClick={download} className={outlineBtn}>DOWNLOAD .TXT</button>
//           </div>

//           {typeof result.overall_confidence === "number" && (
//             <p className="text-xs text-gray-400 mb-3">
//               Translation confidence: {Math.round(result.overall_confidence * 100)}%
//             </p>
//           )}
//           {result.warnings?.length > 0 && (
//             <ul className="list-disc pl-5 text-xs text-gray-400 mb-3">
//               {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
//             </ul>
//           )}

//           <pre className="border border-gray-800 p-4 text-xs text-gray-300 whitespace-pre-wrap overflow-x-auto mb-4">
//             {result.normalized_config || "(no commands produced)"}
//           </pre>

//           {summary ? (
//             <p className="text-xs text-gray-300">
//               Compliance check of the translated config:{" "}
//               <span className="text-white">{summary.passed} passed</span>,{" "}
//               <span className="text-red-400">{summary.failed} failed</span> of {summary.total} rules.
//             </p>
//           ) : (
//             <p className="text-xs text-gray-500">
//               Compliance check unavailable{handoff?.error ? `: ${handoff.error}` : "."}
//             </p>
//           )}
//         </div>
//       )}
//     </section>
//   );
// }