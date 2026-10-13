import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Activity, LineChart, Search, Shield, PlusSquare, Server, Clock, History } from "lucide-react";
import AuditScheduleSection from "../components/analyst/AuditScheduleSection";
import AuditHistorySection from "../components/analyst/AuditHistorySection";
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
  { id: "schedules", label: "AUDIT SCHEDULES", Icon: Clock },
  { id: "history", label: "AUDIT HISTORY", Icon: History },
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
            
            {tab === "schedules" && (
              <AuditScheduleSection devices={devices} devicesLoading={loading} />
            )}
            
            {tab === "history" && (
              <AuditHistorySection devices={devices} />
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


// import { useState } from "react";
// import { useNavigate } from "react-router-dom";
// // import { Shield, PlusSquare, Server, Activity, LineChart , Search} from "lucide-react";
// import { Activity, LineChart, Search } from "lucide-react";
// import { Shield, PlusSquare, Server, Clock, History } from "lucide-react";
// import AuditScheduleSection from "../components/analyst/AuditScheduleSection";
// import AuditHistorySection from "../components/analyst/AuditHistorySection";
// import { useAuth } from "../components/AuthContext";
// import DeviceRegistration from "../components/DeviceRegistration";
// import useDevices from "../components/dashboard/useDevices";
// import DeviceOverviewSection from "../components/dashboard-analys/DeviceOverviewSection.jsx";
// import DeviceAnalysisSection from "../components/dashboard-analys/DeviceAnalysisSection";
// import DeviceInventorySection from "../components/dashboard/DeviceInventorySection";
// import DeviceQuerySection from "../components/dashboard-analys/DeviceQuerySection";
// const TABS = [
//   { id: "overview", label: "DEVICE STATUS", Icon: Activity },
//   { id: "ask", label: "ASK DEVICES", Icon: Search },
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

//   // "VIEW GRAPHS" (status table) and "ANALYZE" (search results) jump to the analysis tab for that device.
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
//           Suraksha<span className="font-light">Asthra</span>
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
//             <button
//               key={id}
//               onClick={() => setTab(id)}
//               className={tabClass(id)}
//             >
//               <Icon className="w-4 h-4 shrink-0" /> {label}
//             </button>
//           ))}
//         </aside>

//         <main className="flex-1 min-w-0 overflow-y-auto p-8 lg:p-12">
//           {/* Only the open tab is mounted, so each one loads fresh data when opened. */}
//           <div
//             className={`mx-auto w-full ${tab === "register" ? "max-w-2xl" : "max-w-5xl"}`}
//           >
//             {tab === "overview" && (
//               <DeviceOverviewSection onAnalyze={openAnalysis} />
//             )}

//             {tab === "ask" && <DeviceQuerySection onAnalyze={openAnalysis} />}

//             {tab === "analysis" && (
//               <DeviceAnalysisSection
//                 devices={devices}
//                 loading={loading}
//                 initialDeviceId={analysisDevice}
//               />
//             )}

//             {tab === "inventory" && (
//               <DeviceInventorySection
//                 devices={devices}
//                 loading={loading}
//                 error={error}
//                 onRefresh={refresh}
//               />
//             )}

//             {tab === "register" && (
//               <>
//                 <h1 className="text-3xl font-bold tracking-wide mb-2">
//                   REGISTER A DEVICE
//                 </h1>
//                 <p className="text-gray-400 text-xs leading-relaxed mb-8">
//                   Add a network device to a tenant. Each device gets a unique ID
//                   such as DEV-0001, which is used to track its audits.
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

