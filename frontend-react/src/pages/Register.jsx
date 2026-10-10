import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AuthShell, { inputClass } from "../components/AuthShell";
import { useAuth } from "../components/AuthContext";

const ROLES = [
  { id: "auditor", label: "Compliance Auditor", desc: "Run audits, review findings and sign off on reports." },
  { id: "analyst", label: "Security Analyst", desc: "Investigate risks and review normalization results." },
];

export default function Register() {
  const { signUp } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("auditor");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setError("");
    const clean = email.trim().toLowerCase();

    if (password.length < 8) {
      return setError("Password must be at least 8 characters.");
    }

    setBusy(true);
    const { data, error } = await signUp(clean, password, role);
    setBusy(false);
    if (error) return setError(error.message);

    // No session yet means Supabase is waiting for email confirmation.
    if (!data.session) {
      return setNotice(`We sent a confirmation link to ${clean}. Open it, then log in.`);
    }
    navigate("/dashboard", { replace: true });
  };

  return (
    <AuthShell
      title="Create account"
      subtitle="Register with your company email and choose the role you will work in."
      footer={
        <>
          Already registered?{" "}
          <Link to="/login" className="text-white underline underline-offset-4">
            Log in
          </Link>
        </>
      }
    >
      {notice ? (
        <p role="status" className="border border-gray-500 text-gray-200 text-xs leading-relaxed px-3 py-3">
          {notice}
        </p>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-5">
          <div>
            <label htmlFor="email" className="block text-xs text-gray-400 mb-2">Company email</label>
            <input
              id="email" type="email" required autoComplete="email"
              placeholder="you@company.com" className={inputClass}
              value={email} onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-xs text-gray-400 mb-2">
              Password (8+ characters)
            </label>
            <input
              id="password" type="password" required minLength={8} autoComplete="new-password"
              className={inputClass}
              value={password} onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <fieldset>
            <legend className="text-xs text-gray-400 mb-2">Role</legend>
            <div className="flex flex-col gap-2">
              {ROLES.map((r) => (
                <label
                  key={r.id}
                  className={`flex gap-3 border px-3 py-2.5 cursor-pointer transition-colors ${
                    role === r.id ? "border-white" : "border-gray-700 hover:border-gray-500"
                  }`}
                >
                  <input
                    type="radio" name="role" value={r.id}
                    checked={role === r.id} onChange={() => setRole(r.id)}
                    className="mt-1 accent-white"
                  />
                  <span>
                    <span className="block text-sm">{r.label}</span>
                    <span className="block text-[11px] text-gray-500 leading-relaxed">{r.desc}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {error && (
            <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit" disabled={busy}
            className="border border-white bg-white text-black py-3 text-[11px] tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50"
          >
            {busy ? "CREATING ACCOUNT..." : "REGISTER"}
          </button>
        </form>
      )}
    </AuthShell>
  );
}