import { outlineBtn, typeLabel } from "../dashboard/dashboardApi";

const fmt = (v) => {
  if (v === null || v === undefined) return "-";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "(empty)";
  return String(v);
};

// Shows the answer to one question: how it was understood, the counts, and the matching devices.
export default function QueryResults({ result, onAnalyze }) {
  const { interpretation, count, scanned, not_determined, not_audited, last_updated, devices } = result;

  const cards = [["MATCHING", count], ["CHECKED", scanned], ["NOT DETERMINED", not_determined], ["NOT AUDITED", not_audited]];

  return (
    <div className="mt-8">
      <p className="text-xs text-gray-400 mb-4">
        Understood as: <span className="text-white">{interpretation}</span>
      </p>

      <dl className="grid grid-cols-2 sm:grid-cols-4 text-center border border-gray-800 mb-3">
        {cards.map(([k, v]) => (
          <div key={k} className="py-4 border-r border-gray-800 last:border-r-0">
            <dd className="text-2xl font-bold">{v}</dd>
            <dt className="text-[10px] text-gray-500 mt-1">{k}</dt>
          </div>
        ))}
      </dl>

      <p className="text-[10px] text-gray-500 mb-1">
        Answered from each device's latest pushed snapshot
        {last_updated ? `, newest from ${new Date(last_updated).toLocaleString()}` : ""}.
      </p>
      {not_determined > 0 && (
        <p className="text-[10px] text-gray-500 mb-1">
          {not_determined} device(s) are not counted because their config does not say either way.
        </p>
      )}
      {not_audited > 0 && (
        <p className="text-[10px] text-gray-500 mb-1">
          {not_audited} device(s) have no snapshot yet, so they could not be checked.
        </p>
      )}

      {count === 0 ? (
        <p className="text-xs text-gray-400 border border-gray-800 px-4 py-6 text-center mt-4">
          No device matches this question.
        </p>
      ) : (
        <div className="border border-gray-800 overflow-x-auto mt-4">
          <table className="w-full text-xs text-left">
            <thead className="text-[10px] text-gray-500 tracking-wider border-b border-gray-800">
              <tr>
                {["DEVICE", "TENANT · SITE", "VENDOR", "MATCHED VALUE", "SNAPSHOT", ""].map((h) => (
                  <th key={h} className="px-4 py-3 font-normal whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {devices.map((d) => (
                <tr key={d.device_id}>
                  <td className="px-4 py-3">
                    <p className="whitespace-nowrap">{d.device_id}</p>
                    <p className="text-[10px] text-gray-500">{d.hostname}</p>
                    {d.serial_number && <p className="text-[10px] text-gray-600">SN {d.serial_number}</p>}
                  </td>
                  <td className="px-4 py-3">{d.tenant}{d.site ? ` · ${d.site}` : ""}</td>
                  <td className="px-4 py-3">{d.vendor} {typeLabel(d.device_type)}</td>
                  <td className="px-4 py-3">
                    {d.facts.map((f) => (
                      <p key={f.field} className="break-words">
                        <span className="text-gray-500">{f.label}:</span> {fmt(f.value)}
                      </p>
                    ))}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <p>#{d.snapshot_id} · {new Date(d.uploaded_at).toLocaleString()}</p>
                    <p className="text-[10px] text-gray-500">by {d.uploaded_by}</p>
                  </td>
                  <td className="px-4 py-3">
                    {onAnalyze && (
                      <button type="button" onClick={() => onAnalyze(d.device_id)} className={outlineBtn}>ANALYZE</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}