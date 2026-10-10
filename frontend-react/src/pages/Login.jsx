import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import AuthShell, { inputClass } from "../components/AuthShell";
import { useAuth } from "../components/AuthContext";

export default function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    const { error } = await signIn(email.trim(), password);
    setBusy(false);
    if (error) return setError(error.message);
    navigate("/dashboard", { replace: true });
  };

  return (
    <AuthShell
      title="Log in"
      subtitle="Use your company email to open your audit workspace."
      footer={
        <>
          No account yet?{" "}
          <Link to="/register" className="text-white underline underline-offset-4">
            Create one
          </Link>
        </>
      }
    >
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
          <label htmlFor="password" className="block text-xs text-gray-400 mb-2">Password</label>
          <input
            id="password" type="password" required autoComplete="current-password"
            className={inputClass}
            value={password} onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {error && (
          <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2">
            {error}
          </p>
        )}

        <button
          type="submit" disabled={busy}
          className="border border-white bg-white text-black py-3 text-[11px] tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50"
        >
          {busy ? "LOGGING IN..." : "LOGIN"}
        </button>
      </form>
    </AuthShell>
  );
}