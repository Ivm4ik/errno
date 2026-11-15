"use client";

import { useState } from "react";
import { RoleGate } from "@/components/auth/role-gate";
import { Card } from "@/components/ui/primitives";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { useT } from "@/lib/locale";

export default function AuditPage() {
  return <RoleGate roles={["doctor", "chief"]}><Audit /></RoleGate>;
}

function Audit() {
  const t = useT();
  const { user } = useAuth();
  const [result, setResult] = useState<string>("");
  const [rows, setRows] = useState<{ id: number; kind: string; ts: number }[]>([]);
  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <h1 className="text-lg font-semibold">{t("medic.auditTitle")}</h1>
        <p className="text-sm text-muted">{t("medic.auditDesc")}</p>
        <div className="flex gap-2">
          <button className="rounded-lg bg-accent px-3 py-1 text-sm text-accent-ink" onClick={async () => {
            const verify = await api.get<{ ok: boolean; broken_at: number | null; total: number }>("/audit/verify");
            const log = await api.get<{ id: number; kind: string; ts: number }[]>("/audit?limit=20");
            setResult(verify.ok ? t("medic.chainOk", { total: verify.total }) : t("medic.chainBroken", { at: verify.broken_at ?? 0 }));
            setRows(log);
          }}>{t("medic.verifyChain")}</button>
          <button className="rounded-lg border border-line px-3 py-1 text-sm" onClick={async () => {
            try {
              await api.post("/audit/tamper");
              setResult(t("medic.demoTamperDone"));
            } catch (error) {
              setResult(error instanceof Error ? error.message : t("medic.tamperUnavailable"));
            }
          }}>{t("medic.demoTamper")}</button>
        </div>
        {result && <p className="text-sm">{result}</p>}
      </Card>
      <Card className="p-4">
        <ul className="space-y-1 font-mono text-xs">{rows.map((row) => <li key={row.id}>{row.id} {row.kind}</li>)}</ul>
        {user?.role === "chief" && <p className="mt-3 text-sm text-muted">{t("medic.chiefAccountsNote")}</p>}
      </Card>
    </div>
  );
}