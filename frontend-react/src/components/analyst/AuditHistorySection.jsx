import { useCallback, useState } from "react";
import { useAuth } from "../AuthContext";
import { authHeaders } from "../dashboard/dashboardApi";
import CriteriaList from "./CriteriaList";
import {
  STATUS_BADGE,
  btn,
  formatWhen,
  inputClass,
  labelClass,
  relativeTime,
  usePolling,
} from "./scheduleUi";

const FRAMEWORK_FILTERS = [
  ["", "All frameworks"],
  ["CIS", "CIS"],
  ["NIST", "NIST"],
  ["STIG", "STIG"],
  ["ISO", "ISO 27001"],
];
const barColor = (score) =>
  score >= 80 ? "bg-green-500" : score >= 50 ? "bg-yellow-500" : "bg-red-500";

export default function AuditHistorySection({ devices }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [deviceId, setDeviceId] = useState("");
  const [framework, setFramework] = useState("");
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [visible, setVisible] = useState(25);
  const [openId, setOpenId] = useState(null);
  const [details, setDetails] = useState({}); // run id -> { data | error | loading }

  // GET /api/devices/<id>/audits/ now, then every 30 seconds.
  const load = useCallback(async () => {
    if (!token || !deviceId) return;
    try {
      const q = framework ? `&framework=${framework}` : "";
      const res = await fetch(
        `/api/devices/${deviceId}/audits/?limit=200${q}`,
        { headers: authHeaders(token) },
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok)
        throw new Error(data.error || `server returned ${res.status}`);
      setRuns(data.runs ?? []);
      setError("");
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  }, [token, deviceId, framework]);
  usePolling(
    load,
    30000,
    deviceId ? `${deviceId}|${framework}|${token}` : null,
  );

  const pickDevice = (id) => {
    setDeviceId(id);
    setRuns([]);
    setOpenId(null);
    setVisible(25);
    setError("");
    setLoading(Boolean(id));
  };

  // GET /api/audit-runs/<id>/ : every criterion of one audit.
  const toggleRun = async (run) => {
    if (openId === run.id) return setOpenId(null);
    setOpenId(run.id);
    if (!run.result || details[run.id]?.data) return;
    setDetails((d) => ({ ...d, [run.id]: { loading: true } }));
    try {
      const res = await fetch(`/api/audit-runs/${run.id}/`, {
        headers: authHeaders(token),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok)
        throw new Error(data.error || `server returned ${res.status}`);
      setDetails((d) => ({ ...d, [run.id]: { data } }));
    } catch (err) {
      setDetails((d) => ({ ...d, [run.id]: { error: err.message } }));
    }
  };

  const okRuns = runs.filter((r) => r.result);
  const latest = okRuns[0];
  const trend = okRuns.slice(0, 40).reverse();
  const changed = new Set(); // audits whose findings differ from the one before
  okRuns.forEach((r, i) => {
    if (okRuns[i + 1] && okRuns[i + 1].result.id !== r.result.id)
      changed.add(r.id);
  });
  const device = devices.find((d) => d.device_id === deviceId);

  return (
    <section>
      <h1 className="text-3xl font-bold tracking-wide mb-2">AUDIT HISTORY</h1>
      <p className="text-base text-gray-300 leading-relaxed mb-8 max-w-3xl">
        Every scheduled audit of a device with its time, score and the criteria
        that passed or failed. This page refreshes by itself every 30 seconds.
      </p>

      <div className="grid sm:grid-cols-2 gap-6 mb-8">
        <div>
          <label htmlFor="hd" className={labelClass}>
            DEVICE
          </label>
          <select
            id="hd"
            value={deviceId}
            onChange={(e) => pickDevice(e.target.value)}
            className={`${inputClass} cursor-pointer`}
          >
            <option value="">Select a device</option>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.device_id} · {d.hostname}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="hf" className={labelClass}>
            FRAMEWORK
          </label>
          <select
            id="hf"
            value={framework}
            onChange={(e) => {
              setFramework(e.target.value);
              setRuns([]);
              setOpenId(null);
            }}
            className={`${inputClass} cursor-pointer`}
          >
            {FRAMEWORK_FILTERS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!deviceId && (
        <p className="text-base text-gray-300">
          Choose a device to see its audit history.
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="border border-red-500/60 text-red-400 text-base px-4 py-3 mb-5"
        >
          {error}
        </p>
      )}
      {deviceId && loading && (
        <p className="text-base text-gray-300">Loading audits...</p>
      )}

      {deviceId && !loading && !error && runs.length === 0 && (
        <p className="text-base text-gray-300 leading-relaxed border border-gray-700 px-5 py-4">
          No audits recorded for {device?.hostname ?? deviceId} yet. Add it to
          an audit schedule, make sure it has a pushed configuration, and make
          sure the scheduler is running.
        </p>
      )}

      {latest && (
        <div className="mb-8">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <h2 className="text-sm tracking-widest text-gray-200">
              LATEST RESULT
            </h2>
            <span className="text-sm text-gray-300">
              {formatWhen(latest.ran_at)} ({relativeTime(latest.ran_at)}) ·{" "}
              {latest.framework}
            </span>
          </div>
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            {[
              ["SCORE", `${latest.result.score}%`, "text-white"],
              ["PASSED", latest.result.pass_count, "text-green-400"],
              ["FAILED", latest.result.fail_count, "text-red-400"],
              ["UNDECIDED", latest.result.unknown_count, "text-yellow-400"],
            ].map(([k, v, c]) => (
              <div key={k} className="border border-gray-700 py-5 text-center">
                <dd className={`text-4xl font-bold ${c}`}>{v}</dd>
                <dt className="text-xs tracking-widest text-gray-400 mt-2">
                  {k}
                </dt>
              </div>
            ))}
          </dl>

          <h2 className="text-sm tracking-widest text-gray-200 mb-3">
            SCORE OVER TIME (OLDEST TO NEWEST)
          </h2>
          <div className="border border-gray-700 p-4">
            <div className="flex items-end gap-1 h-28">
              {trend.map((r) => (
                <div
                  key={r.id}
                  title={`${formatWhen(r.ran_at)} · ${r.result.score}%`}
                  className={`flex-1 max-w-[24px] min-w-[5px] ${barColor(r.result.score)}`}
                  style={{ height: `${Math.max(4, r.result.score)}%` }}
                />
              ))}
            </div>
            <p className="text-sm text-gray-400 mt-3">
              Green is 80% or more, yellow 50–79%, red below 50%. Hover a bar
              for its time.
            </p>
          </div>
        </div>
      )}

      {runs.length > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <h2 className="text-sm tracking-widest text-gray-200">
              AUDITS RECORDED ({runs.length})
            </h2>
            <button type="button" onClick={load} className={btn}>
              REFRESH NOW
            </button>
          </div>

          <ul className="divide-y divide-gray-800 border border-gray-700">
            {runs.slice(0, visible).map((r) => {
              const open = openId === r.id;
              const d = details[r.id];
              return (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => toggleRun(r)}
                    aria-expanded={open}
                    className="w-full text-left px-5 py-4 hover:bg-gray-900 transition-colors"
                  >
                    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                      <span className="text-base text-white">
                        {formatWhen(r.ran_at)}
                      </span>
                      <span className="text-sm text-gray-400">
                        {relativeTime(r.ran_at)}
                      </span>
                      <span
                        className={`text-xs tracking-widest border px-3 py-1 ${STATUS_BADGE[r.status] ?? ""}`}
                      >
                        {r.status.toUpperCase()}
                      </span>
                      <span className="text-sm text-gray-300">
                        {r.framework}
                      </span>
                      {changed.has(r.id) && (
                        <span className="text-xs tracking-widest border border-yellow-500/60 text-yellow-300 px-3 py-1">
                          RESULT CHANGED
                        </span>
                      )}
                      <span className="ml-auto text-sm text-gray-400">
                        {open ? "HIDE" : "DETAILS"}
                      </span>
                    </div>
                    <p
                      className={`text-base mt-2 ${r.status === "ok" ? "text-gray-100" : "text-yellow-200"}`}
                    >
                      {r.result ? `${r.result.score}% · ` : ""}
                      {r.message}
                    </p>
                  </button>

                  {open && (
                    <div className="px-5 pb-6 pt-2 bg-gray-950">
                      {!r.result && (
                        <p className="text-base text-gray-300">
                          No result was recorded for this audit.
                        </p>
                      )}
                      {d?.loading && (
                        <p className="text-base text-gray-300">
                          Loading criteria...
                        </p>
                      )}
                      {d?.error && (
                        <p role="alert" className="text-red-400 text-base">
                          {d.error}
                        </p>
                      )}
                      {d?.data && (
                        <>
                          <p className="text-sm text-gray-400 mb-4">
                            Configuration snapshot #{r.result.snapshot_id} ·{" "}
                            {d.data.criteria.length} criteria checked
                          </p>
                          <CriteriaList criteria={d.data.criteria} />
                        </>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>

          {visible < runs.length && (
            <button
              type="button"
              onClick={() => setVisible((v) => v + 25)}
              className={`${btn} mt-4`}
            >
              SHOW 25 MORE
            </button>
          )}
        </>
      )}
    </section>
  );
}
