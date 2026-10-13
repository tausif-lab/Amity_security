import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../AuthContext";
import { authHeaders } from "../dashboard/dashboardApi";
import ScheduleForm from "./ScheduleForm";
import ScheduleList from "./ScheduleList";
import { usePolling } from "./scheduleUi";

const FALLBACK_FRAMEWORKS = [
  { id: "CIS", label: "CIS Benchmark" },
  { id: "NIST", label: "NIST SP 800-53" },
];

export default function AuditScheduleSection({ devices, devicesLoading }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [schedules, setSchedules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [frameworks, setFrameworks] = useState(FALLBACK_FRAMEWORKS);
  const [editing, setEditing] = useState(null);
  const [notice, setNotice] = useState("");
  const [now, setNow] = useState(Date.now());
  const formRef = useRef(null);

  // GET /api/schedules/ now, then every 30 seconds.
  const load = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch("/api/schedules/", { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`server returned ${res.status}`);
      setSchedules(await res.json());
      setError("");
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  }, [token]);
  usePolling(load, 30000, token);

  useEffect(() => {          // keeps "in 5 min" style times fresh
    const t = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {          // GET /api/frameworks/, falls back to CIS + NIST
    if (!token) return;
    let live = true;
    fetch("/api/frameworks/", { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((list) => { if (live && Array.isArray(list) && list.length) setFrameworks(list); })
      .catch(() => {});
    return () => { live = false; };
  }, [token]);

  const saved = (_data, wasEditing) => {
    setEditing(null);
    setNotice(wasEditing ? "Schedule updated."
      : "Schedule created. Its first audit runs the next time the scheduler checks.");
    setTimeout(() => setNotice(""), 8000);
    load();
  };

  const edit = (s) => {
    setEditing(s);
    setTimeout(() => formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };

  // A schedule that has been due for 2+ minutes means nothing is running the audits.
  const overdue = schedules.some((s) => s.enabled && new Date(s.next_run_at).getTime() < now - 120000);

  return (
    <section>
      <h1 className="text-3xl font-bold tracking-wide mb-2">AUDIT SCHEDULES</h1>
      <p className="text-base text-gray-300 leading-relaxed mb-8 max-w-3xl">
        Pick devices, a security framework and how often to check. Each scheduled audit re-checks the
        device's latest pushed configuration and records the score and every criterion that passed or failed.
      </p>

      <h2 ref={formRef} className="text-sm tracking-widest text-gray-200 mb-4">
        {editing ? `EDIT SCHEDULE #${editing.id}` : "NEW SCHEDULE"}
      </h2>
      <ScheduleForm
        key={editing ? `edit-${editing.id}` : "new"}
        devices={devices} frameworks={frameworks} schedule={editing}
        onSaved={saved} onCancel={() => setEditing(null)} />
      {devicesLoading && <p className="text-sm text-gray-400 mt-3">Loading devices...</p>}
      {notice && (
        <p role="status" className="text-base text-green-300 border border-green-500/60 px-4 py-3 mt-5">{notice}</p>
      )}

      <h2 className="text-sm tracking-widest text-gray-200 mt-12 mb-4">SCHEDULES ({schedules.length})</h2>

      {overdue && (
        <p role="alert" className="border border-yellow-500/60 text-yellow-300 text-base px-4 py-3 mb-5 leading-relaxed">
          A schedule has been due for over 2 minutes, so the scheduler does not seem to be running.
          Start it on the server with <code className="text-white">python manage.py run_due_audits --loop</code>.
        </p>
      )}
      {loading && <p className="text-base text-gray-300">Loading schedules...</p>}
      {error && (
        <p role="alert" className="border border-red-500/60 text-red-400 text-base px-4 py-3 mb-5">
          Could not load schedules: {error}
        </p>
      )}
      {!loading && !error && schedules.length === 0 && (
        <p className="text-base text-gray-300">No schedules yet. Create one above.</p>
      )}

      <ScheduleList schedules={schedules} frameworks={frameworks} now={now} onChanged={load} onEdit={edit} />
    </section>
  );
}