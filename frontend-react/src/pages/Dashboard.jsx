import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, Upload, RefreshCw, FileText, Plus, X } from "lucide-react";
import { useAuth } from "../components/AuthContext";
import NetworkGlobe from "../components/NetworkGlobe";

// ---- API settings -------------------------------------------------------
// Relative paths go through the Vite proxy to Django (http://127.0.0.1:8000).
const UPLOAD_URL = "/api/uploads/";
// TODO: confirm this against your script.js. It was not in the files I received.
const TRANSLATE_URL = "/api/translate/";

const VENDORS = [
  { value: "cisco", label: "Cisco" },
  { value: "juniper", label: "Juniper" },
];
const ACCEPT = ".txt,.conf,.cfg";
const selectClass =
  "w-full bg-black border border-gray-700 text-sm px-4 py-3 focus:outline-none focus:border-white transition-colors cursor-pointer";

// ---- One device row: vendor + file from the user's own computer ----------
function DeviceRow({ index, row, canRemove, onVendor, onFile, onRemove }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  const open = () => inputRef.current?.click();

  return (
    <div className="border border-gray-800 p-4 mb-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-gray-400">Device {index + 1}</span>
        {canRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove device ${index + 1}`}
            className="text-gray-600 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <label htmlFor={`vendor-${row.id}`} className="block text-[10px] text-gray-500 tracking-wider mb-2">
        VENDOR
      </label>
      <select
        id={`vendor-${row.id}`}
        value={row.vendor}
        onChange={(e) => onVendor(e.target.value)}
        className={`${selectClass} mb-4`}
      >
        {VENDORS.map((v) => (
          <option key={v.value} value={v.value}>{v.label}</option>
        ))}
      </select>

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = ""; // lets the same file be chosen again
        }}
      />
      <div
        role="button"
        tabIndex={0}
        onClick={open}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open())}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onFile(f);
        }}
        className={`border border-dashed p-6 text-center cursor-pointer transition-colors focus:outline-none focus:border-white ${
          dragging ? "border-white" : "border-gray-600 hover:border-white"
        }`}
      >
        <FileText className={`w-7 h-7 mx-auto mb-2 ${row.file ? "text-white" : "text-gray-600"}`} />
        {row.file ? (
          <>
            <p className="text-xs text-white break-all">{row.file.name}</p>
            <p className="text-[10px] text-gray-500 mt-1">
              {(row.file.size / 1024).toFixed(1)} KB. Click to choose a different file.
            </p>
          </>
        ) : (
          <>
            <p className="text-xs text-gray-400">Drop a config file here or click to browse your device</p>
            <p className="text-[10px] text-gray-600 mt-1">Supports .txt, .conf, .cfg</p>
          </>
        )}
      </div>
    </div>
  );
}

// ---- Result card for one analysed device ---------------------------------
function ResultCard({ entry }) {
  const { file, vendor, item, report, failed } = entry;
  const summary = report?.summary;

  return (
    <div className="border border-gray-800 bg-black/50 p-5 mb-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h3 className="text-sm break-all">{file}</h3>
        <span className="text-[10px] text-gray-500">{vendor}</span>
      </div>

      {failed && (
        <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2">
          Upload failed: {failed}
        </p>
      )}

      {item && !report && (
        <div className="text-xs text-gray-300 leading-relaxed">
          <p className="mb-2">
            Status: <span className="text-white">{item.status}</span>
          </p>
          {item.errors?.length > 0 && (
            <ul className="list-disc pl-5 text-gray-400 mb-2">
              {item.errors.map((er, i) => <li key={i}>{er}</li>)}
            </ul>
          )}
          {item.normalization_review?.length > 0 && (
            <p className="text-gray-400">
              {item.normalization_review.length} unknown command(s) need review before this device can be scored.
            </p>
          )}
        </div>
      )}

      {summary && (
        <>
          <p className="text-xs text-gray-300 mb-4">
            {summary.passed} of {summary.total} rules passed. {summary.failed} failed, including{" "}
            {summary.critical_high} critical or high.
          </p>
          <ul className="divide-y divide-gray-800 border border-gray-800">
            {report.results.map((r) => (
              <li key={r.rule_id} className="px-3 py-2 text-xs">
                <div className="flex items-start gap-3">
                  <span className={`w-10 shrink-0 ${r.status === "Pass" ? "text-white" : "text-red-400"}`}>
                    {r.status === "Pass" ? "PASS" : "FAIL"}
                  </span>
                  <div className="min-w-0">
                    <p className="text-gray-200">[{r.rule_id}] {r.name}</p>
                    <p className="text-[10px] text-gray-500 mt-0.5 break-words">
                      {r.field}. Expected: {String(r.expected)}. Actual: {String(r.actual)}
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

// ---- Page -----------------------------------------------------------------
export default function Dashboard() {
  const { user, session, signOut } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("audit");

  // Compliance audit
  const nextId = useRef(2);
  const [rows, setRows] = useState([{ id: 1, vendor: "cisco", file: null }]);
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Translation
  const [source, setSource] = useState("cisco");
  const [target, setTarget] = useState("junos");
  const [tFile, setTFile] = useState(null);
  const [tBusy, setTBusy] = useState(false);
  const [tOutput, setTOutput] = useState("");
  const [tError, setTError] = useState("");
  const tInput = useRef(null);

  const authHeader = () =>
    session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};

  const updateRow = (id, patch) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const addRow = () =>
    setRows((rs) => [...rs, { id: nextId.current++, vendor: "cisco", file: null }]);
  const removeRow = (id) => setRows((rs) => rs.filter((r) => r.id !== id));

  // One POST per device, then GET the stored report for each result.
  const analyze = async () => {
    const ready = rows.filter((r) => r.file);
    if (!ready.length) {
      return setError("Choose a configuration file for at least one device.");
    }
    setError("");
    setBusy(true);
    setResults([]);
    const out = [];

    for (const r of ready) {
      try {
        const fd = new FormData();
        fd.append("config", r.file);
        fd.append("vendor", r.vendor);
        const res = await fetch(UPLOAD_URL, { method: "POST", headers: authHeader(), body: fd });
        if (!res.ok) throw new Error(`server returned ${res.status}`);
        const data = await res.json();

        for (const item of data.results ?? []) {
          let report = null;
          try {
            const d = await fetch(`${UPLOAD_URL}${item.id}/`, { headers: authHeader() });
            if (d.ok) report = (await d.json()).compliance_report ?? null;
          } catch {
            /* the upload itself worked; show it without the full report */
          }
          out.push({ file: r.file.name, vendor: r.vendor, item, report });
        }
      } catch (err) {
        out.push({ file: r.file.name, vendor: r.vendor, failed: err.message });
      }
      setResults([...out]);
    }
    setBusy(false);
  };

  const translate = async () => {
    if (!tFile) return setTError("Choose a configuration file first.");
    setTError("");
    setTOutput("");
    setTBusy(true);
    try {
      const fd = new FormData();
      fd.append("config", tFile);
      fd.append("source_vendor", source);
      fd.append("target_vendor", target);
      const res = await fetch(TRANSLATE_URL, { method: "POST", headers: authHeader(), body: fd });
      const text = await res.text();
      if (!res.ok) throw new Error(`server returned ${res.status}`);
      try {
        setTOutput(JSON.stringify(JSON.parse(text), null, 2));
      } catch {
        setTOutput(text);
      }
    } catch (err) {
      setTError(err.message);
    }
    setTBusy(false);
  };

  const handleLogout = async () => {
    await signOut();
    navigate("/", { replace: true });
  };

  const queued = rows.filter((r) => r.file).length;
  const failedRules = results.reduce((n, e) => n + (e.report?.summary?.failed ?? 0), 0);

  const tabClass = (t) =>
    `flex items-center gap-3 text-xs tracking-wider p-3 text-left transition-colors ${
      activeTab === t
        ? "bg-white text-black"
        : "text-gray-400 hover:text-white border border-transparent hover:border-gray-700"
    }`;

  return (
    <div className="h-screen bg-black text-white font-mono flex flex-col overflow-hidden">
      {/* HEADER */}
      <header className="w-full flex justify-between items-center px-8 py-5 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2 text-xl font-bold tracking-widest">
          <Shield className="w-5 h-5" />
          Suraksha<span className="font-light">Asthri</span>
          <span className="ml-4 text-xs bg-white text-black px-2 py-0.5 tracking-widest hidden sm:inline">
            AUDITOR WORKSPACE
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span className="hidden md:inline">// {user?.email}</span>
          <button
            onClick={handleLogout}
            className="border border-gray-600 text-gray-200 px-4 py-1.5 hover:border-white hover:text-white transition-colors"
          >
            LOGOUT
          </button>
        </div>
      </header>

      <div className="flex flex-1 min-h-0">
        {/* SIDEBAR */}
        <aside className="w-56 shrink-0 border-r border-gray-800 p-6 flex flex-col gap-3">
          <div className="text-gray-500 text-[10px] tracking-widest mb-2 border-b border-gray-800 pb-2">
            MODULES
          </div>
          <button onClick={() => setActiveTab("audit")} className={tabClass("audit")}>
            <Upload className="w-4 h-4 shrink-0" /> COMPLIANCE AUDIT
          </button>
          <button onClick={() => setActiveTab("translate")} className={tabClass("translate")}>
            <RefreshCw className="w-4 h-4 shrink-0" /> VENDOR TRANSLATION
          </button>
        </aside>

        {/* MAIN */}
        <main className="flex-1 min-w-0 overflow-y-auto p-8 lg:p-12">
          <div className="max-w-2xl">
            {activeTab === "audit" && (
              <>
                <h1 className="text-3xl font-bold tracking-wide mb-2">AUTOMATE COMPLIANCE REVIEW</h1>
                <p className="text-gray-400 text-xs leading-relaxed mb-8">
                  Choose a vendor and upload a configuration from your device. Add more devices to audit
                  several in one run. Each file is checked against CIS and NIST rules.
                </p>

                <div className="border border-gray-800 p-6">
                  <h2 className="text-sm tracking-widest border-b border-gray-800 pb-4 mb-6">
                    UPLOAD CONFIGURATIONS
                  </h2>

                  {rows.map((row, i) => (
                    <DeviceRow
                      key={row.id}
                      index={i}
                      row={row}
                      canRemove={rows.length > 1}
                      onVendor={(v) => updateRow(row.id, { vendor: v })}
                      onFile={(f) => updateRow(row.id, { file: f })}
                      onRemove={() => removeRow(row.id)}
                    />
                  ))}

                  <button
                    type="button"
                    onClick={addRow}
                    className="w-full flex items-center justify-center gap-2 border border-gray-700 text-gray-400 py-3 text-xs tracking-widest hover:border-white hover:text-white transition-colors mb-4"
                  >
                    <Plus className="w-4 h-4" /> ADD ANOTHER DEVICE
                  </button>

                  {error && (
                    <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2 mb-4">
                      {error}
                    </p>
                  )}

                  <button
                    type="button"
                    onClick={analyze}
                    disabled={busy}
                    className="w-full border border-white bg-white text-black py-3 text-xs tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50"
                  >
                    {busy ? "ANALYZING..." : "ANALYZE CONFIGURATIONS"}
                  </button>
                </div>

                {results.length > 0 && (
                  <div className="mt-10">
                    <h2 className="text-sm tracking-widest border-b border-gray-800 pb-4 mb-6">
                      COMPLIANCE REPORT
                    </h2>
                    {results.map((entry, i) => (
                      <ResultCard key={i} entry={entry} />
                    ))}
                  </div>
                )}
              </>
            )}

            {activeTab === "translate" && (
              <>
                <h1 className="text-3xl font-bold tracking-wide mb-2">NETWORK CONFIG TRANSLATION</h1>
                <p className="text-gray-400 text-xs leading-relaxed mb-8">
                  Convert a device configuration from one vendor format to another.
                </p>

                <div className="border border-gray-800 p-6 grid grid-cols-2 gap-6">
                  <div className="col-span-2 sm:col-span-1">
                    <label htmlFor="src" className="block text-[10px] text-gray-500 tracking-wider mb-2">
                      SOURCE VENDOR
                    </label>
                    <select id="src" value={source} onChange={(e) => setSource(e.target.value)} className={selectClass}>
                      <option value="cisco">Cisco</option>
                    </select>
                  </div>
                  <div className="col-span-2 sm:col-span-1">
                    <label htmlFor="tgt" className="block text-[10px] text-gray-500 tracking-wider mb-2">
                      TARGET VENDOR
                    </label>
                    <select id="tgt" value={target} onChange={(e) => setTarget(e.target.value)} className={selectClass}>
                      <option value="junos">Junos / Juniper</option>
                      <option value="cisco">Cisco (passthrough)</option>
                    </select>
                  </div>

                  <div className="col-span-2">
                    <span className="block text-[10px] text-gray-500 tracking-wider mb-2">
                      CONFIGURATION FILE
                    </span>
                    <input
                      ref={tInput}
                      type="file"
                      accept={ACCEPT}
                      className="hidden"
                      onChange={(e) => setTFile(e.target.files?.[0] ?? null)}
                    />
                    <div className="flex">
                      <button
                        type="button"
                        onClick={() => tInput.current?.click()}
                        className="flex-1 text-left border border-gray-700 text-sm px-4 py-3 text-gray-400 hover:border-white hover:text-white transition-colors truncate"
                      >
                        {tFile ? tFile.name : "Choose file..."}
                      </button>
                      <button
                        type="button"
                        onClick={() => tInput.current?.click()}
                        className="border border-l-0 border-gray-700 bg-gray-900 px-6 text-xs hover:text-white transition-colors"
                      >
                        BROWSE
                      </button>
                    </div>
                  </div>

                  {tError && (
                    <p role="alert" className="col-span-2 border border-red-500/60 text-red-400 text-xs px-3 py-2">
                      {tError}
                    </p>
                  )}

                  <button
                    type="button"
                    onClick={translate}
                    disabled={tBusy}
                    className="col-span-2 border border-white bg-white text-black py-3 text-xs tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50"
                  >
                    {tBusy ? "TRANSLATING..." : "TRANSLATE & ANALYZE"}
                  </button>
                </div>

                {tOutput && (
                  <pre className="mt-6 border border-gray-800 p-4 text-xs text-gray-300 whitespace-pre-wrap overflow-x-auto">
                    {tOutput}
                  </pre>
                )}
              </>
            )}
          </div>
        </main>

        {/* GLOBE PANEL (large screens) */}
        <aside className="hidden xl:block w-[38%] shrink-0 border-l border-gray-800 relative">
          <div className="absolute inset-0">
            <NetworkGlobe />
          </div>
          <dl className="absolute bottom-0 left-0 right-0 grid grid-cols-3 border-t border-gray-800 bg-black/80 text-center">
            {[
              ["Devices queued", queued],
              ["Audits run", results.length],
              ["Rules failed", failedRules],
            ].map(([label, value]) => (
              <div key={label} className="py-4 border-r border-gray-800 last:border-r-0">
                <dd className="text-2xl font-bold">{value}</dd>
                <dt className="text-[10px] text-gray-500 mt-1">{label}</dt>
              </div>
            ))}
          </dl>
        </aside>
      </div>
    </div>
  );
}
// import { useState } from "react";
// import { useAuth } from "../components/AuthContext";

// export default function Dashboard({ title = "Dashboard" }) {
//   const { user, role, session, signOut } = useAuth();
//   const [apiResult, setApiResult] = useState("");

//   // Sends the Supabase token to Django, which verifies it and checks the role.
//   const testDjango = async () => {
//     setApiResult("Calling Django...");
//     try {
//       const res = await fetch("/api/me/", {
//         headers: { Authorization: `Bearer ${session.access_token}` },
//       });
//       setApiResult(`${res.status}: ${await res.text()}`);
//     } catch (err) {
//       setApiResult(`Request failed: ${err.message}`);
//     }
//   };

//   return (
//     <div className="min-h-screen bg-black text-white font-mono px-8 py-10">
//       <div className="max-w-xl border border-gray-700 p-8">
//         <h1 className="text-2xl font-bold mb-6">{title}</h1>
//         <p className="text-sm text-gray-400">Signed in as</p>
//         <p className="mb-4">{user?.email}</p>
//         <p className="text-sm text-gray-400">Role</p>
//         <p className="mb-8">{role ?? "loading..."}</p>

//         <div className="flex gap-3">
//           <button onClick={testDjango}
//             className="border border-gray-600 px-4 py-2 text-[11px] tracking-widest hover:border-white transition-colors">
//             TEST DJANGO API
//           </button>
//           <button onClick={signOut}
//             className="border border-white bg-white text-black px-4 py-2 text-[11px] tracking-widest hover:bg-transparent hover:text-white transition-colors">
//             LOGOUT
//           </button>
//         </div>
//         {apiResult && <pre className="mt-6 text-xs text-gray-300 whitespace-pre-wrap">{apiResult}</pre>}
//       </div>
//     </div>
//   );
// }