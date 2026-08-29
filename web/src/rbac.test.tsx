import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { RoleProvider, rolePermissions, useRole } from "./rbac";

function RoleProbe() {
  const { role, setRole, can } = useRole();
  return (
    <div>
      <span data-testid="role">{role}</span>
      <span data-testid="settings">{String(can("settings"))}</span>
      <button onClick={() => setRole("production")}>production</button>
    </div>
  );
}

describe("demo RBAC", () => {
  beforeEach(() => localStorage.clear());

  it("defines all six demo roles", () => {
    expect(Object.keys(rolePermissions)).toHaveLength(6);
  });

  it("switches role and persists the choice", () => {
    render(<RoleProvider><RoleProbe /></RoleProvider>);
    expect(screen.getByTestId("role")).toHaveTextContent("management");
    expect(screen.getByTestId("settings")).toHaveTextContent("true");
    fireEvent.click(screen.getByRole("button", { name: "production" }));
    expect(screen.getByTestId("role")).toHaveTextContent("production");
    expect(screen.getByTestId("settings")).toHaveTextContent("false");
    expect(localStorage.getItem("demo-role")).toBe("production");
  });
});
