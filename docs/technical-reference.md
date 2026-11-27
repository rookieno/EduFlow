# EduFlow 기술 참고

[프로젝트 소개와 로컬 실행](../README.md)

## API

API 접두사는 `/api/v1/`입니다. 날짜 입력 형식은 `YYYY-MM-DD`입니다.

| 메서드·경로 | 기능 |
| --- | --- |
| `GET /api/v1/courses/` | 공개 교육 목록 |
| `GET /api/v1/courses/<slug>/` | 교육 상세와 접수 상태 |
| `POST /api/v1/applications/` | 공개 신청 접수. `course_slug`, `submission_id`(UUID), `name`, `email`, `address`, `contact_date`를 받습니다. |
| `GET /api/v1/applications/` | 운영자용 신청 목록. 이름·이메일·주소를 포함하지 않습니다. |
| `GET /api/v1/applications/staff-results/` | 이름·이메일을 포함하는 운영자용 검색 결과 |
| `GET /api/v1/applications/summary/` | 대시보드 신청 상태별 건수 |
| `POST /api/v1/applications/staff-create/` | 운영자 신청 등록 |
| `GET`, `PATCH`, `DELETE /api/v1/applications/<uuid>/` | 신청 상세 조회·수정·삭제 |
| `GET /api/v1/courses/staff-choices/` | 운영자 필터용 교육 선택지 |
| `GET /api/v1/applications/reminders/` | 메일 발송 내역 목록 |
| `GET /api/v1/applications/reminders/<uuid>/` | 메일 발송 내역 상세 |
| `POST /api/v1/applications/export/` | Google Sheets 내보내기. 응답은 `count`와 `sheet_url`을 포함합니다. |
| `GET /api/v1/session/` | 브라우저 CSRF 토큰 및 신청 관련 작업 권한 |
| `POST /api/v1/session/login/`, `POST /api/v1/session/logout/` | 브라우저 세션 로그인·로그아웃 |

신청 목록과 내보내기는 `q`(접수번호·이름·이메일), `course`(슬러그),
`status`, `contact_date_from`, `contact_date_to`를 받습니다. 날짜 범위는 양 끝을
포함하며 한 쪽만 입력해도 검색됩니다. 메일 발송 내역은 `status`와 해당 신청의
접수번호·이름·현재 이메일을 찾는 `q`를 지원합니다.

브라우저는 세션 인증을 사용하며 쓰기 요청 시 CSRF 토큰을 보냅니다. 운영자 API는
직원 계정과 `applications.view_application` 권한을 검사합니다. 등록·수정·삭제는
각 작업의 Django 권한을 추가로 검사합니다. 메일 발송 내역에는
`applications.view_applicationreminder`, 내보내기에는 `applications.export_application`
권한이 추가로 필요합니다.

외부 API 클라이언트는 `pipenv run python manage.py drf_create_token <사용자이름>`으로
발급한 토큰을 `Authorization: Token <토큰>` 헤더에 보냅니다. 브라우저에서 다른
출처로 API에 접근할 경우 `EDUFLOW_CORS_ALLOWED_ORIGINS`에 허용 출처를 쉼표로 구분해
지정합니다. 외부 출처에서 공개 신청을 보낼 때는 쿠키 없이 호출합니다.

## 데이터와 실행 환경

- `POSTGRES_DB`의 기본값은 `eduflow`입니다. `POSTGRES_HOST`와 `POSTGRES_USER`를
  비우면 로컬 PostgreSQL 소켓과 현재 OS 계정을 사용합니다. 별도 호스트에 연결할 때는
  `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`를 설정합니다.
- `Application.objects.submit(...)`은 교육 행을 잠근 뒤 마감과 정원을 확인합니다.
  최초 요청과 같은 식별자·입력으로 다시 요청하면 기존 신청을 돌려주며, 같은 식별자로
  다른 내용을 제출하면 충돌을 알립니다.
- 운영자가 신청 상태를 완료로 바꾼 시각은 별도로 기록합니다. 완료 상태에서 다른 정보만
  수정하면 기존 완료 시각을 유지합니다.
- `pipenv run python manage.py seed_demo --reset`은 기존 예시 신청과 연결된 메일 이력을
  지우고 예시 데이터를 재생성합니다. 일반 신청은 보존합니다.
- pytest는 별도의 PostgreSQL 테스트 DB를 생성하므로 테스트 계정에 DB 생성 권한이
  필요합니다.
