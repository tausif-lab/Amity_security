import { Link } from "react-router-dom";
import { Shield } from "lucide-react";

export const inputClass =
  "w-full bg-black border border-gray-600 text-white text-sm px-3 py-2.5 placeholder-gray-700 focus:outline-none focus:border-white transition-colors";

export default function AuthShell({ title, subtitle, children, footer }) {
  return (
    <div className="min-h-screen w-full bg-black text-white font-mono flex flex-col">
      <header className="flex items-center justify-between px-8 py-5">
        <Link to="/" className="flex items-center gap-2 text-lg font-bold tracking-widest">
          <Shield className="w-5 h-5" />
          Suraksha<span className="font-light">Asthri</span>
        </Link>
        <Link to="/" className="text-xs text-gray-500 hover:text-white transition-colors">
          // Back to home
        </Link>
      </header>

      <main className="flex-1 flex items-center justify-center px-6 pb-16">
        <div className="w-full max-w-md border border-gray-700 p-8">
          <h1 className="text-2xl font-bold tracking-wide mb-2">{title}</h1>
          <p className="text-gray-400 text-xs leading-relaxed mb-8">{subtitle}</p>
          {children}
          <p className="text-gray-500 text-xs mt-8">{footer}</p>
        </div>
      </main>
    </div>
  );
}