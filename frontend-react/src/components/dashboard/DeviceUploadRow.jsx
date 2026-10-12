import { useRef, useState } from "react";
import { FileText, X } from "lucide-react";
import { ACCEPT, labelClass, selectClass, tenantOf, typeLabel } from "./dashboardApi";

export default function DeviceUploadRow({
  index, row, devices, devicesLoading, canRemove, onDevice, onFile, onRemove,
}) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const device = devices.find((d) => d.device_id === row.deviceId);
  const open = () => inputRef.current?.click();

  return (
    <div className="border border-gray-800 p-4 mb-4">
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs text-gray-400">Device {index + 1}</span>
        {canRemove && (
          <button type="button" onClick={onRemove} aria-label={`Remove device ${index + 1}`}
            className="text-gray-600 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <label htmlFor={`device-${row.id}`} className={labelClass}>DEVICE ID</label>
      <select id={`device-${row.id}`} value={row.deviceId} onChange={(e) => onDevice(e.target.value)}
        className={`${selectClass} mb-3`}>
        <option value="">{devicesLoading ? "Loading devices..." : "Select a registered device"}</option>
        {devices.map((d) => (
          <option key={d.device_id} value={d.device_id}>{d.device_id} · {d.hostname}</option>
        ))}
      </select>

      {!devicesLoading && devices.length === 0 && (
        <p className="text-[10px] text-gray-500 mb-3">
          No devices registered yet. An analyst needs to register devices first.
        </p>
      )}

      {device && (
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 text-xs">
          {[["Vendor", device.vendor], ["Type", typeLabel(device.device_type)],
            ["Hostname", device.hostname], ["Tenant", tenantOf(device)]].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[10px] text-gray-500">{k}</dt>
              <dd className="text-gray-200 break-all">{v}</dd>
            </div>
          ))}
        </dl>
      )}

      <input ref={inputRef} type="file" accept={ACCEPT} className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }} />
      <div
        role="button" tabIndex={0} onClick={open}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open())}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onFile(f);
        }}
        className={`border border-dashed p-6 text-center cursor-pointer transition-colors focus:outline-none focus:border-white ${
          dragging ? "border-white" : "border-gray-600 hover:border-white"
        }`}
      >
        <FileText className={`w-7 h-7 mx-auto mb-2 ${row.file ? "text-white" : "text-gray-600"}`} />
        {row.file ? (
          <>
            <p className="text-xs text-white break-all">{row.file.name}</p>
            <p className="text-[10px] text-gray-500 mt-1">
              {(row.file.size / 1024).toFixed(1)} KB. Click to choose a different file.
            </p>
          </>
        ) : (
          <>
            <p className="text-xs text-gray-400">Drop a config file here or click to browse</p>
            <p className="text-[10px] text-gray-600 mt-1">Supports .txt, .conf, .cfg</p>
          </>
        )}
      </div>
    </div>
  );
}