import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, Upload, RefreshCw, Server } from "lucide-react";
import { useAuth } from "../components/AuthContext";
import useDevices from "../components/dashboard/useDevices";
import AuditorSection from "../components/dashboard/AuditorSection";
import VendorTranslatorSection from "../components/dashboard/VendorTranslatorSection";
import DeviceInventorySection from "../components/dashboard/DeviceInventorySection";

// Order matters: inventory comes after the translator.
const TABS = [
  { id: "audit", label: "COMPLIANCE AUDIT", Icon: Upload },
  { id: "translate", label: "VENDOR TRANSLATION", Icon: RefreshCw },
  { id: "inventory", label: "DEVICE INVENTORY", Icon: Server },
];

export default function Dashboard() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState("audit");
  const { devices, loading, error, refresh } = useDevices();

  const handleLogout = async () => {
    await signOut();
    navigate("/", { replace: true });
  };

  const tabClass = (t) =>
    `flex items-center gap-2 text-xs tracking-wider px-4 py-2 transition-colors ${
      tab === t ? "bg-white text-black" : "text-gray-400 hover:text-white border border-gray-800 hover:border-gray-600"
    }`;

  // Sections stay mounted and are only hidden, so audit results survive a tab switch.
  const show = (t) => (tab === t ? "" : "hidden");

  return (
    <div className="h-screen bg-black text-white font-mono flex flex-col overflow-hidden">
      <header className="w-full flex justify-between items-center px-8 py-5 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2 text-xl font-bold tracking-widest">
          <Shield className="w-5 h-5" />
          Suraksha<span className="font-light">Asthra</span>
          <span className="ml-4 text-xs bg-white text-black px-2 py-0.5 tracking-widest hidden sm:inline">
            AUDITOR WORKSPACE
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-gray-500">
          <span className="hidden md:inline">// {user?.email}</span>
          <button
            onClick={handleLogout}
            className="border border-gray-600 text-gray-200 px-4 py-1.5 hover:border-white hover:text-white transition-colors"
          >
            LOGOUT
          </button>
        </div>
      </header>

      <nav className="border-b border-gray-800 shrink-0">
        <div className="max-w-4xl mx-auto flex flex-wrap justify-center gap-2 px-4 py-3">
          {TABS.map(({ id, label, Icon }) => (
            <button key={id} onClick={() => setTab(id)} className={tabClass(id)}>
              <Icon className="w-4 h-4 shrink-0" /> {label}
            </button>
          ))}
        </div>
      </nav>

      <main className="flex-1 min-h-0 overflow-y-auto px-6 py-10">
        <div className="max-w-4xl mx-auto w-full">
          <div className={show("audit")}>
            <AuditorSection devices={devices} devicesLoading={loading} />
          </div>
          <div className={show("translate")}>
            <VendorTranslatorSection />
          </div>
          <div className={show("inventory")}>
            <DeviceInventorySection devices={devices} loading={loading} error={error} onRefresh={refresh} />
          </div>
        </div>
      </main>
    </div>
  );
}