import { useState } from "react";
import { RULE_BADGE, showValue } from "./scheduleUi";

const ORDER = { Fail: 0, Unknown: 1, Manual: 2, Pass: 3 };
const GROUPS = [
  ["ALL", () => true],
  ["FAILED", (r) => r.status === "Fail"],
  ["PASSED", (r) => r.status === "Pass"],
  ["UNDECIDED", (r) => r.status === "Unknown" || r.status === "Manual"],
];

export default function CriteriaList({ criteria }) {
  const [group, setGroup] = useState(() => (criteria.some((r) => r.status === "Fail") ? "FAILED" : "ALL"));
  const test = GROUPS.find(([name]) => name === group)[1];
  const rows = criteria.filter(test).sort((a, b) => (ORDER[a.status] ?? 4) - (ORDER[b.status] ?? 4));

  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-4">
        {GROUPS.map(([name, fn]) => (
          <button key={name} type="button" onClick={() => setGroup(name)}
            className={`px-4 py-2 text-sm border transition-colors ${
              group === name ? "bg-white text-black border-white" : "border-gray-600 text-gray-200 hover:border-white"}`}>
            {name} ({criteria.filter(fn).length})
          </button>
        ))}
      </div>

      {rows.length === 0 && <p className="text-base text-gray-300">Nothing in this group.</p>}
      <ul className="divide-y divide-gray-800 border border-gray-700">
        {rows.map((r) => {
          const badge = RULE_BADGE[r.status] ?? RULE_BADGE.Manual;
          return (
            <li key={r.rule_id} className="px-5 py-4">
              <div className="flex flex-wrap items-start gap-4">
                <span className={`shrink-0 w-28 text-center border px-2 py-1.5 text-xs tracking-widest ${badge.cls}`}>
                  {badge.label}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-base text-white leading-snug">
                    <span className="text-gray-400">[{r.rule_id}]</span> {r.name}
                    {r.severity && (
                      <span className="ml-3 text-xs text-gray-300 border border-gray-600 px-2 py-0.5 align-middle">
                        {r.severity} severity
                      </span>
                    )}
                  </p>
                  <dl className="grid sm:grid-cols-3 gap-x-6 gap-y-3 mt-3 text-sm">
                    <div>
                      <dt className="text-xs tracking-wider text-gray-400 mb-1">FIELD</dt>
                      <dd className="text-gray-200 break-all">{r.field}</dd>
                    </div>
                    <div>
                      <dt className="text-xs tracking-wider text-gray-400 mb-1">EXPECTED</dt>
                      <dd className="text-gray-200 break-words">{showValue(r.expected)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs tracking-wider text-gray-400 mb-1">ACTUAL</dt>
                      <dd className={`break-words ${r.status === "Fail" ? "text-red-300" : "text-gray-200"}`}>
                        {showValue(r.actual)}
                      </dd>
                    </div>
                  </dl>
                  {r.reason && <p className="mt-3 text-sm text-gray-400 italic">{r.reason}</p>}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}