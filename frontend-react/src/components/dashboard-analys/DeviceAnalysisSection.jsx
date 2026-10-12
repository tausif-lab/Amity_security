import { useEffect, useState } from "react";
import { useAuth } from "../AuthContext";
import { authHeaders, labelClass, selectClass } from "../dashboard/dashboardApi";
import SectionHeader from "../dashboard/SectionHeader";
import useFrameworks from "./useFrameworks";
import { LineChart, StackedBarChart, RuleFailureList, shortDate } from "./AnalysisCharts";

const MAX_POINTS = 30;   // charts show the most recent snapshots

function ChartBlock({ title, note, children }) {
  return (
    <div className="border border-gray-800 p-5 mb-6">
      <h3 className="text-xs tracking-widest mb-1">{title}</h3>
      {note && <p className="text-[10px] text-gray-500 mb-4">{note}</p>}
      {children}
    </div>
  );
}

// GET /api/devices/<id>/analysis/ : graphs for one device, built from its snapshot timeline.
export default function DeviceAnalysisSection({ devices, loading, initialDeviceId }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const frameworks = useFrameworks(token);
  const [deviceId, setDeviceId] = useState(initialDeviceId ?? "");
  const [framework, setFramework] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { if (initialDeviceId) setDeviceId(initialDeviceId); }, [initialDeviceId]);
  useEffect(() => { if (!deviceId && devices.length) setDeviceId(devices[0].device_id); }, [devices, deviceId]);

  useEffect(() => {
    if (!token || !deviceId) return;
    let live = true;
    setBusy(true);
    setError("");
    const qs = framework ? `?framework=${framework}` : "";
    fetch(`/api/devices/${deviceId}/analysis/${qs}`, { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`server returned ${r.status}`))))
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [deviceId, framework, token]);

  const timeline = (data?.timeline ?? []).slice(-MAX_POINTS).map((t) => ({
    ...t, label: new Date(t.uploaded_at).toLocaleString(), short: shortDate(t.uploaded_at),
  }));
  const scored = timeline.filter((t) => t.result);
  const latestScore = scored.length ? scored[scored.length - 1].result.score : null;
  const avgScore = scored.length
    ? Math.round((10 * scored.reduce((s, t) => s + t.result.score, 0)) / scored.length) / 10 : null;
  const ruleRows = (data?.rule_stats ?? [])
    .filter((r) => r.failed > 0)
    .sort((a, b) => b.failed - a.failed)
    .slice(0, 10)
    .map((r) => ({ name: r.rule_id, label: `[${r.rule_id}] ${r.name}`, failed: r.failed, total: r.failed + r.passed }));
  const alwaysPassing = (data?.rule_stats ?? []).filter((r) => r.failed === 0 && r.passed > 0).length;

  return (
    <section>
      <SectionHeader title="DEVICE ANALYSIS">
        How one device's audits have moved over time: scores, passed and failed rules, configuration
        changes, and the rules that fail most often.
      </SectionHeader>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
        <div>
          <label htmlFor="an-device" className={labelClass}>DEVICE</label>
          <select id="an-device" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className={selectClass}>
            <option value="">{loading ? "Loading devices..." : "Select a device"}</option>
            {devices.map((d) => <option key={d.device_id} value={d.device_id}>{d.device_id} · {d.hostname}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="an-framework" className={labelClass}>BENCHMARK</label>
          <select id="an-framework" value={framework} onChange={(e) => setFramework(e.target.value)} className={selectClass}>
            <option value="">All benchmarks</option>
            {frameworks.map((f) => <option key={f.id} value={f.id}>{f.label ?? f.id}</option>)}
          </select>
        </div>
      </div>

      {!loading && devices.length === 0 && (
        <p className="text-xs text-gray-500 text-center">No devices registered yet.</p>
      )}
      {busy && <p className="text-xs text-gray-500 text-center">Loading...</p>}
      {error && (
        <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2 mb-4">
          Could not load the analysis: {error}
        </p>
      )}

      {data && !busy && data.snapshot_count === 0 && (
        <p className="text-xs text-gray-500 text-center">
          No snapshots for {data.device.device_id} yet. Push an audit result from the auditor workspace to start its history.
        </p>
      )}

      {data && !busy && data.snapshot_count > 0 && (
        <>
          <dl className="grid grid-cols-2 sm:grid-cols-4 text-center border border-gray-800 mb-6">
            {[["SNAPSHOTS", data.snapshot_count], ["LATEST SCORE", latestScore == null ? "-" : `${latestScore}%`],
              ["AVERAGE SCORE", avgScore == null ? "-" : `${avgScore}%`], ["RULES EVER FAILED", ruleRows.length]].map(([k, v]) => (
              <div key={k} className="py-4 border-r border-gray-800 last:border-r-0">
                <dd className="text-2xl font-bold">{v}</dd>
                <dt className="text-[10px] text-gray-500 mt-1">{k}</dt>
              </div>
            ))}
          </dl>

          <ChartBlock title="COMPLIANCE SCORE OVER TIME" note="Share of rules passed in each pushed snapshot.">
            {scored.length === 0 ? <p className="text-xs text-gray-500">No scored audits yet.</p> : (
              <LineChart title="Compliance score over time"
                points={scored.map((t) => ({ label: t.label, short: t.short, value: t.result.score }))} />
            )}
          </ChartBlock>

          <ChartBlock title="PASSED VS FAILED RULES" note="Rule outcomes in each snapshot.">
            <StackedBarChart title="Passed and failed rules per snapshot"
              data={scored.map((t) => ({ label: t.label, short: t.short,
                values: { pass: t.result.pass_count, fail: t.result.fail_count, unknown: t.result.unknown_count } }))}
              series={[{ key: "pass", label: "Passed", color: "#ffffff" },
                       { key: "fail", label: "Failed", color: "#ef4444" },
                       { key: "unknown", label: "Undecided", color: "#4b5563" }]} />
          </ChartBlock>

          <ChartBlock title="CONFIGURATION CHANGES" note="Lines added and removed compared with the previous snapshot.">
            <StackedBarChart title="Lines changed per snapshot"
              data={timeline.map((t) => ({ label: t.label, short: t.short,
                values: { added: t.lines_added, removed: t.lines_removed } }))}
              series={[{ key: "added", label: "Lines added", color: "#22c55e" },
                       { key: "removed", label: "Lines removed", color: "#ef4444" }]} />
          </ChartBlock>

          <ChartBlock title="RULES THAT FAIL MOST OFTEN"
            note={alwaysPassing ? `${alwaysPassing} other rule(s) passed in every audit.` : undefined}>
            {ruleRows.length === 0
              ? <p className="text-xs text-gray-500">No rule has failed in any audit of this device.</p>
              : <RuleFailureList rows={ruleRows} />}
          </ChartBlock>

          {data.frameworks.length > 0 && (
            <ChartBlock title="BY BENCHMARK">
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead className="text-[10px] text-gray-500 border-b border-gray-800">
                    <tr>{["BENCHMARK", "AUDITS", "AVG SCORE", "RULES PASSED", "RULES FAILED"].map((h) => (
                      <th key={h} className="py-2 pr-4 font-normal whitespace-nowrap">{h}</th>))}</tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {data.frameworks.map((f) => (
                      <tr key={f.framework}>
                        <td className="py-2 pr-4">{f.framework}</td><td className="py-2 pr-4">{f.audits}</td>
                        <td className="py-2 pr-4">{f.average_score}%</td><td className="py-2 pr-4">{f.rules_passed}</td>
                        <td className="py-2 pr-4 text-red-400">{f.rules_failed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </ChartBlock>
          )}
        </>
      )}
    </section>
  );
}