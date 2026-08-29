import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

interface AppContextValue {
  asOfDate: string;
  setAsOfDate: (value: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

function getLocalToday() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function AppContextProvider({ children }: { children: ReactNode }) {
  // Always start a newly opened page with today's local date. A historical
  // date selected by the user remains active while navigating in this session,
  // but it must not silently become tomorrow's default through localStorage.
  const [asOfDate, setAsOfDateState] = useState(getLocalToday);
  const value = useMemo(() => ({
    asOfDate,
    setAsOfDate: (next: string) => {
      setAsOfDateState(next);
    }
  }), [asOfDate]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppContext() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useAppContext必须在AppContextProvider中使用");
  return value;
}
