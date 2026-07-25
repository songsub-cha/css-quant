# apps/web

프론트엔드. TypeScript 5 + Node 22 + pnpm 11, React 18 + Vite, React Router, TanStack Query v5, Zustand,
React Hook Form + Zod, Tailwind v4 (+shadcn/ui), Lightweight Charts + Recharts, vite-plugin-pwa
(SoT PART B5 확정 스택).

빌드된 SPA는 `apps/api`가 단일 오리진으로 직접 서빙한다 (SoT B1) — 별도 프론트 서버 없음, CORS 불필요.

프론트는 주문 결정에 개입하지 않는다 — 표시와 승인만 담당한다 (SoT A2, B1). 모바일은 Tailscale 경유 PWA로
대시보드 조회·긴급 정지·주문 후보 승인/거절을 지원해야 한다 (SoT A5.10).

## 현재 상태

**순수 스캐폴딩만 존재한다.** Vite + React 18 + TypeScript 5 + React Router + Tailwind v4가 부트스트랩되어
있고, 라우트는 `/` 하나에 콘텐츠 없는 placeholder 페이지만 붙어 있다 ("빌드되고 렌더링된다"만 증명).

다음은 아직 없다 — 모두 후속 이슈:

- 로그인 화면, 인증 상태 관리(TanStack Query v5 + Zustand), 보호 라우트, 실제 대시보드 콘텐츠
- shadcn/ui 컴포넌트 본격 도입, React Hook Form + Zod 폼 검증
- `vite-plugin-pwa` (Tailscale 접속 전제라 나중에)
- Testing Library / MSW / Playwright E2E
- `apps/api` prod Dockerfile이 이 빌드 산출물을 실제로 임베드하도록 하는 멀티스테이지 통합 (자리만 마련되어
  있음 — `FRONTEND_DIST`)

## 개발

Node 22 + pnpm 11 필요 (`corepack enable`로 활성화 가능).

```bash
pnpm install
pnpm dev      # 개발 서버 (기본 http://localhost:5173)
```

## 빌드

```bash
pnpm build    # tsc -b && vite build → dist/
```

기타: `pnpm lint`(ESLint), `pnpm typecheck`(`tsc -b --noEmit`).
