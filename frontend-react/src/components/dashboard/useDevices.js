import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../AuthContext";
import { authHeaders } from "./dashboardApi";

// Loads GET /api/devices/ once; the audit dropdown and the inventory share it.
export default function useDevices() {
  const { session } = useAuth();
  const token = session?.access_token;
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/devices/", { headers: authHeaders(token) });
      if (!res.ok) throw new Error(`server returned ${res.status}`);
      const data = await res.json();
      setDevices(Array.isArray(data) ? data : data.results ?? []);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  }, [token]);

  useEffect(() => { refresh(); }, [refresh]);

  return { devices, loading, error, refresh };
}