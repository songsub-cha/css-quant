# 0006. 로컬 셀프호스팅 전환 (Mac mini M4 + Docker + Tailscale)

- **날짜**: 2026-07-11
- **상태**: Accepted
- **관련**: SoT [PART E1](../SoT.md#e1-adr-새-저장소-docsadr에-재기록) #6, [A3](../SoT.md#a3-운영-모델-확정), [PART D](../SoT.md#part-d--운영-mac-mini-셀프호스팅)

## 맥락

시스템은 브로커 API 키 등 민감한 자격 증명을 보관하는 **단일 사용자(오너)** 전용 애플리케이션이다.
구 저장소(`quant_ai`)는 클라우드 PaaS(Render/Neon/Upstash)에 배포되었으나, 상시 가동을 위한
항상성 비용, 무료 티어의 슬립(sleep) 동작, 그리고 민감 키를 제3자 관리형 인프라에 보관해야 하는
문제가 있었다.

## 결정

**Mac mini M4에서 Docker Compose로 셀프호스팅**하고, **Tailscale HTTPS**로 접속한다. 클라우드 PaaS
배포는 폐기한다.

## 결과

이 결정은 A3(운영 모델)의 파생 결정 전체의 근거가 된다:

- 사용자 모델이 **단일 사용자(오너)**로 확정되고, 멀티유저 SaaS는 비목표(A4)가 된다.
- 회원가입은 최초 오너 계정 부트스트랩 후 비활성화(`SIGNUP_ENABLED=false` 기본)되고, admin 역할은
  오너 계정에 통합된다.
- Tailscale이 유효한 HTTPS 인증서를 자동 발급하므로 Secure 쿠키, PWA 설치, 웹 푸시, Google OAuth
  redirect URI 등록이 모두 성립한다 (D3). **인터넷 포트 개방(공유기 포트포워딩)은 금지**한다 — 브로커
  키를 보관하는 시스템이기 때문이다.
- macOS 상시 운영을 위해 절전 해제(`pmset -a sleep 0`), 컨테이너 런타임 자동 시작(OrbStack 또는
  colima), macOS 자동 로그인이 필요하다 — 정전/재부팅 후 사람 개입 없이 복구되는 체인을 구성한다 (D4).
- `postgres`/`redis`/`api`/`worker` 4개 서비스로 구성된 prod Docker Compose가 필요하며, `worker`
  누락은 구 구현에서 실제로 발생한 사고 지점이다 (D1).
- DB 백업은 클라우드 관리형 백업이 아닌 `pg_dump` + 오프박스 복사로 직접 운영해야 한다 (D5).
- 2FA(TOTP)는 "실거래 전 필수"에서 "실거래 전 권장"으로 하향된다 — tailnet 자체가 1차 방벽이 되기
  때문이다.
