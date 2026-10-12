import { Fragment, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useAuth } from "../AuthContext";
import { authHeaders, outlineBtn, tenantOf, typeLabel } from "./dashboardApi";
import SectionHeader from "../dashboard/SectionHeader";

// GET /api/devices/<id>/snapshots/ : the pushed history of one device.
function SnapshotTimeline({ deviceId, token }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    fetch(`/api/devices/${deviceId}/snapshots/`, { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`server returned ${r.status}`))))
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [deviceId, token]);

  if (error) return <p className="text-red-400 text-xs">Could not load history: {error}</p>;
  if (!data) return <p className="text-xs text-gray-500">Loading history...</p>;
  if (data.snapshots.length === 0) {
    return <p className="text-xs text-gray-500">No snapshots yet. Push an audit result to create one.</p>;
  }

  return (
    <ul className="divide-y divide-gray-800 border border-gray-800">
      {data.snapshots.map((s) => (
        <li key={s.id} className="px-3 py-2 text-xs flex flex-wrap items-center gap-x-6 gap-y-1">
          <span className="text-gray-200">{new Date(s.uploaded_at).toLocaleString()}</span>
          <span className="text-gray-500">by {s.uploaded_by}</span>
          <span className="text-gray-600">{s.config_hash.slice(0, 10)}...</span>
          {s.is_latest && <span className="text-[10px] bg-white text-black px-1.5">LATEST</span>}
          {s.results.map((r, i) => (
            <span key={i} className="text-gray-300">
              {r.framework}: <span className="text-white">{r.pass_count} passed</span>,{" "}
              <span className="text-red-400">{r.fail_count} failed</span> ({r.score}%)
            </span>
          ))}
        </li>
      ))}
    </ul>
  );
}

export default function DeviceInventorySection({ devices, loading, error, onRefresh }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [open, setOpen] = useState(null);

  return (
    <section>
      <SectionHeader title="DEVICE INVENTORY">
        Every registered device and its Device ID. Open a device to see the snapshots pushed for it.
      </SectionHeader>

      <div className="flex justify-end mb-3">
        <button type="button" onClick={onRefresh} className={`${outlineBtn} flex items-center gap-2`}>
          <RefreshCw className="w-3 h-3" /> REFRESH
        </button>
      </div>

      {loading && <p className="text-xs text-gray-500">Loading devices...</p>}
      {error && (
        <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2">
          Could not load devices: {error}
        </p>
      )}
      {!loading && !error && devices.length === 0 && (
        <p className="text-xs text-gray-500 text-center">No devices registered yet.</p>
      )}

      {devices.length > 0 && (
        <div className="border border-gray-800 overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead className="text-[10px] text-gray-500 tracking-wider border-b border-gray-800">
              <tr>
                {["ID", "HOSTNAME", "VENDOR", "TYPE", "TENANT", "SITE", "SERIAL", ""].map((h) => (
                  <th key={h} className="px-4 py-3 font-normal whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {devices.map((d) => (
                <Fragment key={d.device_id}>
                  <tr>
                    <td className="px-4 py-3 whitespace-nowrap">{d.device_id}</td>
                    <td className="px-4 py-3">{d.hostname}</td>
                    <td className="px-4 py-3">{d.vendor}</td>
                    <td className="px-4 py-3">{typeLabel(d.device_type)}</td>
                    <td className="px-4 py-3">{tenantOf(d)}</td>
                    <td className="px-4 py-3">{d.site || "-"}</td>
                    <td className="px-4 py-3">{d.serial_number || "-"}</td>
                    <td className="px-4 py-3">
                      <button type="button" className="text-gray-400 hover:text-white underline"
                        onClick={() => setOpen(open === d.device_id ? null : d.device_id)}>
                        {open === d.device_id ? "HIDE" : "HISTORY"}
                      </button>
                    </td>
                  </tr>
                  {open === d.device_id && (
                    <tr>
                      <td colSpan={8} className="px-4 py-3 bg-gray-950">
                        <SnapshotTimeline deviceId={d.device_id} token={token} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}