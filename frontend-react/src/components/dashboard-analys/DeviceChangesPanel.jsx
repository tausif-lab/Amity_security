import { useEffect, useState } from "react";
import { useAuth } from "../AuthContext";
import { authHeaders, outlineBtn } from "../dashboard/dashboardApi";

const FLIP_STYLE = { Pass: "text-white", Fail: "text-red-400" };

// GET /api/devices/<id>/analysis/ : what changed in the latest snapshot of one device.
export default function DeviceChangesPanel({ deviceId, framework, onAnalyze }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    let live = true;
    setData(null);
    setError("");
    const qs = framework ? `?framework=${framework}` : "";
    fetch(`/api/devices/${deviceId}/analysis/${qs}`, {
      headers: authHeaders(token),
    })
      .then((r) =>
        r.ok
          ? r.json()
          : Promise.reject(new Error(`server returned ${r.status}`)),
      )
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [deviceId, framework, token]);

  if (error)
    return (
      <p role="alert" className="text-red-400 text-xs">
        Could not load details: {error}
      </p>
    );
  if (!data) return <p className="text-xs text-gray-500">Loading details...</p>;

  const latest = data.latest;
  if (!latest)
    return (
      <p className="text-xs text-gray-500">
        No snapshots yet. Push an audit result for this device first.
      </p>
    );

  // Group the line changes under their parent block (for example "interface Gi0/0").
  const groups = [];
  for (const c of latest.changes) {
    const name = c.parent_block || "(global)";
    let g = groups.find((x) => x.name === name);
    if (!g) groups.push((g = { name, lines: [] }));
    g.lines.push(c);
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-gray-400">
          Latest snapshot #{latest.snapshot_id}
          {latest.previous_snapshot_id ? (
            <>
              {" "}
              compared with #{latest.previous_snapshot_id}. File hash{" "}
              <span
                className={latest.hash_changed ? "text-white" : "text-gray-300"}
              >
                {latest.hash_changed ? "changed" : "is the same"}
              </span>
              .
            </>
          ) : (
            ". This is the first snapshot, so there is nothing to compare."
          )}
        </p>
        <button
          type="button"
          onClick={() => onAnalyze(deviceId)}
          className={outlineBtn}
        >
          VIEW GRAPHS
        </button>
      </div>

      <div>
        <h4 className="text-[10px] text-gray-500 tracking-wider mb-2">
          COMPLIANCE RULES THAT CHANGED
        </h4>
        {latest.rule_changes.length === 0 ? (
          <p className="text-xs text-gray-500">No rule changed status.</p>
        ) : (
          <ul className="divide-y divide-gray-800 border border-gray-800">
            {latest.rule_changes.map((r) => (
              <li
                key={r.rule_id}
                className="px-3 py-2 text-xs flex flex-wrap gap-x-4"
              >
                <span className="text-gray-200">
                  [{r.rule_id}] {r.name}
                </span>
                <span>
                  <span className={FLIP_STYLE[r.from] ?? "text-gray-400"}>
                    {r.from}
                  </span>
                  <span className="text-gray-600"> to </span>
                  <span className={FLIP_STYLE[r.to] ?? "text-gray-400"}>
                    {r.to}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="text-[10px] text-gray-500 tracking-wider mb-2">
          LINE CHANGES ({latest.changes.length}) · secrets are masked for most
          roles
        </h4>
        {groups.length === 0 ? (
          <p className="text-xs text-gray-500">
            No configuration lines changed.
          </p>
        ) : (
          <div className="border border-gray-800 divide-y divide-gray-800 text-[11px]">
            {groups.map((g) => (
              <div key={g.name} className="px-3 py-2">
                <p className="text-gray-500 mb-1 break-all">{g.name}</p>
                {g.lines.map((c, i) => (
                  <pre
                    key={i}
                    className={`whitespace-pre-wrap break-all ${
                      c.change_type === "added"
                        ? "text-green-400"
                        : "text-red-400"
                    }`}
                  >
                    {c.change_type === "added" ? "+" : "-"} {c.line_text}
                  </pre>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      <details>
        <summary className="text-[10px] text-gray-500 tracking-wider cursor-pointer">
          NORMALIZED CONFIG (LATEST)
        </summary>
        <pre className="border border-gray-800 p-3 mt-2 text-[11px] text-gray-300 whitespace-pre-wrap overflow-x-auto">
          {JSON.stringify(latest.normalized_config, null, 2)}
        </pre>
      </details>
    </div>
  );
}
