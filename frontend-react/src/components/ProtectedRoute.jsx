import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

// <ProtectedRoute roles={["admin", "auditor"]}> ... </ProtectedRoute>
export default function ProtectedRoute({ roles, children }) {
  const { session, role, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen bg-black text-gray-500 font-mono text-xs flex items-center justify-center">
        Loading session...
      </div>
    );
  }
  if (!session) return <Navigate to="/login" state={{ from: location }} replace />;
  if (roles && !roles.includes(role)) {
    return (
      <div className="min-h-screen bg-black text-white font-mono text-sm flex items-center justify-center px-6 text-center">
        Your role ({role ?? "none"}) does not have access to this page.
      </div>
    );
  }
  return children;
}