import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { FIXTURE_STRATEGIES, resetStrategies } from "../test/msw/handlers";
import { server } from "../test/msw/server";
import StrategyEditPage from "./StrategyEditPage";

afterEach(() => resetStrategies());

function renderPage(id: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/strategies/${id}`]}>
        <Routes>
          <Route path="/strategies/:id" element={<StrategyEditPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StrategyEditPage", () => {
  it("loads an existing strategy into the form and saves an edit", async () => {
    const user = userEvent.setup();
    const strategy = FIXTURE_STRATEGIES[0];
    renderPage(strategy.id);

    const nameInput = await screen.findByDisplayValue(strategy.name);
    await user.clear(nameInput);
    await user.type(nameInput, "수정된 전략 이름");

    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(await screen.findByText("저장했어요.")).toBeInTheDocument();
  });

  it("fills in sell_rules fields including the trailing stop and saves them", async () => {
    const user = userEvent.setup();
    const strategy = FIXTURE_STRATEGIES[0];
    renderPage(strategy.id);

    await screen.findByDisplayValue(strategy.name);
    await user.type(screen.getByLabelText("손절(%)"), "8");
    await user.type(screen.getByLabelText("트레일링 스탑(%)"), "12");

    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(await screen.findByText("저장했어요.")).toBeInTheDocument();
  });

  it("shows an inline error when the backend rejects the save (422)", async () => {
    const strategy = FIXTURE_STRATEGIES[0];
    server.use(
      http.patch(`/api/v1/strategies/${strategy.id}`, () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Unprocessable Entity",
            status: 422,
            detail: "config이 올바르지 않아요.",
          },
          { status: 422, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage(strategy.id);

    await screen.findByDisplayValue(strategy.name);
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(await screen.findByText("config이 올바르지 않아요.")).toBeInTheDocument();
  });

  it("blocks submission on an invalid ma_alignment pair with a client-side Zod error", async () => {
    const user = userEvent.setup();
    const strategy = FIXTURE_STRATEGIES[0];
    renderPage(strategy.id);

    await screen.findByDisplayValue(strategy.name);
    await user.type(screen.getByLabelText("단기 이동평균(일)"), "60");
    await user.type(screen.getByLabelText("장기 이동평균(일)"), "20");

    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(
      await screen.findByText("짧은 이동평균 기간이 긴 기간보다 작아야 해요."),
    ).toBeInTheDocument();
    expect(screen.queryByText("저장했어요.")).not.toBeInTheDocument();
  });
});
