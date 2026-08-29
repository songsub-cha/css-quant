import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { server } from "../test/msw/server";
import RankingPage from "./RankingPage";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/rankings"]}>
        <RankingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RankingPage", () => {
  it("renders the scores response in the order it arrives, without re-sorting", async () => {
    renderPage();

    const rows = await screen.findAllByRole("button");
    expect(within(rows[0]).getByText(/삼성전자/)).toBeInTheDocument();
    expect(within(rows[0]).getByText("82.50")).toBeInTheDocument();
    expect(within(rows[0]).getByText("정상")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/SK하이닉스/)).toBeInTheDocument();
    expect(within(rows[1]).getByText("방어")).toBeInTheDocument();
  });

  it("expands a row to show sub-scores and score reasons", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click((await screen.findByText(/삼성전자/)).closest("button")!);

    expect(screen.getByText("모멘텀과 유동성이 강해요.")).toBeInTheDocument();
    expect(screen.getByText("최근 3개월 상승세가 뚜렷해요.")).toBeInTheDocument();
    expect(screen.getByText("밸류에이션이 다소 높아요.")).toBeInTheDocument();
    expect(screen.getByText("78.00")).toBeInTheDocument();
  });

  it('shows "설명 없음" when summary/positive_reasons/risk_reasons are all null', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click((await screen.findByText(/SK하이닉스/)).closest("button")!);

    expect(screen.getByText("설명 없음")).toBeInTheDocument();
  });

  it("shows a cold-start empty state when score_date is null", async () => {
    server.use(
      http.get("/api/v1/scores", () => HttpResponse.json({ score_date: null, scores: [] })),
    );
    renderPage();

    expect(
      await screen.findByText("아직 계산된 점수가 없어요. 점수 파이프라인이 처음 실행되면 이곳에 순위가 표시돼요."),
    ).toBeInTheDocument();
  });

  it("shows an inline error message and does not crash on API failure", async () => {
    server.use(
      http.get("/api/v1/scores", () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Internal Server Error",
            status: 500,
            detail: "점수를 불러오지 못했어요.",
          },
          { status: 500, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    renderPage();

    expect(await screen.findByText("점수를 불러오지 못했어요.")).toBeInTheDocument();
  });
});
