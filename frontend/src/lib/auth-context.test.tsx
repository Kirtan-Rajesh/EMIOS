import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import { v1Api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  v1Api: {
    me: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  },
}));

function Probe() {
  const { user, loading, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{user?.email ?? "none"}</span>
      <button onClick={() => login("a@b.com", "pw")}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

describe("AuthProvider", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("resolves the session from the httpOnly cookie via me() on mount", async () => {
    vi.mocked(v1Api.me).mockResolvedValue({ user_id: "u1", email: "a@b.com", created_at: "2026-01-01" });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("user")).toHaveTextContent("a@b.com");
  });

  it("treats a failed me() (no valid session cookie) as logged out, not an error", async () => {
    vi.mocked(v1Api.me).mockRejectedValue(new Error("401"));
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("login sets user from the response body - the session cookie itself arrives via Set-Cookie, not JS", async () => {
    vi.mocked(v1Api.me).mockRejectedValue(new Error("401"));
    vi.mocked(v1Api.login).mockResolvedValue({
      access_token: "unused-by-the-browser-client",
      token_type: "bearer",
      user: { user_id: "u1", email: "a@b.com" },
    });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
    await userEvent.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("a@b.com"));
  });

  it("logout calls the backend logout endpoint and clears user client-side even if that call fails", async () => {
    vi.mocked(v1Api.me).mockResolvedValue({ user_id: "u1", email: "a@b.com", created_at: "2026-01-01" });
    vi.mocked(v1Api.logout).mockRejectedValue(new Error("network error"));
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("a@b.com"));
    await userEvent.click(screen.getByText("logout"));
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("none"));
    expect(v1Api.logout).toHaveBeenCalled();
  });
});
