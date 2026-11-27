# EduFlow 외부 연동 안내

[프로젝트 소개와 로컬 실행](../README.md)

## 안내 메일

신청이 접수되면 신청자가 고른 날짜의 한국 시간 오전 9시로 발송을 예약합니다.
연락 가능일을 바꾸면 대기 중인 예약을 교체하고, 신청을 완료하면 대기 예약을 취소합니다.
발송 실패 후 5분, 다시 실패하면 10분 뒤에 재시도합니다.

### Redis와 Celery 실행

Redis를 설치하고 [README의 웹 서버](../README.md#로컬에서-실행)를 실행합니다. Redis,
Worker, Beat는 한 컴퓨터에서 아래 명령을 각각 별도 터미널로 실행하면 됩니다.

```sh
# 터미널 1 · 메시지 큐
redis-server

# 터미널 2 · 예약 배치와 메일 발송 처리
pipenv run celery -A config worker --loglevel=INFO

# 터미널 3 · 매분 예약 확인
pipenv run celery -A config beat --loglevel=INFO
```

Redis가 이미 실행 중이면 `redis-cli ping`으로 `PONG`을 확인합니다. 기본 브로커는
`redis://127.0.0.1:6379/0`이며, 별도 Redis를 쓰면 Worker와 Beat에 동일한
`CELERY_BROKER_URL`을 설정합니다. Beat는 한 개만 실행합니다.

### 콘솔에서 메일 내용 확인

1. `.env`에서 `DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`를
   사용합니다. 샘플 설정의 기본값입니다.
2. 접수 가능한 교육에 `learner@example.com`과 오늘의 연락 가능일로 새 신청을 등록합니다.
3. 한국 시간 오전 9시 이후라면 다음 스캔에서 Worker 터미널에 메일 제목과 본문이
   출력됩니다. 오전 9시 전이면 오전 9시 이후 첫 스캔을 확인합니다.

예시 데이터의 `.invalid` 이메일은 실제 발송 대상에서 제외됩니다.

### 실제 메일로 발송 확인

1. 메일 제공자의 SMTP 발송 정보를 `.env`에 넣습니다. 아래는 포트 587과 STARTTLS를
   사용하는 제공자의 예시입니다.

   ```dotenv
   DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
   DJANGO_EMAIL_HOST=smtp.example.com
   DJANGO_EMAIL_PORT=587
   DJANGO_EMAIL_USE_TLS=1
   DJANGO_EMAIL_USE_SSL=0
   DJANGO_EMAIL_HOST_USER=sender@example.com
   DJANGO_EMAIL_HOST_PASSWORD='SMTP 앱 비밀번호'
   DJANGO_DEFAULT_FROM_EMAIL=sender@example.com
   ```

   `DJANGO_EMAIL_HOST_USER`는 SMTP 로그인 계정이고 `DJANGO_DEFAULT_FROM_EMAIL`은 받는
   사람에게 표시할 발신 주소입니다. 비밀번호에 `#`나 공백이 있으면 값 전체를
   작은따옴표로 감쌉니다.

   네이버는 POP3/SMTP 사용과 2단계 인증을 켜고 애플리케이션 비밀번호를 발급합니다.
   `DJANGO_EMAIL_HOST=smtp.naver.com`, `DJANGO_EMAIL_PORT=465`,
   `DJANGO_EMAIL_USE_SSL=1`, `DJANGO_EMAIL_USE_TLS=0`을 설정합니다.
   [네이버 SMTP 설정 안내](https://help.naver.com/service/30029/contents/21341?lang=ko&osType=PC)
2. Worker를 재시작하고 본인 이메일과 오늘 날짜로 새 신청을 등록합니다. 콘솔에서
   이미 확인한 건도 발송 완료로 기록되므로 실제 발송 테스트에는 새 신청을 사용합니다.
3. 운영자의 **메일 발송 내역**에서 발송 시각과 실패 시 다음 시도를 확인합니다. 실제
   도착 여부는 받은편지함에서 확인합니다.

화면의 `발송 완료`는 백엔드가 발송 요청을 받아들인 상태입니다. 백엔드 수락 직후
Worker가 중단되면 재시도 때 같은 메일이 중복 발송될 수 있습니다.

## Google Sheets 내보내기

1. Google Cloud 프로젝트에서 Google Sheets API를 활성화하고 서비스 계정을 만든 뒤
   로컬 개발용 JSON 키를 프로젝트 밖에 저장합니다.
   [Google 서비스 계정 설정](https://developers.google.com/workspace/guides/create-credentials#create_a_service_account)
2. 대상 스프레드시트를 서비스 계정 이메일에 **편집자**로 공유합니다. 문서 URL의
   `/d/`와 `/edit` 사이 값을 문서 ID로 사용합니다.
3. `.env`에 아래 값을 넣고 Django 웹 서버를 다시 시작합니다.

   ```dotenv
   GOOGLE_SHEETS_SPREADSHEET_ID=스프레드시트_ID
   GOOGLE_APPLICATION_CREDENTIALS='/absolute/path/to/service-account.json'
   ```

4. 운영자 **신청목록**에서 필터를 적용한 뒤 **Google Sheets로 내보내기**를 누릅니다.
   슈퍼유저 또는 신청 조회와 내보내기 권한이 있는 직원이 실행할 수 있습니다.
5. 완료 메시지의 **Google Sheets 열기** 링크에서 새 탭을 확인합니다.

한 번에 최대 500건이 저장되며, 열은 운영자 신청목록과 동일합니다. 시각은 한국 시간으로
기록합니다. 이름과 이메일이 포함되므로 공유 범위를 운영자에 맞춰 설정합니다.
