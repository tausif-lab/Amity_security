import { useMemo, useState } from "react";
import { useAuth } from "../AuthContext";
import { jsonHeaders, tenantOf, typeLabel } from "../dashboard/dashboardApi";
import {
  INTERVALS, browserTimezone, btn, btnPrimary, describeInterval, inputClass, labelClass, timezoneList,
} from "./scheduleUi";

const UNITS = { minutes: 1, hours: 60, days: 1440 };
const MAX_MINUTES = 43200;   // 30 days, same limit as the server

function splitCustom(minutes) {
  if (minutes % 1440 === 0) return { value: minutes / 1440, unit: "days" };
  if (minutes % 60 === 0) return { value: minutes / 60, unit: "hours" };
  return { value: minutes, unit: "minutes" };
}

const chip = (on) =>
  `px-5 py-2.5 text-sm border transition-colors ${
    on ? "bg-white text-black border-white" : "border-gray-600 text-gray-200 hover:border-white"}`;

export default function ScheduleForm({ devices, frameworks, schedule, onSaved, onCancel }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const editing = Boolean(schedule);

  const startMinutes = schedule?.interval_minutes ?? 60;
  const custom0 = splitCustom(startMinutes);
  const [framework, setFramework] = useState(schedule?.framework ?? frameworks[0]?.id ?? "CIS");
  const [preset, setPreset] = useState(INTERVALS.some((i) => i.minutes === startMinutes) ? startMinutes : "custom");
  const [customValue, setCustomValue] = useState(custom0.value);
  const [customUnit, setCustomUnit] = useState(custom0.unit);
  const [time, setTime] = useState(schedule ? schedule.daily_at ?? "" : "09:00");
  const [tz, setTz] = useState(schedule?.timezone ?? browserTimezone());
  const [zones] = useState(() => {
    const z = timezoneList();
    const initial = schedule?.timezone ?? browserTimezone();
    return z.includes(initial) ? z : [initial, ...z];
  });
  const [selected, setSelected] = useState(() => new Set((schedule?.devices ?? []).map((d) => d.device_id)));
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const minutes = preset === "custom" ? Math.round(Number(customValue) * UNITS[customUnit]) : preset;
  const validInterval = Number.isFinite(minutes) && minutes >= 1 && minutes <= MAX_MINUTES;
  const isDaily = validInterval && minutes % 1440 === 0;
  const fixedTime = isDaily && time ? time : null;

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return devices;
    return devices.filter((d) =>
      [d.device_id, d.hostname, d.vendor, d.device_type, tenantOf(d), d.site].join(" ").toLowerCase().includes(q));
  }, [devices, query]);

  const toggle = (id) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const selectShown = () => setSelected((prev) => new Set([...prev, ...shown.map((d) => d.device_id)]));

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (!selected.size) return setError("Select at least one device.");
    if (!validInterval) return setError("Enter an interval between 1 minute and 30 days.");
    const body = {
      framework, interval_minutes: minutes, device_ids: [...selected], daily_at: fixedTime,
      ...(fixedTime ? { timezone: tz } : {}),
    };
    setBusy(true);
    try {
      const res = await fetch(editing ? `/api/schedules/${schedule.id}/` : "/api/schedules/", {
        method: editing ? "PATCH" : "POST", headers: jsonHeaders(token), body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `server returned ${res.status}`);
      if (!editing) setSelected(new Set());
      onSaved(data, editing);
    } catch (err) {
      setError(err.message);
    }
    setBusy(false);
  };

  const fwLabel = frameworks.find((f) => f.id === framework)?.label ?? framework;

  return (
    <form onSubmit={submit} className="border border-gray-700 p-8 space-y-8">
      <div>
        <label htmlFor="fw" className={labelClass}>SECURITY FRAMEWORK</label>
        <select id="fw" value={framework} onChange={(e) => setFramework(e.target.value)}
          className={`${inputClass} cursor-pointer`}>
          {frameworks.map((f) => <option key={f.id} value={f.id}>{f.label ?? f.id}</option>)}
        </select>
      </div>

      <div>
        <span className={labelClass}>HOW OFTEN</span>
        <div className="flex flex-wrap gap-3">
          {INTERVALS.map((i) => (
            <button key={i.minutes} type="button" onClick={() => setPreset(i.minutes)} className={chip(preset === i.minutes)}>
              {i.label}
            </button>
          ))}
          <button type="button" onClick={() => setPreset("custom")} className={chip(preset === "custom")}>Custom</button>
        </div>

        {preset === "custom" && (
          <div className="flex flex-wrap items-center gap-3 mt-4">
            <span className="text-base text-gray-300">Every</span>
            <input type="number" min="1" value={customValue} onChange={(e) => setCustomValue(e.target.value)}
              aria-label="Custom interval" className={`${inputClass} !w-32`} />
            <select value={customUnit} onChange={(e) => setCustomUnit(e.target.value)}
              aria-label="Custom interval unit" className={`${inputClass} !w-40 cursor-pointer`}>
              <option value="minutes">minutes</option>
              <option value="hours">hours</option>
              <option value="days">days</option>
            </select>
            <span className="text-sm text-gray-400">(1 minute to 30 days)</span>
          </div>
        )}
      </div>

      {isDaily && (
        <div className="grid sm:grid-cols-2 gap-6">
          <div>
            <label htmlFor="at" className={labelClass}>RUN AT (TIME OF DAY)</label>
            <input id="at" type="time" value={time} onChange={(e) => setTime(e.target.value)} className={inputClass} />
            <p className="text-sm text-gray-400 mt-2">Leave empty to run every 24 hours from now instead.</p>
          </div>
          <div>
            <label htmlFor="tz" className={labelClass}>TIME ZONE</label>
            <select id="tz" value={tz} onChange={(e) => setTz(e.target.value)}
              disabled={!time} className={`${inputClass} cursor-pointer disabled:opacity-50`}>
              {zones.map((z) => <option key={z} value={z}>{z}</option>)}
            </select>
          </div>
        </div>
      )}

      <div>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <span className="text-sm tracking-wider text-gray-300">
            DEVICES ({selected.size} of {devices.length} selected)
          </span>
          <div className="flex gap-3">
            <button type="button" onClick={selectShown} className={btn}>SELECT ALL SHOWN</button>
            <button type="button" onClick={() => setSelected(new Set())} className={btn}>CLEAR</button>
          </div>
        </div>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by ID, hostname, vendor, tenant..."
          aria-label="Search devices" className={`${inputClass} mb-3`} />
        <div className="border border-gray-700 max-h-80 overflow-y-auto divide-y divide-gray-800">
          {devices.length === 0 && (
            <p className="px-4 py-4 text-base text-gray-300">No devices registered yet. Register a device first.</p>
          )}
          {devices.length > 0 && shown.length === 0 && (
            <p className="px-4 py-4 text-base text-gray-300">No device matches your search.</p>
          )}
          {shown.map((d) => (
            <label key={d.device_id} className="flex items-start gap-4 px-4 py-3 cursor-pointer hover:bg-gray-900">
              <input type="checkbox" checked={selected.has(d.device_id)} onChange={() => toggle(d.device_id)}
                className="mt-1.5 h-4 w-4 accent-white" />
              <span className="min-w-0">
                <span className="text-base text-white">{d.device_id}</span>
                <span className="text-base text-gray-200"> · {d.hostname}</span>
                <span className="block text-sm text-gray-400">
                  {d.vendor} {typeLabel(d.device_type)} · {tenantOf(d)}{d.site ? ` · ${d.site}` : ""}
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className="border border-gray-700 bg-gray-950 px-5 py-4">
        <p className="text-base text-white">
          {selected.size} device(s) · {fwLabel} ·{" "}
          {validInterval ? describeInterval({ interval_minutes: minutes, daily_at: fixedTime, timezone: tz }) : "choose an interval"}
        </p>
        <p className="text-sm text-gray-400 mt-1 leading-relaxed">
          Each audit re-checks the device's latest pushed configuration and saves the score and every
          passed and failed criterion with a timestamp.
        </p>
      </div>

      {error && <p role="alert" className="border border-red-500/60 text-red-400 text-sm px-4 py-3">{error}</p>}

      <div className="flex flex-wrap gap-4">
        <button type="submit" disabled={busy} className={btnPrimary}>
          {busy ? "SAVING..." : editing ? "SAVE CHANGES" : "CREATE SCHEDULE"}
        </button>
        {editing && <button type="button" onClick={onCancel} className={btn}>CANCEL</button>}
      </div>
    </form>
  );
}