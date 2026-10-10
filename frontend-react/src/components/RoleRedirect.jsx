import { Navigate } from "react-router-dom";
import { useAuth } from "../components/AuthContext";

// Sends a logged-in user to the area that matches their registered role.
export default function RoleRedirect() {
  const { session, role, loading } = useAuth();

  if (loading || (session && !role)) {
    return (
      <div className="min-h-screen bg-black text-gray-500 font-mono text-xs flex items-center justify-center">
        Opening your workspace...
      </div>
    );
  }
  if (!session) return <Navigate to="/login" replace />;
  return <Navigate to={role === "auditor" ? "/auditor" : "/analyst"} replace />;
}