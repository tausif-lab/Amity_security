import { useRef, useState } from "react";
import { useAuth } from "../AuthContext";
import { ACCEPT, downloadBlob, labelClass, outlineBtn, primaryBtn, selectClass } from "./dashboardApi";
import SectionHeader from "./SectionHeader";

export default function VendorTranslatorSection() {
  const { session } = useAuth();
  const token = session?.access_token;
  const [source, setSource] = useState("cisco");
  const [target, setTarget] = useState("junos");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const inputRef = useRef(null);

  // POST /api/translate/upload (FastAPI, port 8001 through the Vite proxy)
  const translate = async () => {
    if (!file) return setError("Choose a configuration file first.");
    setError("");
    setResult(null);
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
  const summary = handoff?.compliance_report?.summary;

  return (
    <section>
      <SectionHeader title="NETWORK CONFIG TRANSLATION">
        Convert a device configuration from one vendor format to another, then check the result.
      </SectionHeader>

      <div className="border border-gray-800 p-6 grid grid-cols-2 gap-6">
        <div className="col-span-2 sm:col-span-1">
          <label htmlFor="src" className={labelClass}>SOURCE VENDOR</label>
          <select id="src" value={source} onChange={(e) => setSource(e.target.value)} className={selectClass}>
            <option value="cisco">Cisco</option>
          </select>
        </div>
        <div className="col-span-2 sm:col-span-1">
          <label htmlFor="tgt" className={labelClass}>TARGET VENDOR</label>
          <select id="tgt" value={target} onChange={(e) => setTarget(e.target.value)} className={selectClass}>
            <option value="junos">Junos / Juniper</option>
            <option value="cisco">Cisco (passthrough)</option>
          </select>
        </div>

        <div className="col-span-2">
          <span className={labelClass}>CONFIGURATION FILE</span>
          <input ref={inputRef} type="file" accept={ACCEPT} className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="flex">
            <button type="button" onClick={() => inputRef.current?.click()}
              className="flex-1 text-left border border-gray-700 text-sm px-4 py-3 text-gray-400 hover:border-white hover:text-white transition-colors truncate">
              {file ? file.name : "Choose file..."}
            </button>
            <button type="button" onClick={() => inputRef.current?.click()}
              className="border border-l-0 border-gray-700 bg-gray-900 px-6 text-xs hover:text-white transition-colors">
              BROWSE
            </button>
          </div>
        </div>

        {error && (
          <p role="alert" className="col-span-2 border border-red-500/60 text-red-400 text-xs px-3 py-2">{error}</p>
        )}

        <button type="button" onClick={translate} disabled={busy} className={`col-span-2 ${primaryBtn}`}>
          {busy ? "TRANSLATING..." : "TRANSLATE & ANALYZE"}
        </button>
      </div>

      {result && (
        <div className="mt-8 border border-gray-800 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h2 className="text-sm tracking-widest">TRANSLATED CONFIGURATION</h2>
            <button type="button" onClick={download} className={outlineBtn}>DOWNLOAD .TXT</button>
          </div>

          {typeof result.overall_confidence === "number" && (
            <p className="text-xs text-gray-400 mb-3">
              Translation confidence: {Math.round(result.overall_confidence * 100)}%
            </p>
          )}
          {result.warnings?.length > 0 && (
            <ul className="list-disc pl-5 text-xs text-gray-400 mb-3">
              {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}

          <pre className="border border-gray-800 p-4 text-xs text-gray-300 whitespace-pre-wrap overflow-x-auto mb-4">
            {result.normalized_config || "(no commands produced)"}
          </pre>

          {summary ? (
            <p className="text-xs text-gray-300">
              Compliance check of the translated config:{" "}
              <span className="text-white">{summary.passed} passed</span>,{" "}
              <span className="text-red-400">{summary.failed} failed</span> of {summary.total} rules.
            </p>
          ) : (
            <p className="text-xs text-gray-500">
              Compliance check unavailable{handoff?.error ? `: ${handoff.error}` : "."}
            </p>
          )}
        </div>
      )}
    </section>
  );
}