"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { LockKeyhole } from "lucide-react";
import { Button, Card, Field, Input } from "@/components/ui/primitives";
import { useAuth, roleHome } from "@/lib/auth";
import { useT } from "@/lib/locale";

export default function LoginPage() {
  const t = useT();
  const { login } = useAuth();
  const router = useRouter();
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = await login(loginName.trim(), password);
      router.replace(roleHome(session.role));
      router.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("login.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden bg-canvas px-4 py-10">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_18%_-12%,color-mix(in_srgb,var(--color-accent)_18%,transparent),transparent_58%)]"
      />
      <div className="relative w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center gap-3 text-center">
          <img src="/brand/errno-logo.png" alt="ERRNO" className="errno-logo h-12 w-auto" />
          <p className="font-mono text-[10px] tracking-[0.2em] text-muted uppercase">{t("login.missionTag")}</p>
        </div>
        <Card className="border-line/80 shadow-[var(--shadow-pop)]">
          <div className="mb-5">
            <div className="mb-3 grid size-10 place-items-center rounded-xl bg-accent/10 text-accent">
              <LockKeyhole className="size-5" />
            </div>
            <h1 className="text-lg font-semibold">{t("login.title")}</h1>
            <p className="mt-1 text-sm text-muted">{t("login.subtitle")}</p>
          </div>
          <form onSubmit={submit} className="space-y-4">
            <Field label={t("login.username")}>
              <Input autoComplete="username" value={loginName} onChange={(event) => setLoginName(event.target.value)} required />
            </Field>
            <Field label={t("login.password")}>
              <Input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
            </Field>
            {error ? (
              <p role="alert" className="rounded-lg border border-critical/30 bg-critical/10 px-3 py-2 text-xs text-critical">
                {error}
              </p>
            ) : null}
            <Button type="submit" className="w-full" loading={busy}>
              {t("login.submit")}
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-xs text-muted">{t("login.footnote")}</p>
      </div>
    </main>
  );
}