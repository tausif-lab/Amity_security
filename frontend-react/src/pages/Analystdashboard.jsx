import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, PlusSquare, Server, Activity, LineChart , Search} from "lucide-react";
import { useAuth } from "../components/AuthContext";
import DeviceRegistration from "../components/DeviceRegistration";
import useDevices from "../components/dashboard/useDevices";
import DeviceOverviewSection from "../components/dashboard-analys/DeviceOverviewSection.jsx";
import DeviceAnalysisSection from "../components/dashboard-analys/DeviceAnalysisSection";
import DeviceInventorySection from "../components/dashboard/DeviceInventorySection";
import DeviceQuerySection from "../components/dashboard-analys/DeviceQuerySection";
const TABS = [
  { id: "overview", label: "DEVICE STATUS", Icon: Activity },
  { id: "ask", label: "ASK DEVICES", Icon: Search },
  { id: "analysis", label: "DEVICE ANALYSIS", Icon: LineChart },
  { id: "inventory", label: "DEVICE INVENTORY", Icon: Server },
  { id: "register", label: "REGISTER DEVICE", Icon: PlusSquare },
];

export default function AnalystDashboard() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState("overview");
  const [analysisDevice, setAnalysisDevice] = useState("");
  const { devices, loading, error, refresh } = useDevices();

  const handleLogout = async () => {
    await signOut();
    navigate("/", { replace: true });
  };

  // "VIEW GRAPHS" (status table) and "ANALYZE" (search results) jump to the analysis tab for that device.
  const openAnalysis = (deviceId) => {
    setAnalysisDevice(deviceId);
    setTab("analysis");
  };

  const tabClass = (t) =>
    `flex items-center gap-3 text-xs tracking-wider p-3 text-left transition-colors ${
      tab === t
        ? "bg-white text-black"
        : "text-gray-400 hover:text-white border border-transparent hover:border-gray-700"
    }`;

  return (
    <div className="h-screen bg-black text-white font-mono flex flex-col overflow-hidden">
      <header className="w-full flex justify-between items-center px-8 py-5 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2 text-xl font-bold tracking-widest">
          <Shield className="w-5 h-5" />
          Suraksha<span className="font-light">Asthra</span>
          <span className="ml-4 text-xs bg-white text-black px-2 py-0.5 tracking-widest hidden sm:inline">
            ANALYST WORKSPACE
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

      <div className="flex flex-1 min-h-0">
        <aside className="w-56 shrink-0 border-r border-gray-800 p-6 flex flex-col gap-3">
          <div className="text-gray-500 text-[10px] tracking-widest mb-2 border-b border-gray-800 pb-2">
            MODULES
          </div>
          {TABS.map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={tabClass(id)}
            >
              <Icon className="w-4 h-4 shrink-0" /> {label}
            </button>
          ))}
        </aside>

        <main className="flex-1 min-w-0 overflow-y-auto p-8 lg:p-12">
          {/* Only the open tab is mounted, so each one loads fresh data when opened. */}
          <div
            className={`mx-auto w-full ${tab === "register" ? "max-w-2xl" : "max-w-5xl"}`}
          >
            {tab === "overview" && (
              <DeviceOverviewSection onAnalyze={openAnalysis} />
            )}

            {tab === "ask" && <DeviceQuerySection onAnalyze={openAnalysis} />}

            {tab === "analysis" && (
              <DeviceAnalysisSection
                devices={devices}
                loading={loading}
                initialDeviceId={analysisDevice}
              />
            )}

            {tab === "inventory" && (
              <DeviceInventorySection
                devices={devices}
                loading={loading}
                error={error}
                onRefresh={refresh}
              />
            )}

            {tab === "register" && (
              <>
                <h1 className="text-3xl font-bold tracking-wide mb-2">
                  REGISTER A DEVICE
                </h1>
                <p className="text-gray-400 text-xs leading-relaxed mb-8">
                  Add a network device to a tenant. Each device gets a unique ID
                  such as DEV-0001, which is used to track its audits.
                </p>
                <DeviceRegistration onRegistered={refresh} />
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

// // The first tab is the device information; graphs come next.
// const TABS = [
//   { id: "overview", label: "DEVICE STATUS", Icon: Activity },
//   { id: "analysis", label: "DEVICE ANALYSIS", Icon: LineChart },
//   { id: "inventory", label: "DEVICE INVENTORY", Icon: Server },
//   { id: "register", label: "REGISTER DEVICE", Icon: PlusSquare },
// ];

// export default function AnalystDashboard() {
//   const { user, signOut } = useAuth();
//   const navigate = useNavigate();
//   const [tab, setTab] = useState("overview");
//   const [analysisDevice, setAnalysisDevice] = useState("");
//   const { devices, loading, error, refresh } = useDevices();

//   const handleLogout = async () => {
//     await signOut();
//     navigate("/", { replace: true });
//   };

//   // "VIEW GRAPHS" in the status table jumps to the analysis tab for that device.
//   const openAnalysis = (deviceId) => {
//     setAnalysisDevice(deviceId);
//     setTab("analysis");
//   };

//   const tabClass = (t) =>
//     `flex items-center gap-3 text-xs tracking-wider p-3 text-left transition-colors ${
//       tab === t
//         ? "bg-white text-black"
//         : "text-gray-400 hover:text-white border border-transparent hover:border-gray-700"
//     }`;

//   return (
//     <div className="h-screen bg-black text-white font-mono flex flex-col overflow-hidden">
//       <header className="w-full flex justify-between items-center px-8 py-5 border-b border-gray-800 shrink-0">
//         <div className="flex items-center gap-2 text-xl font-bold tracking-widest">
//           <Shield className="w-5 h-5" />
//           Suraksha<span className="font-light">Asthri</span>
//           <span className="ml-4 text-xs bg-white text-black px-2 py-0.5 tracking-widest hidden sm:inline">
//             ANALYST WORKSPACE
//           </span>
//         </div>
//         <div className="flex items-center gap-4 text-xs text-gray-500">
//           <span className="hidden md:inline">// {user?.email}</span>
//           <button
//             onClick={handleLogout}
//             className="border border-gray-600 text-gray-200 px-4 py-1.5 hover:border-white hover:text-white transition-colors"
//           >
//             LOGOUT
//           </button>
//         </div>
//       </header>

//       <div className="flex flex-1 min-h-0">
//         <aside className="w-56 shrink-0 border-r border-gray-800 p-6 flex flex-col gap-3">
//           <div className="text-gray-500 text-[10px] tracking-widest mb-2 border-b border-gray-800 pb-2">
//             MODULES
//           </div>
//           {TABS.map(({ id, label, Icon }) => (
//             <button key={id} onClick={() => setTab(id)} className={tabClass(id)}>
//               <Icon className="w-4 h-4 shrink-0" /> {label}
//             </button>
//           ))}
//         </aside>

//         <main className="flex-1 min-w-0 overflow-y-auto p-8 lg:p-12">
//           {/* Only the open tab is mounted, so each one loads fresh data when opened. */}
//           <div className={`mx-auto w-full ${tab === "register" ? "max-w-2xl" : "max-w-5xl"}`}>
//             {tab === "overview" && <DeviceOverviewSection onAnalyze={openAnalysis} />}

//             {tab === "analysis" && (
//               <DeviceAnalysisSection devices={devices} loading={loading} initialDeviceId={analysisDevice} />
//             )}

//             {tab === "inventory" && (
//               <DeviceInventorySection devices={devices} loading={loading} error={error} onRefresh={refresh} />
//             )}

//             {tab === "register" && (
//               <>
//                 <h1 className="text-3xl font-bold tracking-wide mb-2">REGISTER A DEVICE</h1>
//                 <p className="text-gray-400 text-xs leading-relaxed mb-8">
//                   Add a network device to a tenant. Each device gets a unique ID such as DEV-0001, which
//                   is used to track its audits.
//                 </p>
//                 <DeviceRegistration onRegistered={refresh} />
//               </>
//             )}
//           </div>
//         </main>
//       </div>
//     </div>
//   );
// }

// import { useEffect, useState } from "react";
// import { useNavigate } from "react-router-dom";
// import { Shield, PlusSquare, Server } from "lucide-react";
// import { useAuth } from "../components/AuthContext";
// import DeviceRegistration from "../components/DeviceRegistration";

// const tenantOf = (d) => d.tenant_name ?? d.tenant?.name ?? (typeof d.tenant === "string" ? d.tenant : "-");

// export default function AnalystDashboard() {
//   const { user, session, signOut } = useAuth();
//   const navigate = useNavigate();
//   const [tab, setTab] = useState("register");
//   const [devices, setDevices] = useState([]);
//   const [loading, setLoading] = useState(true);
//   const [listError, setListError] = useState("");

//   // GET /api/devices/
//   useEffect(() => {
//     if (!session) return;
//     let live = true;
//     (async () => {
//       try {
//         const res = await fetch("/api/devices/", {
//           headers: { Authorization: `Bearer ${session.access_token}` },
//         });
//         if (!res.ok) throw new Error(`server returned ${res.status}`);
//         const data = await res.json();
//         if (live) setDevices(Array.isArray(data) ? data : data.results ?? []);
//       } catch (err) {
//         if (live) setListError(err.message);
//       }
//       if (live) setLoading(false);
//     })();
//     return () => { live = false; };
//   }, [session]);

//   const handleLogout = async () => {
//     await signOut();
//     navigate("/", { replace: true });
//   };

//   const tabClass = (t) =>
//     `flex items-center gap-3 text-xs tracking-wider p-3 text-left transition-colors ${
//       tab === t
//         ? "bg-white text-black"
//         : "text-gray-400 hover:text-white border border-transparent hover:border-gray-700"
//     }`;

//   return (
//     <div className="h-screen bg-black text-white font-mono flex flex-col overflow-hidden">
//       <header className="w-full flex justify-between items-center px-8 py-5 border-b border-gray-800 shrink-0">
//         <div className="flex items-center gap-2 text-xl font-bold tracking-widest">
//           <Shield className="w-5 h-5" />
//           Suraksha<span className="font-light">Asthri</span>
//           <span className="ml-4 text-xs bg-white text-black px-2 py-0.5 tracking-widest hidden sm:inline">
//             ANALYST WORKSPACE
//           </span>
//         </div>
//         <div className="flex items-center gap-4 text-xs text-gray-500">
//           <span className="hidden md:inline">// {user?.email}</span>
//           <button
//             onClick={handleLogout}
//             className="border border-gray-600 text-gray-200 px-4 py-1.5 hover:border-white hover:text-white transition-colors"
//           >
//             LOGOUT
//           </button>
//         </div>
//       </header>

//       <div className="flex flex-1 min-h-0">
//         <aside className="w-56 shrink-0 border-r border-gray-800 p-6 flex flex-col gap-3">
//           <div className="text-gray-500 text-[10px] tracking-widest mb-2 border-b border-gray-800 pb-2">
//             MODULES
//           </div>
//           <button onClick={() => setTab("register")} className={tabClass("register")}>
//             <PlusSquare className="w-4 h-4 shrink-0" /> REGISTER DEVICE
//           </button>
//           <button onClick={() => setTab("inventory")} className={tabClass("inventory")}>
//             <Server className="w-4 h-4 shrink-0" /> DEVICE INVENTORY
//           </button>
//         </aside>

//         <main className="flex-1 min-w-0 overflow-y-auto p-8 lg:p-12">
//           <div className="max-w-2xl">
//             {tab === "register" && (
//               <>
//                 <h1 className="text-3xl font-bold tracking-wide mb-2">REGISTER A DEVICE</h1>
//                 <p className="text-gray-400 text-xs leading-relaxed mb-8">
//                   Add a network device to a tenant. Each device gets a unique ID such as DEV-0001, which
//                   is used to track its audits.
//                 </p>
//                 <DeviceRegistration onRegistered={(d) => setDevices((list) => [d, ...list])} />
//               </>
//             )}

//             {tab === "inventory" && (
//               <>
//                 <h1 className="text-3xl font-bold tracking-wide mb-2">DEVICE INVENTORY</h1>
//                 <p className="text-gray-400 text-xs leading-relaxed mb-8">
//                   All devices registered so far, newest first.
//                 </p>

//                 {loading && <p className="text-xs text-gray-500">Loading devices...</p>}
//                 {listError && (
//                   <p role="alert" className="border border-red-500/60 text-red-400 text-xs px-3 py-2">
//                     Could not load devices: {listError}
//                   </p>
//                 )}
//                 {!loading && !listError && devices.length === 0 && (
//                   <p className="text-xs text-gray-500">No devices yet. Register one first.</p>
//                 )}

//                 {devices.length > 0 && (
//                   <div className="border border-gray-800 overflow-x-auto">
//                     <table className="w-full text-xs text-left">
//                       <thead className="text-[10px] text-gray-500 tracking-wider border-b border-gray-800">
//                         <tr>
//                          {["ID", "HOSTNAME", "VENDOR", "TYPE", "TENANT", "SITE", "SERIAL"].map((h) => (
//                             <th key={h} className="px-4 py-3 font-normal whitespace-nowrap">{h}</th>
//                           ))}
//                         </tr>
//                       </thead>
//                       <tbody className="divide-y divide-gray-800">
//                         {devices.map((d, i) => (
//                           <tr key={d.device_id ?? d.id ?? i}>
//                             <td className="px-4 py-3 whitespace-nowrap">{d.device_id ?? "-"}</td>
//                             <td className="px-4 py-3">{d.hostname}</td>
//                             <td className="px-4 py-3">{d.vendor}</td>
//                             <td className="px-4 py-3 capitalize">{(d.device_type ?? "-").replace(/_/g, " ")}</td>
//                             <td className="px-4 py-3">{tenantOf(d)}</td>
//                             <td className="px-4 py-3">{d.site || "-"}</td>
//                             <td className="px-4 py-3">{d.serial_number || "-"}</td>
//                           </tr>
//                         ))}
//                       </tbody>
//                     </table>
//                   </div>
//                 )}
//               </>
//             )}
//           </div>
//         </main>

//       </div>
//     </div>
//   );
// }
