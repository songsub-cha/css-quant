# 0004. fake-by-default 어댑터 패턴

- **날짜**: 2026-07-11
- **상태**: Accepted
- **관련**: SoT [PART E1](../SoT.md#e1-adr-새-저장소-docsadr에-재기록) #4, [B3](../SoT.md#b3-어댑터-스왑-fake-by-default), [A6.1](../SoT.md#a61-ai-종목-점수-파이프라인), [A6.8](../SoT.md#a68-모의투자)

## 맥락

시스템은 다수의 외부 연동(시세/재무 데이터 소스, LLM, 증권사 브로커)에 의존한다. 이런 연동은 API 키
발급, 네트워크 접근, 비용이 필요해 로컬 개발·CI·신규 기여자 온보딩을 무겁게 만든다. 또한 백테스트·모의투자
같은 핵심 도메인 로직은 외부 연동 없이도 결정론적으로 테스트 가능해야 한다 (B4.7 골든 테스트 요구사항).

## 결정

모든 외부 연동은 **Port 인터페이스(Protocol) 뒤에 두고 fake 구현을 기본값**으로 삼는다:

- `DATA_SOURCE` = `fake` | `krx`
- `LLM_ADAPTER` = `fake` | `openai`
- `BROKER_ADAPTER` = `fake` | `kis`

실구현을 추가할 때도 fake와 동일한 인터페이스 뒤에 두고, 같은 환경변수 분기 지점에서 선택한다.

## 결과

- **API 키 0개로 전체 앱이 구동**된다 — 신규 기여자, CI, 로컬 개발 모두 외부 계정 없이 전체 파이프라인을
  실행할 수 있다.
- `LLMClient` Protocol의 기본 구현은 `FakeLLMClient`이며, `OpenAILLMClient`/`AnthropicLLMClient`는
  같은 인터페이스의 대안 구현이다 (A6.1).
- `PaperBrokerAdapter`는 `BrokerAdapter` 인터페이스의 첫 구현체이며, 이후 `KISAdapter`도 동일 인터페이스
  뒤에 추가된다 (A6.8, A6.9) — 검증 사다리(내부 Paper → KIS 모의 서버 → 실계좌 승인형 → 제한적 자동)가
  이 패턴 위에서 성립한다.
- 어댑터 스왑은 배포 환경 변경만으로 이루어지며 서비스/도메인 레이어 코드 변경을 요구하지 않는다.
