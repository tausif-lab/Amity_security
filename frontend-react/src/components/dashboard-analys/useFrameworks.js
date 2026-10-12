import { useEffect, useState } from "react";
import { authHeaders } from "../dashboard/dashboardApi";

const FALLBACK = [{ id: "CIS", label: "CIS Benchmark" }, { id: "NIST", label: "NIST SP 800-53" }];

// GET /api/frameworks/ ; falls back to CIS and NIST if it is unavailable.
export default function useFrameworks(token) {
  const [frameworks, setFrameworks] = useState(FALLBACK);
  useEffect(() => {
    if (!token) return;
    let live = true;
    fetch("/api/frameworks/", { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((list) => { if (live && Array.isArray(list) && list.length) setFrameworks(list); })
      .catch(() => {});
    return () => { live = false; };
  }, [token]);
  return frameworks;
}