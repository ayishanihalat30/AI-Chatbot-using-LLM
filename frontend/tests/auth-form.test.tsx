import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthForm } from "@/components/AuthForm";
import { I18nProvider } from "@/lib/i18n";

afterEach(() => vi.restoreAllMocks());

function setup(onDone = vi.fn()) {
  render(
    <I18nProvider>
      <AuthForm onDone={onDone} />
    </I18nProvider>,
  );
  return onDone;
}

describe("AuthForm", () => {
  it("logs in against the API and reports success", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ access_token: "a", refresh_token: "r" }), { status: 200 }),
    );
    const done = setup();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "me@example.com" } });
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: "password123" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/auth/login");
  });

  it("shows the server error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid email or password" }), { status: 401 }));
    setup();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "me@example.com" } });
    fireEvent.change(screen.getByLabelText(/Password/), { target: { value: "x" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  });

  it("switches to registration and can change language", () => {
    setup();
    fireEvent.click(screen.getByText("No account yet? Create one"));
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "fr" } });
    expect(screen.getByRole("button", { name: "Créer un compte" })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe("ltr");
    fireEvent.change(screen.getByLabelText("Langue"), { target: { value: "ar" } });
    expect(document.documentElement.dir).toBe("rtl");
  });
});
