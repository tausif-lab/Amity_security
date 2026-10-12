import { useEffect, useRef, useState } from "react";
import { useAuth } from "../AuthContext";
import { authHeaders, jsonHeaders, primaryBtn } from "../dashboard/dashboardApi";
import SectionHeader from "../dashboard/SectionHeader";
import QueryResults from "./QueryResults";

const FALLBACK_EXAMPLES = [
  "which devices have http enabled",
  "telnet is on in tenant Acme",
  "devices using the public snmp community",
  "not running ssh version 2",
];

// POST /api/analysis/query/        : question -> validated filter -> devices
// GET  /api/analysis/query/fields/ : what can be asked, plus example questions
export default function DeviceQuerySection({ onAnalyze }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);      // the last response from the server
  const [error, setError] = useState("");
  const [history, setHistory] = useState([]);
  const [help, setHelp] = useState({ fields: [], examples: FALLBACK_EXAMPLES });
  const latest = useRef(0);                         // ignores answers to older questions

  useEffect(() => {
    if (!token) return;
    let live = true;
    fetch("/api/analysis/query/fields/", { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => live && setHelp({ fields: d.fields ?? [], examples: d.examples?.length ? d.examples : FALLBACK_EXAMPLES }))
      .catch(() => {});
    return () => { live = false; };
  }, [token]);

  const ask = async (text) => {
    const q = (text ?? question).trim();
    if (!q) return setError("Type a question first.");
    setQuestion(q);
    setError("");
    setResult(null);
    setBusy(true);
    const id = ++latest.current;
    try {
      const res = await fetch("/api/analysis/query/", {
        method: "POST", headers: jsonHeaders(token), body: JSON.stringify({ question: q }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
      if (id !== latest.current) return;
      setResult(data);
      setHistory((h) => [q, ...h.filter((x) => x !== q)].slice(0, 5));
    } catch (err) {
      if (id === latest.current) setError(err.message);
    }
    if (id === latest.current) setBusy(false);
  };

  const chip = "border border-gray-700 text-gray-400 text-[11px] px-3 py-1.5 hover:border-white hover:text-white transition-colors disabled:opacity-50";

  return (
    <section>
      <SectionHeader title="ASK ABOUT YOUR DEVICES">
        Ask in plain English, for example "which devices have HTTP enabled". The AI only reads your
        question. The answer comes from the stored configuration of each device.
      </SectionHeader>

      <form onSubmit={(e) => { e.preventDefault(); ask(); }} className="border border-gray-800 p-6">
        <label htmlFor="nl-question" className="block text-[10px] text-gray-500 tracking-wider mb-2">YOUR QUESTION</label>
        <input id="nl-question" value={question} onChange={(e) => setQuestion(e.target.value)}
          maxLength={300} disabled={busy} autoComplete="off"
          placeholder="Which devices have telnet enabled?"
          className="w-full bg-black border border-gray-700 text-sm px-4 py-3 mb-4 focus:outline-none focus:border-white transition-colors disabled:opacity-60" />

        <button type="submit" disabled={busy} className={primaryBtn}>{busy ? "THINKING..." : "ASK"}</button>

        <div className="mt-5">
          <p className="text-[10px] text-gray-500 tracking-wider mb-2">TRY ONE OF THESE</p>
          <div className="flex flex-wrap gap-2">
            {help.examples.map((ex) => (
              <button key={ex} type="button" disabled={busy} onClick={() => ask(ex)} className={chip}>{ex}</button>
            ))}
          </div>
        </div>

        {history.length > 1 && (
          <div className="mt-4">
            <p className="text-[10px] text-gray-500 tracking-wider mb-2">RECENT</p>
            <div className="flex flex-wrap gap-2">
              {history.slice(1).map((h) => (
                <button key={h} type="button" disabled={busy} onClick={() => ask(h)} className={chip}>{h}</button>
              ))}
            </div>
          </div>
        )}

        {help.fields.length > 0 && (
          <details className="mt-5">
            <summary className="text-[10px] text-gray-500 tracking-wider cursor-pointer">WHAT CAN I ASK ABOUT?</summary>
            <ul className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6 text-[11px] text-gray-400">
              {help.fields.map((f) => <li key={f.field} className="py-0.5">{f.label}</li>)}
            </ul>
          </details>
        )}
      </form>

      {busy && (
        <p role="status" className="text-xs text-gray-400 text-center mt-6">
          The AI is reading your question. The first question after a restart can take a little longer.
        </p>
      )}
      {error && (
        <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2 mt-6">{error}</p>
      )}

      {result?.status === "unsupported" && (
        <div className="border border-gray-700 px-4 py-4 mt-6 text-xs">
          <p className="text-gray-200 mb-2">{result.message}</p>
          {result.supported?.length > 0 && (
            <p className="text-[10px] text-gray-500 leading-relaxed">
              You can ask about: {result.supported.map((f) => f.label).join(", ")}.
            </p>
          )}
        </div>
      )}

      {result?.status === "ok" && <QueryResults result={result} onAnalyze={onAnalyze} />}
    </section>
  );
}