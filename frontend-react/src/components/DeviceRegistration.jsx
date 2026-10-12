import { useState } from "react";
import { useAuth } from "./AuthContext";

const VENDORS = [
  { value: "cisco", label: "Cisco" },
  { value: "juniper", label: "Juniper" },
];
const DEVICE_TYPES = [
  { value: "router", label: "Router" },
  { value: "switch", label: "Switch" },
  { value: "firewall", label: "Firewall" },
  { value: "load_balancer", label: "Load Balancer" },
  { value: "wireless_controller", label: "Wireless Controller" },
  { value: "other", label: "Other" },
];
const inputClass =
  "w-full bg-black border border-gray-700 text-sm px-4 py-3 placeholder-gray-700 focus:outline-none focus:border-white transition-colors";
const labelClass = "block text-[10px] text-gray-500 tracking-wider mb-2";
const empty = { tenant_name: "", site: "", vendor: "cisco", device_type: "router", hostname: "", serial_number: "" };
// Calls POST /api/devices/. `onRegistered(device)` lets the dashboard update its list.
export default function DeviceRegistration({ onRegistered }) {
  const { user, session } = useAuth();
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState(null);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setCreated(null);
    setBusy(true);
    try {
      const res = await fetch("/api/devices/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(session?.access_token && { Authorization: `Bearer ${session.access_token}` }),
        },
        body: JSON.stringify({ ...form, registered_by: user?.email ?? "" }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Server returned ${res.status}`);

      setCreated(data);
      onRegistered?.(data);
      // keep tenant and site so several devices can be added in a row
      setForm((f) => ({ ...empty, tenant_name: f.tenant_name, site: f.site }));
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  return (
    <form onSubmit={submit} className="border border-gray-800 p-6 grid grid-cols-2 gap-6">
      <div className="col-span-2 sm:col-span-1">
        <label htmlFor="tenant" className={labelClass}>TENANT / COMPANY *</label>
        <input id="tenant" required className={inputClass} placeholder="Acme Corp"
          value={form.tenant_name} onChange={set("tenant_name")} />
      </div>
      <div className="col-span-2 sm:col-span-1">
        <label htmlFor="site" className={labelClass}>SITE</label>
        <input id="site" className={inputClass} placeholder="Mumbai DC-1"
          value={form.site} onChange={set("site")} />
      </div>

      <div className="col-span-2 sm:col-span-1">
        <label htmlFor="vendor" className={labelClass}>VENDOR *</label>
        <select id="vendor" className={`${inputClass} cursor-pointer`}
          value={form.vendor} onChange={set("vendor")}>
          {VENDORS.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
        </select>
      </div>
      <div className="col-span-2 sm:col-span-1">
        <label htmlFor="device_type" className={labelClass}>DEVICE TYPE *</label>
        <select id="device_type" required className={`${inputClass} cursor-pointer`}
          value={form.device_type} onChange={set("device_type")}>
          {DEVICE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
      </div>
      <div className="col-span-2 sm:col-span-1">
        <label htmlFor="hostname" className={labelClass}>HOSTNAME *</label>
        <input id="hostname" required className={inputClass} placeholder="Core-SW-01"
          value={form.hostname} onChange={set("hostname")} />
      </div>

      <div className="col-span-2 ">
        <label htmlFor="serial" className={labelClass}>SERIAL NUMBER</label>
        <input id="serial" className={inputClass} placeholder="FOC1234ABCD"
          value={form.serial_number} onChange={set("serial_number")} />
      </div>
      <div className="col-span-2 sm:col-span-1">
        <label htmlFor="by" className={labelClass}>REGISTERED BY</label>
        <input id="by" readOnly className={`${inputClass} text-gray-500`} value={user?.email ?? ""} />
      </div>

      {error && (
        <p role="alert" className="col-span-2 border border-red-500/60 text-red-400 text-xs px-3 py-2">
          {error}
        </p>
      )}
      {created && (
        <p role="status" className="col-span-2 border border-gray-500 text-gray-200 text-xs px-3 py-2">
          Registered {created.device_id ?? "device"} ({created.hostname}).
        </p>
      )}

      <button
        type="submit" disabled={busy}
        className="col-span-2 border border-white bg-white text-black py-3 text-xs tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50"
      >
        {busy ? "REGISTERING..." : "REGISTER DEVICE"}
      </button>
    </form>
  );
}