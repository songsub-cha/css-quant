import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import GlossaryPage from "./GlossaryPage";

function renderPage(initialEntry = "/glossary") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <GlossaryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GlossaryPage", () => {
  it("lists all fixture terms by default", async () => {
    renderPage();

    expect(await screen.findByText(/PER\(주가수익비율\)/)).toBeInTheDocument();
    expect(screen.getByText("모멘텀 팩터")).toBeInTheDocument();
    expect(screen.getByText("누적 손실 킬 스위치")).toBeInTheDocument();
  });

  it("filters the list by search term", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/PER\(주가수익비율\)/);

    await user.type(screen.getByPlaceholderText("용어 검색…"), "모멘텀");

    await waitFor(() => {
      expect(screen.queryByText(/PER\(주가수익비율\)/)).not.toBeInTheDocument();
    });
    expect(screen.getByText("모멘텀 팩터")).toBeInTheDocument();
  });

  it("filters the list by category", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/PER\(주가수익비율\)/);

    await user.selectOptions(screen.getByRole("combobox"), "risk");

    await waitFor(() => {
      expect(screen.queryByText(/PER\(주가수익비율\)/)).not.toBeInTheDocument();
    });
    expect(screen.getByText("누적 손실 킬 스위치")).toBeInTheDocument();
  });

  it("highlights the term named in the ?term= query param", async () => {
    renderPage("/glossary?term=kill_switch");

    const entry = await screen.findByText("누적 손실 킬 스위치");
    expect(entry.closest("li")).toHaveClass("border-sky-500");
  });

  it("shows an empty state when no term matches", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/PER\(주가수익비율\)/);

    await user.type(screen.getByPlaceholderText("용어 검색…"), "존재하지않는용어검색어");

    expect(await screen.findByText("일치하는 용어가 없어요.")).toBeInTheDocument();
  });
});
