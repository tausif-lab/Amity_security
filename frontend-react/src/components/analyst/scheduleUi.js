import { useEffect, useRef } from "react";

// ---- shared styles (readable sizes, matching the auditor dashboard) ----
export const labelClass = "block text-sm tracking-wider text-gray-300 mb-2";
export const inputClass =
  "w-full bg-black border border-gray-600 text-base px-4 py-3 text-white placeholder-gray-600 focus:outline-none focus:border-white transition-colors";
export const btn =
  "border border-gray-500 text-gray-100 px-5 py-2.5 text-sm tracking-widest hover:border-white hover:text-white transition-colors disabled:opacity-50";
export const btnPrimary =
  "border border-white bg-white text-black px-6 py-3 text-sm tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50";
export const btnDanger =
  "border border-red-500/70 text-red-400 px-5 py-2.5 text-sm tracking-widest hover:bg-red-500 hover:text-white transition-colors disabled:opacity-50";

export const STATUS_BADGE = {
  ok: "border-green-500/70 text-green-400",
  skipped: "border-yellow-500/70 text-yellow-400",
  error: "border-red-500/70 text-red-400",
};
export const RULE_BADGE = {
  Pass: { label: "PASS", cls: "border-green-500/70 text-green-400" },
  Fail: { label: "FAIL", cls: "border-red-500/70 text-red-400" },
  Unknown: { label: "UNKNOWN", cls: "border-yellow-500/70 text-yellow-400" },
  Manual: { label: "MANUAL", cls: "border-gray-500 text-gray-300" },
};

export const INTERVALS = [
  { label: "1 min", minutes: 1 }, { label: "2 min", minutes: 2 }, { label: "5 min", minutes: 5 },
  { label: "15 min", minutes: 15 }, { label: "30 min", minutes: 30 }, { label: "1 hour", minutes: 60 },
  { label: "2 hours", minutes: 120 }, { label: "6 hours", minutes: 360 },
  { label: "12 hours", minutes: 720 }, { label: "1 day", minutes: 1440 },
];

// "Every 2 hours", "Every day at 09:30 (Asia/Kolkata)"
export function describeInterval({ interval_minutes: m, daily_at, timezone }) {
  let every;
  if (m % 1440 === 0) every = m === 1440 ? "day" : `${m / 1440} days`;
  else if (m % 60 === 0) every = m === 60 ? "hour" : `${m / 60} hours`;
  else every = m === 1 ? "minute" : `${m} minutes`;
  return `Every ${every}${daily_at ? ` at ${daily_at} (${timezone})` : ""}`;
}

export const formatWhen = (iso) => (iso ? new Date(iso).toLocaleString() : "never");

export function relativeTime(iso, now = Date.now()) {
  if (!iso) return "";
  const secs = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(secs);
  const text = abs < 60 ? `${abs} sec` : abs < 3600 ? `${Math.round(abs / 60)} min`
    : abs < 86400 ? `${Math.round(abs / 3600)} h` : `${Math.round(abs / 86400)} d`;
  return secs >= 0 ? `in ${text}` : `${text} ago`;
}

// Readable text for any value a rule can return.
export function showValue(v) {
  if (v === null || v === undefined) return "not found";
  if (v === "") return "(empty)";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) {
    return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : "none";
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function browserTimezone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
}

export function timezoneList() {
  const all = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  return ["UTC", ...all.filter((z) => z !== "UTC")];
}

// Calls load() now and then every `ms`. It restarts whenever `key` changes;
// a null key pauses it.
export function usePolling(load, ms, key) {
  const ref = useRef(load);
  ref.current = load;
  useEffect(() => {
    if (key === null || key === undefined || key === false) return undefined;
    ref.current();
    const t = setInterval(() => ref.current(), ms);
    return () => clearInterval(t);
  }, [ms, key]);
}