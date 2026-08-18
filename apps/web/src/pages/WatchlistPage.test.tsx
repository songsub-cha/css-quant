import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { resetWatchlistItems } from "../test/msw/handlers";
import { server } from "../test/msw/server";
import WatchlistPage from "./WatchlistPage";

afterEach(() => resetWatchlistItems());

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/watchlist"]}>
        <WatchlistPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WatchlistPage", () => {
  it("lists fixture items with ticker/name instead of a raw asset_id", async () => {
    renderPage();

    expect(await screen.findByText(/삼성전자/)).toBeInTheDocument();
    expect(screen.getByText(/SK하이닉스/)).toBeInTheDocument();
    expect(screen.queryByText(/ast_/)).not.toBeInTheDocument();
  });

  it("filters the list by kind", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/삼성전자/);

    await user.click(screen.getByRole("button", { name: "제외" }));

    await waitFor(() => {
      expect(screen.queryByText(/삼성전자/)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/SK하이닉스/)).toBeInTheDocument();
  });

  it("shows an empty state when no item matches", async () => {
    server.use(http.get("/api/v1/watchlist", () => HttpResponse.json([])));
    renderPage();

    expect(await screen.findByText("등록된 종목이 없어요.")).toBeInTheDocument();
  });

  it("removes an item on 해제 click and it disappears from the list", async () => {
    const user = userEvent.setup();
    renderPage();
    const row = (await screen.findByText(/삼성전자/)).closest("li");
    if (!row) throw new Error("row not found");

    await user.click(within(row).getByRole("button", { name: "해제" }));

    await waitFor(() => {
      expect(screen.queryByText(/삼성전자/)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/SK하이닉스/)).toBeInTheDocument();
  });

  it("shows an inline error message when removal fails", async () => {
    server.use(
      http.delete("/api/v1/watchlist/:assetId", () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Internal Server Error",
            status: 500,
            detail: "해제에 실패했어요.",
          },
          { status: 500, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    const row = (await screen.findByText(/삼성전자/)).closest("li");
    if (!row) throw new Error("row not found");

    await user.click(within(row).getByRole("button", { name: "해제" }));

    expect(await screen.findByText("해제에 실패했어요.")).toBeInTheDocument();
    expect(screen.getByText(/삼성전자/)).toBeInTheDocument();
  });
});
