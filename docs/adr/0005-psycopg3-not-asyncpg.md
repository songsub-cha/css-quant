# 0005. psycopg 3 채택 (asyncpg 금지)

- **날짜**: 2026-07-11
- **상태**: Accepted
- **관련**: SoT [PART E1](../SoT.md#e1-adr-새-저장소-docsadr에-재기록) #5, [B5.1~B5.3](../SoT.md#b5-검증된-구현-결정-구-저장소에서-확인된-함정--반드시-승계)

## 맥락

구 저장소(`quant_ai`)는 초기에 asyncpg를 PostgreSQL 드라이버로 사용했으나, managed PostgreSQL의
SSL 설정과 asyncpg 사이의 호환성 문제가 실제로 발생해 드라이버를 교체한 이력이 있다. 새 저장소는 이
검증된 함정을 반복하지 않아야 한다.

## 결정

DB 드라이버는 **psycopg 3** (`postgresql+psycopg://`)를 사용한다. **asyncpg는 금지**한다.

## 결과

- SQLAlchemy 연결 문자열 설정(config)에는 `postgres://` / `postgresql://` / `+asyncpg`가 포함된 URL을
  `+psycopg`로 자동 재작성하는 validator를 둔다 — 환경변수 실수로 인한 드라이버 불일치를 방지한다
  (B5.1).
- Alembic 마이그레이션에서 enum 타입은 `sqlalchemy.dialects.postgresql`의
  `postgresql.ENUM(..., create_type=False)`를 사용한다. `sa.Enum(create_type=False)`는 psycopg
  방언에서 플래그가 소실되는 것이 실증되었으므로 사용하지 않는다. `CREATE TYPE`은 DO 블록으로 멱등하게
  작성한다 (B5.3).
- SAEnum 컬럼은 전부 `values_callable=lambda e: [x.value for x in e]`를 지정한다 — StrEnum 멤버 이름은
  대문자이지만 저장 값은 소문자이므로, 이 옵션이 없으면 잘못된 리터럴로 INSERT된다 (B5.2).
- Alembic은 앱의 async 엔진(`settings.DATABASE_URL` 기준)으로 실행하며, prod 이미지는 기동 시
  `alembic upgrade head` 후 uvicorn을 시작한다 (B5.5).
