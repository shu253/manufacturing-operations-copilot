import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { Role } from "./types";

export const roleLabels: Record<Role, string> = {
  admin: "系统管理员",
  management: "经营管理层",
  procurement: "采购人员",
  production: "生产人员",
  sales: "销售人员",
  finance: "财务人员"
};

export const rolePermissions: Record<Role, string[]> = {
  admin: ["*"],
  management: ["dashboard", "orders", "procurement", "suppliers", "cost", "quote", "scenario", "receivables", "reports", "assistant", "tasks", "settings"],
  procurement: ["dashboard", "orders", "procurement", "suppliers", "cost", "scenario", "assistant", "tasks"],
  production: ["dashboard", "orders", "procurement", "assistant", "tasks"],
  sales: ["dashboard", "orders", "cost", "quote", "receivables", "reports", "assistant", "tasks"],
  finance: ["dashboard", "orders", "cost", "quote", "receivables", "reports", "assistant", "tasks"]
};

interface RoleContextValue {
  role: Role;
  setRole: (role: Role) => void;
  can: (permission: string) => boolean;
}

const RoleContext = createContext<RoleContextValue | null>(null);

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<Role>(() => (localStorage.getItem("demo-role") as Role) || "management");
  const value = useMemo<RoleContextValue>(() => ({
    role,
    setRole: next => {
      localStorage.setItem("demo-role", next);
      setRoleState(next);
    },
    can: permission => rolePermissions[role].includes("*") || rolePermissions[role].includes(permission)
  }), [role]);
  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole() {
  const context = useContext(RoleContext);
  if (!context) throw new Error("useRole必须在RoleProvider中使用");
  return context;
}
