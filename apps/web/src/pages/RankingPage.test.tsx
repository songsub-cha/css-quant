import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { ScoreRankingItem } from "../lib/scores-api";
import { FIXTURE_SCORE_DATE } from "../test/msw/handlers";
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

// Arrival order (Alpha, Beta, Gamma) differs from both the ascending
// (Alpha, Gamma, Beta) and descending (Beta, Gamma, Alpha) total_score
// orderings, so rendering any re-sorted order is distinguishable from
// rendering arrival order — unlike the old fixture, which was already in
// descending order and couldn't tell "no re-sort" apart from "desc re-sort".
const SHUFFLED_SCORES: ScoreRankingItem[] = [
  {
    asset_id: "ast_00000000-0000-7000-8000-000000000101",
    ticker: "AAA",
    name: "Alpha",
    regime: "NORMAL",
    total_score: "50.00",
    momentum_score: "50.00",
    quality_score: "50.00",
    value_score: "50.00",
    liquidity_score: "50.00",
    risk_score: "50.00",
    summary: null,
    positive_reasons: null,
    risk_reasons: null,
  },
  {
    asset_id: "ast_00000000-0000-7000-8000-000000000102",
    ticker: "BBB",
    name: "Beta",
    regime: "NORMAL",
    total_score: "90.00",
    momentum_score: "90.00",
    quality_score: "90.00",
    value_score: "90.00",
    liquidity_score: "90.00",
    risk_score: "90.00",
    summary: null,
    positive_reasons: null,
    risk_reasons: null,
  },
  {
    asset_id: "ast_00000000-0000-7000-8000-000000000103",
    ticker: "CCC",
    name: "Gamma",
    regime: "DEFENSIVE",
    total_score: "70.00",
    momentum_score: "70.00",
    quality_score: "70.00",
    value_score: "70.00",
    liquidity_score: "70.00",
    risk_score: "70.00",
    summary: null,
    positive_reasons: null,
    risk_reasons: null,
  },
];

describe("RankingPage", () => {
  it("renders the scores response in the order it arrives, without re-sorting", async () => {
    server.use(
      http.get("/api/v1/scores", () =>
        HttpResponse.json({ score_date: FIXTURE_SCORE_DATE, scores: SHUFFLED_SCORES }),
      ),
    );
    renderPage();

    const rows = await screen.findAllByRole("listitem");
    expect(within(rows[0]).getByText(/Alpha/)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Beta/)).toBeInTheDocument();
    expect(within(rows[2]).getByText(/Gamma/)).toBeInTheDocument();
  });

  it("wires glossary term help for sub-score labels, total score, and regime badge", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "82.50" }));
    expect(await screen.findByText("AI 종합 점수")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "정상" }));
    expect(await screen.findByText("시장 레짐")).toBeInTheDocument();

    await user.click((await screen.findByText(/삼성전자/)).closest("button")!);
    await user.click(screen.getByRole("button", { name: "모멘텀" }));
    expect(await screen.findByText("모멘텀 팩터")).toBeInTheDocument();
  });

  it("shows an empty-state message when score_date is set but there are no scores", async () => {
    server.use(
      http.get("/api/v1/scores", () => HttpResponse.json({ score_date: FIXTURE_SCORE_DATE, scores: [] })),
    );
    renderPage();

    expect(await screen.findByText("점수는 계산됐지만 표시할 종목이 없어요.")).toBeInTheDocument();
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
