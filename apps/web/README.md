# apps/web

프론트엔드. TypeScript 5 + Node 22 + pnpm 11, React 18 + Vite, React Router, TanStack Query v5, Zustand,
React Hook Form + Zod, Tailwind v4 (+shadcn/ui), Lightweight Charts + Recharts, vite-plugin-pwa
(SoT PART B5 확정 스택).

빌드된 SPA는 `apps/api`가 단일 오리진으로 직접 서빙한다 (SoT B1) — 별도 프론트 서버 없음, CORS 불필요.

프론트는 주문 결정에 개입하지 않는다 — 표시와 승인만 담당한다 (SoT A2, B1). 모바일은 Tailscale 경유 PWA로
대시보드 조회·긴급 정지·주문 후보 승인/거절을 지원해야 한다 (SoT A5.10).

## 현재 상태

인증 루프(로그인 → 보호 라우트 → 빈 대시보드 → 로그아웃)까지 붙어 있다. Vite + React 18 + TypeScript 5 +
React Router + Tailwind v4 위에 TanStack Query v5 + Zustand(파생 인증 스토어) + React Hook Form + Zod가
배선되었다:

- `GET /api/v1/auth/me`를 TanStack Query가 소유하고(`src/hooks/useMeQuery.ts`), 그 결과를 Zustand
  스토어(`src/stores/auth-store.ts`)에 반영한다. 라우트 가드가 렌더링 중 동기적으로 읽을 값이 필요해서다 —
  스토어는 쿼리 캐시의 파생값일 뿐, 갱신은 `useMeQuery` 한 곳에서만 일어난다.
- `/login`(공개, `src/pages/LoginPage.tsx`)과 `/`(보호됨, `src/components/ProtectedRoute.tsx` 뒤의
  `src/pages/DashboardPage.tsx`) 두 라우트만 있다. 대시보드는 로그인한 이메일 표시 + 로그아웃 버튼뿐인
  "빈" 화면이다(SoT A8 Phase 1 완료 기준).
- 개발 서버(`vite.config.ts`)는 `/api`를 백엔드(`VITE_API_PROXY_TARGET`, 기본
  `http://localhost:8000`)로 프록시한다 — httpOnly 쿠키 기반 인증이 동일 오리진에서 그대로 동작하게 하기
  위함이며, 백엔드에 CORS를 여는 대신 이 방식을 택했다(SoT B1의 prod 단일 오리진 서빙과 정책 일관).

다음은 아직 없다 — 모두 후속 이슈:

- 회원가입 화면(가입은 부트스트랩 이후 비활성, SoT A3), 비밀번호 재설정 화면(백엔드는 완료, UI만 없음),
  온보딩 체크리스트
- shadcn/ui 컴포넌트 본격 도입(현재는 Tailwind 유틸리티 클래스만 사용)
- Refresh 토큰 자동 갱신(백엔드에 `/auth/refresh` 엔드포인트 자체가 아직 없음)
- `packages/api-types` OpenAPI 코드젠 연동(현재는 수동 타입 정의, `src/lib/auth-api.ts`)
- `vite-plugin-pwa` (Tailscale 접속 전제라 나중에)
- Testing Library / MSW / Playwright E2E
- `apps/api` prod Dockerfile이 이 빌드 산출물을 실제로 임베드하도록 하는 멀티스테이지 통합 (자리만 마련되어
  있음 — `FRONTEND_DIST`)

## 개발

Node 22 + pnpm 11 필요 (`corepack enable`로 활성화 가능).

```bash
pnpm install
cp .env.example .env   # 필요 시 VITE_API_PROXY_TARGET 조정
pnpm dev      # 개발 서버 (기본 http://localhost:5173, /api는 백엔드로 프록시)
```

백엔드(`apps/api`)를 `http://localhost:8000`에서 별도로 띄워 두어야 로그인 등 인증 흐름이 동작한다
(`infra/docker-compose.dev.yml` 또는 `uv run uvicorn src.main:app --reload` — `apps/api` 쪽 안내 참고).

## 빌드

```bash
pnpm build    # tsc -b && vite build → dist/
```

기타: `pnpm lint`(ESLint), `pnpm typecheck`(`tsc -b --noEmit`).

## 운영자 수동 브라우저 확인 (로그인 → 대시보드 → 로그아웃)

이 환경에는 브라우저가 없어 `pnpm build`/`typecheck`/`lint` + 코드 리뷰로만 검증했다. PR을 머지하기 전,
실제 브라우저로 아래 흐름을 한 번 확인한다:

1. 백엔드를 띄운다 (최초 1회, 오너 계정이 아직 없다면): 백엔드 `.env`에서 `SIGNUP_ENABLED=true`로 잠시
   바꾼 뒤 기동하고,
   ```bash
   curl -i -X POST http://localhost:8000/api/v1/auth/bootstrap \
     -H "Content-Type: application/json" \
     -d '{"email":"owner@example.com","password":"a-strong-password"}'
   ```
   로 오너 계정을 만든 다음 `SIGNUP_ENABLED=false`로 되돌리고 백엔드를 재기동한다(SoT A3 — 가입은 부트스트랩
   1회만 허용).
2. `apps/web`에서 `pnpm dev`로 프론트 개발 서버를 띄우고 브라우저로 `http://localhost:5173/`을 연다.
   - **미인증 리다이렉트**: 쿠키가 없는 상태이므로 `/login`으로 자동 리다이렉트되어야 한다.
3. 방금 만든 이메일/비밀번호로 로그인 폼을 제출한다.
   - **로그인 성공**: 대시보드(`/`)로 이동하고 로그인한 이메일이 화면에 보여야 한다.
   - **로그인 실패**: 일부러 틀린 비밀번호로 한 번 더 시도해 에러 메시지("Invalid email or password.")가
     폼에 표시되는지 확인한다.
4. 브라우저를 새로고침한다 — 쿠키가 남아 있으므로 로그인 화면으로 튕기지 않고 대시보드가 다시 렌더링되어야
   한다(`GET /auth/me`가 쿠키로 인증됨을 확인).
5. 로그아웃 버튼을 누른다.
   - **로그아웃**: `/login`으로 이동하고, 다시 `/`로 직접 이동을 시도하면 재차 `/login`으로 리다이렉트되어야
     한다(쿠키가 지워졌는지 브라우저 개발자 도구의 Application → Cookies에서 `at`/`rt`가 사라졌는지도 확인
     가능).
