import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, Mail, ShieldCheck, User as UserIcon } from "lucide-react";
import { Card } from "@/components/Card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/lib/auth-context";
import { v1Api } from "@/lib/api";
import type { CurrentUserResponse } from "@/types/api";

function initialsFor(email?: string): string {
  if (!email) return "?";
  return email.slice(0, 2).toUpperCase();
}

/** Account settings - deliberately limited to what's real (identity + sign
 * out). No notification/appearance toggles: there's no backend for them, and
 * fake controls that do nothing would be misleading. */
export function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [me, setMe] = useState<CurrentUserResponse | null>(null);

  useEffect(() => {
    v1Api
      .me()
      .then(setMe)
      .catch(() => undefined);
  }, []);

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">Manage your EMIOS account.</p>
      </div>

      <Card className="p-6">
        <div className="flex items-center gap-4">
          <Avatar className="size-14">
            <AvatarFallback className="text-lg">{initialsFor(user?.email)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold text-foreground">{user?.email ?? "Loading..."}</p>
            <p className="text-sm text-muted-foreground">
              {me ? `Member since ${new Date(me.created_at).toLocaleDateString()}` : " "}
            </p>
          </div>
        </div>

        <Separator className="my-6" />

        <dl className="space-y-4 text-sm">
          <div className="flex items-center justify-between gap-4">
            <dt className="flex items-center gap-2 text-muted-foreground">
              <Mail className="h-4 w-4" /> Email
            </dt>
            <dd className="truncate text-foreground">{user?.email ?? "—"}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="flex items-center gap-2 text-muted-foreground">
              <UserIcon className="h-4 w-4" /> User ID
            </dt>
            <dd className="truncate font-mono text-xs text-foreground/80">{user?.user_id ?? "—"}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="flex items-center gap-2 text-muted-foreground">
              <ShieldCheck className="h-4 w-4" /> Authentication
            </dt>
            <dd className="text-foreground">Email + password (JWT session)</dd>
          </div>
        </dl>
      </Card>

      <Card className="p-6">
        <h2 className="mb-1 text-sm font-semibold text-foreground">Sign out</h2>
        <p className="mb-4 text-sm text-muted-foreground">End your current session on this device.</p>
        <Button variant="destructive" onClick={handleLogout}>
          <LogOut className="h-4 w-4" /> Log out
        </Button>
      </Card>
    </div>
  );
}
