# apps/web

프론트엔드. TypeScript 5 + Node 22 + pnpm 11, React 18 + Vite, React Router, TanStack Query v5, Zustand,
React Hook Form + Zod, Tailwind v4 (+shadcn/ui), Lightweight Charts + Recharts, vite-plugin-pwa
(SoT PART B5 확정 스택).

빌드된 SPA는 `apps/api`가 단일 오리진으로 직접 서빙한다 (SoT B1) — 별도 프론트 서버 없음, CORS 불필요.

프론트는 주문 결정에 개입하지 않는다 — 표시와 승인만 담당한다 (SoT A2, B1). 모바일은 Tailscale 경유 PWA로
대시보드 조회·긴급 정지·주문 후보 승인/거절을 지원해야 한다 (SoT A5.10).

## 현재 상태

디렉터리 placeholder만 존재한다. `package.json`, Vite 설정, API 클라이언트(자동 refresh 포함, SoT B5.7) 등
실제 부트스트랩은 후속 이슈에서 다룬다.
