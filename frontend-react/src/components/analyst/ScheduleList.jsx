import { useState } from "react";
import { useAuth } from "../AuthContext";
import { jsonHeaders } from "../dashboard/dashboardApi";
import { btn, btnDanger, describeInterval, formatWhen, relativeTime } from "./scheduleUi";

function ScheduleCard({ s, now, frameworkLabel, onChanged, onEdit }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState(null);

  const request = async (kind, url, init, onOk) => {
    setBusy(kind);
    setMsg(null);
    try {
      const res = await fetch(url, { headers: jsonHeaders(token), ...init });
      const data = res.status === 204 ? {} : await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
      onOk(data);
    } catch (err) {
      setMsg({ ok: false, text: err.message });
    }
    setBusy("");
  };

  const toggle = () => request("toggle", `/api/schedules/${s.id}/`,
    { method: "PATCH", body: JSON.stringify({ enabled: !s.enabled }) }, () => onChanged());

  const runNow = () => request("run", `/api/schedules/${s.id}/run-now/`,
    { method: "POST", body: JSON.stringify({}) }, (data) => {
      const count = (st) => data.runs.filter((r) => r.status === st).length;
      const skipped = count("skipped");
      const failed = count("error");
      setMsg({
        ok: failed === 0,
        text: `Audited ${data.audited} device(s): ${count("ok")} ok` +
          (skipped ? `, ${skipped} skipped (no pushed configuration yet)` : "") +
          (failed ? `, ${failed} failed` : "") + ".",
      });
      onChanged();
    });

  const remove = () => {
    if (!window.confirm("Delete this schedule? Audits already recorded are kept.")) return;
    request("delete", `/api/schedules/${s.id}/`, { method: "DELETE" }, () => onChanged());
  };

  const next = new Date(s.next_run_at).getTime();
  const shownDevices = s.devices.slice(0, 8);

  return (
    <div className={`border p-6 mb-5 ${s.enabled ? "border-gray-700" : "border-gray-800 opacity-80"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="text-xl text-white">{describeInterval(s)}</h3>
          <p className="text-base text-gray-300 mt-1">{frameworkLabel}</p>
        </div>
        <span className={`text-xs tracking-widest border px-3 py-1.5 ${
          s.enabled ? "border-green-500/70 text-green-400" : "border-gray-500 text-gray-300"}`}>
          {s.enabled ? "ACTIVE" : "PAUSED"}
        </span>
      </div>

      <dl className="grid sm:grid-cols-3 gap-5 mb-5 text-base">
        <div>
          <dt className="text-xs tracking-wider text-gray-400 mb-1">NEXT RUN</dt>
          <dd className="text-gray-100">
            {!s.enabled ? "paused" : next <= now ? "due now (waiting for the scheduler)"
              : `${formatWhen(s.next_run_at)} (${relativeTime(s.next_run_at, now)})`}
          </dd>
        </div>
        <div>
          <dt className="text-xs tracking-wider text-gray-400 mb-1">LAST RUN</dt>
          <dd className="text-gray-100">
            {s.last_run_at ? `${formatWhen(s.last_run_at)} (${relativeTime(s.last_run_at, now)})` : "not run yet"}
          </dd>
        </div>
        <div>
          <dt className="text-xs tracking-wider text-gray-400 mb-1">CREATED BY</dt>
          <dd className="text-gray-100 break-all">{s.created_by}</dd>
        </div>
      </dl>

      <p className="text-xs tracking-wider text-gray-400 mb-2">DEVICES ({s.devices.length})</p>
      <div className="flex flex-wrap gap-2 mb-6">
        {shownDevices.map((d) => (
          <span key={d.device_id} className="text-sm text-gray-100 border border-gray-600 px-3 py-1">
            {d.device_id} · {d.hostname}
          </span>
        ))}
        {s.devices.length > shownDevices.length && (
          <span className="text-sm text-gray-300 px-3 py-1">+{s.devices.length - shownDevices.length} more</span>
        )}
      </div>

      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={runNow} disabled={Boolean(busy)} className={btn}>
          {busy === "run" ? "RUNNING..." : "RUN NOW"}
        </button>
        <button type="button" onClick={toggle} disabled={Boolean(busy)} className={btn}>
          {s.enabled ? "PAUSE" : "RESUME"}
        </button>
        <button type="button" onClick={() => onEdit(s)} disabled={Boolean(busy)} className={btn}>EDIT</button>
        <button type="button" onClick={remove} disabled={Boolean(busy)} className={btnDanger}>DELETE</button>
      </div>

      {msg && (
        <p role="status" className={`text-sm mt-4 border px-4 py-3 ${
          msg.ok ? "border-green-500/60 text-green-300" : "border-red-500/60 text-red-400"}`}>
          {msg.text}
        </p>
      )}
    </div>
  );
}

export default function ScheduleList({ schedules, frameworks, now, onChanged, onEdit }) {
  return schedules.map((s) => (
    <ScheduleCard key={s.id} s={s} now={now} onChanged={onChanged} onEdit={onEdit}
      frameworkLabel={frameworks.find((f) => f.id === s.framework)?.label ?? s.framework} />
  ));
}