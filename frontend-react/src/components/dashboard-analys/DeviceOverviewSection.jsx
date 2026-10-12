import { Fragment, useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useAuth } from "../AuthContext";
import {
  authHeaders,
  labelClass,
  outlineBtn,
  selectClass,
  typeLabel,
} from "../dashboard/dashboardApi";
import SectionHeader from "../dashboard/SectionHeader";
import useFrameworks from "./useFrameworks";
import DeviceChangesPanel from "./DeviceChangesPanel";

const STATUS = {
  compliant: ["COMPLIANT", "text-white"],
  non_compliant: ["NON-COMPLIANT", "text-red-400"],
  not_audited: ["NOT AUDITED", "text-gray-500"],
};
const CHANGE = {
  initial: ["FIRST SNAPSHOT", "text-gray-400"],
  changed: ["CHANGED", "text-white"],
  no_effective_change: ["NO EFFECTIVE CHANGE", "text-gray-500"],
};

// GET /api/analysis/overview/ : one concise row per device, latest audit only.
export default function DeviceOverviewSection({ onAnalyze }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const frameworks = useFrameworks(token);
  const [framework, setFramework] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const qs = framework ? `?framework=${framework}` : "";
      const res = await fetch(`/api/analysis/overview/${qs}`, {
        headers: authHeaders(token),
      });
      if (!res.ok) throw new Error(`server returned ${res.status}`);
      setData(await res.json());
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  }, [token, framework]);

  useEffect(() => {
    load();
  }, [load]);

  const t = data?.totals;
  const cards = t && [
    ["DEVICES", t.devices],
    ["AUDITED", t.audited],
    ["COMPLIANT", t.compliant],
    ["NON-COMPLIANT", t.non_compliant],
    ["CHANGED", t.changed],
    ["AVG SCORE", t.average_score == null ? "-" : `${t.average_score}%`],
  ];

  return (
    <section>
      <SectionHeader title="DEVICE STATUS">
        The latest audit of every device: its status, how many rules passed and
        failed, and whether its configuration changed since the previous
        snapshot. Open a device for the details.
      </SectionHeader>

      <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
        <div className="w-56">
          <label htmlFor="ov-framework" className={labelClass}>
            BENCHMARK
          </label>
          <select
            id="ov-framework"
            value={framework}
            onChange={(e) => setFramework(e.target.value)}
            className={selectClass}
          >
            <option value="">All benchmarks</option>
            {frameworks.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label ?? f.id}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={load}
          className={`${outlineBtn} flex items-center gap-2`}
        >
          <RefreshCw className="w-3 h-3" /> REFRESH
        </button>
      </div>

      {cards && (
        <dl className="grid grid-cols-3 sm:grid-cols-6 text-center border border-gray-800 mb-6">
          {cards.map(([k, v]) => (
            <div
              key={k}
              className="py-4 border-r border-b sm:border-b-0 border-gray-800 last:border-r-0"
            >
              <dd className="text-2xl font-bold">{v}</dd>
              <dt className="text-[10px] text-gray-500 mt-1">{k}</dt>
            </div>
          ))}
        </dl>
      )}

      {loading && (
        <p className="text-xs text-gray-500 text-center">Loading...</p>
      )}
      {error && (
        <p
          role="alert"
          className="border border-red-500/60 text-red-400 text-xs px-3 py-2"
        >
          Could not load the overview: {error}
        </p>
      )}
      {!loading && !error && data?.devices.length === 0 && (
        <p className="text-xs text-gray-500 text-center">
          No devices registered yet.
        </p>
      )}

      {data?.devices.length > 0 && (
        <div className="border border-gray-800 overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="text-[10px] text-gray-500 tracking-wider border-b border-gray-800">
              <tr>
                {[
                  "DEVICE",
                  "TENANT · SITE",
                  "STATUS",
                  "SCORE",
                  "PASSED",
                  "FAILED",
                  "CONFIG",
                  "LAST AUDIT",
                  "",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 font-normal whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {data.devices.map((d) => {
                const [statusText, statusClass] =
                  STATUS[d.status] ?? STATUS.not_audited;
                const [changeText, changeClass] = CHANGE[d.change_status] ?? [
                  "-",
                  "text-gray-600",
                ];
                const l = d.latest;
                return (
                  <Fragment key={d.device_id}>
                    <tr>
                      <td className="px-4 py-3">
                        <p className="whitespace-nowrap">{d.device_id}</p>
                        <p className="text-[10px] text-gray-500">
                          {d.hostname} · {d.vendor} {typeLabel(d.device_type)}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        {d.tenant}
                        {d.site ? ` · ${d.site}` : ""}
                      </td>
                      <td
                        className={`px-4 py-3 whitespace-nowrap ${statusClass}`}
                      >
                        {statusText}
                      </td>
                      <td className="px-4 py-3">
                        {l?.score != null ? `${l.score}%` : "-"}
                      </td>
                      <td className="px-4 py-3">{l?.pass_count ?? "-"}</td>
                      <td className="px-4 py-3 text-red-400">
                        {l?.fail_count ?? "-"}
                      </td>
                      <td className="px-4 py-3">
                        <p className={`whitespace-nowrap ${changeClass}`}>
                          {changeText}
                        </p>
                        {d.change_status === "changed" && (
                          <p className="text-[10px]">
                            <span className="text-green-400">
                              +{d.lines_added}
                            </span>{" "}
                            <span className="text-red-400">
                              -{d.lines_removed}
                            </span>{" "}
                            lines
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {l ? (
                          <>
                            <p>{new Date(l.uploaded_at).toLocaleString()}</p>
                            <p className="text-[10px] text-gray-500">
                              by {l.uploaded_by}
                            </p>
                          </>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {l && (
                          <button
                            type="button"
                            className="text-gray-400 hover:text-white underline"
                            onClick={() =>
                              setOpen(open === d.device_id ? null : d.device_id)
                            }
                          >
                            {open === d.device_id ? "HIDE" : "DETAILS"}
                          </button>
                        )}
                      </td>
                    </tr>
                    {open === d.device_id && (
                      <tr>
                        <td colSpan={9} className="px-4 py-4 bg-gray-950">
                          <DeviceChangesPanel
                            deviceId={d.device_id}
                            framework={framework}
                            onAnalyze={onAnalyze}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
