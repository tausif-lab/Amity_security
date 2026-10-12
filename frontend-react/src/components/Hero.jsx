import { Shield, Zap } from "lucide-react";
import NetworkGlobe from "./NetworkGlobe";
import { Link } from "react-router-dom";
const MARQUEE =
  "LIVE VENDOR MONITORING /////////  CONTINUOUS COMPLIANCE AUDITS /////////  THREAT & RISK INSIGHTS /////////  ";

export default function Hero() {
  return (
    <div className="relative w-screen h-screen bg-black text-white font-mono overflow-hidden m-0 p-0">
      {/* HEADER */}
      <header className="absolute top-0 left-0 w-full flex justify-between items-center px-8 py-5 z-20">
        <nav className="hidden md:flex gap-6 text-gray-500 text-xs tracking-wide">
          {["Docs", "Blog", "Discord", "Twitter"].map((l) => (
            <a key={l} href="#" className="hover:text-white transition-colors">
              // {l}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2 text-lg md:text-xl font-bold tracking-widest absolute left-1/2 -translate-x-1/2">
          <Shield className="w-5 h-5" />
          Suraksha<span className="font-light">Asthra</span>
        </div>

        <div className="flex gap-3 ml-auto">
          <Link to="/login" className="border border-gray-600 text-gray-200 px-4 py-1.5 text-xs tracking-wider hover:border-white hover:text-white transition-colors">
           LOGIN
          </Link>
          <Link to="/register" className="border border-white bg-white text-black px-4 py-1.5 text-xs tracking-wider hover:bg-transparent hover:text-white transition-colors">
           REGISTER
          </Link>
        </div>
      </header>

      {/* LEFT SIDEBAR */}
      <aside className="absolute left-6 top-1/2 -translate-y-1/2 hidden lg:flex flex-col items-start gap-4 z-10">
        {["01", "02", "03", "04", "05", "06"].map((n, i) => (
          <div key={n} className="flex items-center gap-3 text-sm">
            <span className={`h-px ${i === 0 ? "w-10 bg-gray-400" : "w-0"}`} />
            <span className={i === 0 ? "text-white" : "text-gray-700"}>{n}</span>
          </div>
        ))}
      </aside>

      {/* MAIN */}
      <main className="relative h-full flex flex-col lg:flex-row items-center w-full px-8 lg:pl-40 lg:pr-12 pt-20 pb-16">
        <div className="w-full lg:w-1/2 z-10">
          <span className="text-gray-600 text-lg block mb-3">01</span>
          <h1 className="text-4xl lg:text-5xl font-bold leading-tight tracking-wide mb-6">
            MULTI-VENDOR
            <br />
            COMPLIANCE AUDITOR
          </h1>
          <p className="text-gray-400 max-w-md text-xs leading-relaxed mb-8">
            Suraksha Asthra is a multi-vendor compliance auditing and monitoring
            platform that continuously verifies vendor controls, detects risk in
            real time and strengthens your organization's security posture.
          </p>
          <div className="flex flex-wrap gap-4">
            <button className="border border-white w-40 py-3 text-[10px] tracking-widest hover:bg-white hover:text-black transition-colors">
              GET STARTED
            </button>
            <button className="border border-gray-600 text-gray-300 w-40 py-3 text-[10px] tracking-widest hover:border-white hover:text-white transition-colors">
              STAY UPDATED
            </button>
          </div>
        </div>

        <div className="w-full lg:w-1/2 flex-1 lg:h-full min-h-0 relative">
          <NetworkGlobe />
        </div>
      </main>

      {/* CENTER LINE + BOLT */}
      <div className="absolute left-1/2 -translate-x-1/2 bottom-0 w-px h-40 bg-gray-700 z-0" />
      <div className="absolute left-1/2 -translate-x-1/2 bottom-24 w-10 h-10 rounded-full border border-gray-400 bg-black flex items-center justify-center z-10">
        <Zap className="w-4 h-4" />
      </div>

      {/* MARQUEE */}
      <div className="absolute bottom-6 left-0 w-full border-y border-gray-800 py-2 overflow-hidden whitespace-nowrap bg-black/80 z-10">
        <div className="animate-marquee inline-block text-[11px] text-gray-300 tracking-widest">
          <span>{MARQUEE.repeat(4)}</span>
          <span>{MARQUEE.repeat(4)}</span>
        </div>
      </div>
    </div>
  );
}