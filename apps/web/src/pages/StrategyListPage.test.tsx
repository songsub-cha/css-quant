import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { FIXTURE_STRATEGIES, resetStrategies } from "../test/msw/handlers";
import { server } from "../test/msw/server";
import StrategyListPage from "./StrategyListPage";

afterEach(() => resetStrategies());

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/strategies"]}>
        <Routes>
          <Route path="/strategies" element={<StrategyListPage />} />
          <Route path="/strategies/:id" element={<p>편집 화면</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StrategyListPage", () => {
  it("lists fixture strategies with status/execution mode/version", async () => {
    renderPage();

    const row = (await screen.findByText(/내 추세추종 전략/)).closest("li");
    if (!row) throw new Error("row not found");
    expect(screen.getByText(/AI 모멘텀 실전/)).toBeInTheDocument();
    expect(within(row).getByText(/초안 · 백테스트 · v1/)).toBeInTheDocument();
  });

  it("filters the list by status", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/내 추세추종 전략/);

    await user.click(screen.getByRole("button", { name: "활성" }));

    await waitFor(() => {
      expect(screen.queryByText(/내 추세추종 전략/)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/AI 모멘텀 실전/)).toBeInTheDocument();
  });

  it("creates a strategy from a template and navigates to its edit page", async () => {
    const user = userEvent.setup();
    renderPage();

    const templateCard = (await screen.findByText("추세추종")).closest("div");
    if (!templateCard) throw new Error("template card not found");

    await user.click(within(templateCard).getByRole("button", { name: "이 템플릿으로 생성" }));

    expect(await screen.findByText("편집 화면")).toBeInTheDocument();
  });

  it("creates a blank strategy with just a name and execution mode", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/내 추세추종 전략/);

    await user.type(screen.getByPlaceholderText("전략 이름"), "빈 전략 테스트");
    await user.click(screen.getByRole("button", { name: "빈 전략 생성" }));

    expect(await screen.findByText("편집 화면")).toBeInTheDocument();
  });

  it("pauses an active strategy and reflects the status change immediately", async () => {
    const user = userEvent.setup();
    renderPage();
    const row = (await screen.findByText(/AI 모멘텀 실전/)).closest("li");
    if (!row) throw new Error("row not found");

    await user.click(within(row).getByRole("button", { name: "일시정지" }));

    await waitFor(() => {
      expect(within(row).getByText(/일시정지/)).toBeInTheDocument();
    });
  });

  it("shows an inline 409 error when deleting an active strategy, and it stays in the list", async () => {
    const user = userEvent.setup();
    renderPage();
    const row = (await screen.findByText(/AI 모멘텀 실전/)).closest("li");
    if (!row) throw new Error("row not found");

    await user.click(within(row).getByRole("button", { name: "삭제" }));

    expect(
      await screen.findByText("Cannot delete an active strategy — pause or archive it first."),
    ).toBeInTheDocument();
    expect(screen.getByText(/AI 모멘텀 실전/)).toBeInTheDocument();
  });

  it("shows an inline error when an action fails with a 500", async () => {
    const strategy = FIXTURE_STRATEGIES[0];
    server.use(
      http.post(`/api/v1/strategies/${strategy.id}/clone`, () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Internal Server Error",
            status: 500,
            detail: "복제에 실패했어요.",
          },
          { status: 500, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    const row = (await screen.findByText(/내 추세추종 전략/)).closest("li");
    if (!row) throw new Error("row not found");

    await user.click(within(row).getByRole("button", { name: "복제" }));

    expect(await screen.findByText("복제에 실패했어요.")).toBeInTheDocument();
  });
});
