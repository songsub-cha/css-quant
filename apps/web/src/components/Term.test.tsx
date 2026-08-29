import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import Term from "./Term";

function renderTerm(termKey: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Term termKey={termKey}>PER</Term>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Term", () => {
  it("opens on click and shows definition, interpretation, and caution", async () => {
    const user = userEvent.setup();
    renderTerm("per");

    await user.click(screen.getByRole("button", { name: "PER" }));

    expect(await screen.findByText(/이익 대비 주가가 비싼지 싼지/)).toBeInTheDocument();
    expect(screen.getByText(/낮을수록 이익 대비 저평가/)).toBeInTheDocument();
    expect(screen.getByText(/밸류 트랩/)).toBeInTheDocument();
  });

  it("closes when the trigger is clicked again", async () => {
    const user = userEvent.setup();
    renderTerm("per");

    const trigger = screen.getByRole("button", { name: "PER" });
    await user.click(trigger);
    await screen.findByRole("tooltip");

    await user.click(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("closes when clicking outside the popover", async () => {
    const user = userEvent.setup();
    renderTerm("per");

    await user.click(screen.getByRole("button", { name: "PER" }));
    await screen.findByRole("tooltip");

    await user.click(document.body);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    renderTerm("per");

    await user.click(screen.getByRole("button", { name: "PER" }));
    await screen.findByRole("tooltip");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("links to the glossary page for more detail", async () => {
    const user = userEvent.setup();
    renderTerm("per");

    await user.click(screen.getByRole("button", { name: "PER" }));
    const link = await screen.findByRole("link", { name: "용어집에서 더 보기" });
    expect(link).toHaveAttribute("href", "/glossary?term=per");
  });

  it("shows a not-found message for an unknown term key", async () => {
    const user = userEvent.setup();
    renderTerm("nonexistent_key");

    await user.click(screen.getByRole("button", { name: "PER" }));
    expect(await screen.findByText("이 용어의 설명을 찾을 수 없어요.")).toBeInTheDocument();
  });
});
