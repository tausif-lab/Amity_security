export const ACCEPT = ".txt,.conf,.cfg";
export const labelClass = "block text-[10px] text-gray-500 tracking-wider mb-2";
export const selectClass =
  "w-full bg-black border border-gray-700 text-sm px-4 py-3 focus:outline-none focus:border-white transition-colors cursor-pointer";
export const primaryBtn =
  "w-full border border-white bg-white text-black py-3 text-xs tracking-widest hover:bg-transparent hover:text-white transition-colors disabled:opacity-50";
export const outlineBtn =
  "border border-gray-600 text-gray-200 px-4 py-2 text-xs tracking-widest hover:border-white hover:text-white transition-colors disabled:opacity-50";

export const authHeaders = (token) => (token ? { Authorization: `Bearer ${token}` } : {});
export const jsonHeaders = (token) => ({ "Content-Type": "application/json", ...authHeaders(token) });

export const typeLabel = (t) => (t ? t.replace(/_/g, " ") : "-");
export const tenantOf = (d) => (typeof d.tenant === "string" ? d.tenant : d.tenant?.name ?? "-");

// Fetch a file and save it through the browser's normal download.
export async function downloadBlob(url, token, filename) {
  const res = await fetch(url, { headers: authHeaders(token) });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || data.detail || `Server returned ${res.status}`);
  }
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}