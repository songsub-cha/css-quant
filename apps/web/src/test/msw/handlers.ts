import { http, HttpResponse } from "msw";

import type { GlossaryTerm } from "../../lib/glossary-api";

export const FIXTURE_TERMS: GlossaryTerm[] = [
  {
    key: "per",
    term_ko: "PER(주가수익비율)",
    term_en: "PER (Price-to-Earnings Ratio)",
    category: "financial_metric",
    definition: "주가를 주당순이익으로 나눈 값으로, 이익 대비 주가가 비싼지 싼지를 보여줘요.",
    interpretation: "낮을수록 이익 대비 저평가, 높을수록 고평가로 해석돼요.",
    caution: "낮은 PER이 실적 악화를 미리 반영한 '밸류 트랩'일 수 있어요.",
    in_system: "Value 팩터의 입력 지표 중 하나예요.",
    direction: "lower_is_better",
    related: ["value_factor"],
  },
  {
    key: "momentum_factor",
    term_ko: "모멘텀 팩터",
    term_en: "Momentum Factor",
    category: "factor",
    definition: "최근 일정 기간 동안 주가가 얼마나 올랐는지를 측정하는 지표예요.",
    interpretation: "백분위가 높을수록 최근 상승세가 강한 종목이에요.",
    caution: null,
    in_system: "AI 점수 5개 팩터 중 하나예요.",
    direction: "higher_is_better",
    related: [],
  },
  {
    key: "kill_switch",
    term_ko: "누적 손실 킬 스위치",
    term_en: "Cumulative Loss Kill Switch",
    category: "risk",
    definition: "포트폴리오 가치가 고점 대비 일정 비율 이상 떨어지면 전략을 자동으로 멈춰요.",
    interpretation: "큰 손실이 더 커지기 전에 자동으로 제동을 걸어요.",
    caution: null,
    in_system: "리스크 엔진의 자동 정지 조건 중 하나예요.",
    direction: "lower_is_better",
    related: [],
  },
];

export const handlers = [
  http.get("/api/v1/glossary", ({ request }) => {
    const url = new URL(request.url);
    const category = url.searchParams.get("category");
    const q = url.searchParams.get("q");

    let result = FIXTURE_TERMS;
    if (category) {
      result = result.filter((term) => term.category === category);
    }
    if (q) {
      const needle = q.toLowerCase();
      result = result.filter(
        (term) =>
          term.key.toLowerCase().includes(needle) ||
          term.term_ko.toLowerCase().includes(needle) ||
          term.term_en.toLowerCase().includes(needle) ||
          term.definition.toLowerCase().includes(needle),
      );
    }
    return HttpResponse.json(result);
  }),

  http.get("/api/v1/glossary/:key", ({ params }) => {
    const term = FIXTURE_TERMS.find((t) => t.key === params.key);
    if (!term) {
      return HttpResponse.json(
        {
          type: "about:blank",
          title: "Glossary Term Not Found",
          status: 404,
          detail: "Glossary term not found.",
          code: "GLOSSARY_TERM_NOT_FOUND",
        },
        { status: 404, headers: { "Content-Type": "application/problem+json" } },
      );
    }
    return HttpResponse.json(term);
  }),
];
