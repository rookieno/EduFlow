# EduFlow AWS 배포 구성

[프로젝트 소개](../README.md) · [AWS 사용 계획](aws-usage-plan.md)

이 문서는 운영 배포의 설정값과 적용 순서를 정의합니다. 현재 저장소의 설정은 로컬 개발용입니다.
AWS에서 실행하려면 먼저 아래의 컨테이너 및 운영 설정을 구현하고 검증 환경에서 확인합니다.

## 1. 이미지와 Django 운영 설정

| 항목 | 운영에서 적용할 구성 |
| --- | --- |
| 이미지 | Python 3.12 기반 Linux 이미지에 `Pipfile.lock`의 운영 의존성을 설치합니다. Gunicorn과 WhiteNoise를 운영 의존성으로 추가한 뒤 잠금 파일을 갱신합니다. `.dockerignore`에는 `.env`, 서비스 계정 키, 가상환경, Git 메타데이터를 포함합니다. 이미지 실행 계정은 비루트로 둡니다. |
| 진입점 | `config/wsgi.py`와 `config/settings_production.py`를 추가합니다. ECS에서 `DJANGO_SETTINGS_MODULE=config.settings_production`을 명시해 Django와 Celery가 같은 설정을 읽게 합니다. |
| HTTPS와 세션 | 운영 호스트를 `ALLOWED_HOSTS`에 지정하고, 실제 HTTPS 주소를 `CSRF_TRUSTED_ORIGINS`에 지정합니다. `DEBUG=False`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`를 사용합니다. ALB가 전달하는 `X-Forwarded-Proto`를 `SECURE_PROXY_SSL_HEADER`로 처리하고, ALB의 HTTP 리디렉션과 Django의 `SECURE_SSL_REDIRECT=True`를 함께 사용합니다. HTTPS 동작을 검증한 뒤 운영에 HSTS를 적용합니다. |
| 정적 파일 | `STATIC_ROOT`를 설정하고 이미지 빌드 중 `collectstatic --noinput`을 실행합니다. 빌드 전용 Django 설정을 사용해 운영 비밀을 이미지에 넣지 않습니다. WhiteNoise를 SecurityMiddleware 바로 뒤에 등록하고, 같은 오리진의 `/static/`에서 제공합니다. JavaScript가 `/static/api.js`를 직접 import하므로 해시가 없는 경로도 제공합니다. |
| 상태 점검 | ALB의 `GET /healthz/`는 웹 프로세스만 확인하고 정보를 담지 않은 HTTP 200을 반환합니다. ALB 상태 확인의 Host 헤더가 대상 사설 IP일 수 있으므로, 지정된 경로에만 적용되는 WSGI 상태 응답으로 구현합니다. 별도의 스모크 테스트에서 교육 조회 API로 DB 연결과 정적 파일 로드를 확인합니다. |
| 데이터베이스 | RDS CA 번들을 이미지에 포함하고 `DATABASES["default"]["OPTIONS"]`에 `sslmode=verify-full`과 `sslrootcert` 경로를 설정합니다. 런타임 DB 계정과 스키마 변경용 계정을 분리하고 필요한 권한만 부여합니다. |

[장고 배포 체크리스트](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/) · [ALB 상태 확인의 Host 헤더](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-troubleshooting.html) · [RDS PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html)

## 2. ECS 서비스와 네트워크

같은 ECR 이미지 digest를 각 Task Definition에 지정합니다. 운영 초기 CPU·메모리는
다음 값에서 시작하고, 실제 처리량과 연결 수에 맞춰 조정합니다.

| Task | 시작 규모 | 실행 명령 | 배포 방식 |
| --- | --- | --- | --- |
| `eduflow-web` | 0.5 vCPU / 1 GiB × 2 | `gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 50` | ALB 연결. 롤링 배포, 최소 100%·최대 200%. 상태 확인에 실패하면 이전 정상 배포로 롤백합니다. |
| `eduflow-jobs` | 0.5 vCPU / 1 GiB × 1 | Worker와 Beat를 같은 Task의 두 컨테이너로 실행합니다. | ALB 없이 실행합니다. 최소 0%·최대 100%로 이전 Task를 먼저 종료합니다. |
| `eduflow-migrate` | 0.25 vCPU / 0.5 GiB × 1 | `python manage.py migrate --noinput` | 배포 시 한 번 실행합니다. 종료 코드 0을 확인한 뒤 서비스를 갱신합니다. |

`eduflow-jobs`의 두 컨테이너는 같은 이미지를 쓰고 실행 명령을 각각 지정합니다.

| 컨테이너 | 실행 명령과 옵션 |
| --- | --- |
| `worker` | `celery -A config worker --loglevel=INFO --concurrency=1`. 실행 중인 작업을 마치도록 종료 유예를 90초로 설정합니다. |
| `beat` | `celery -A config beat --loglevel=INFO --schedule /tmp/eduflow-beat-schedule`. 매분 예약 확인 작업을 큐에 등록합니다. |

두 컨테이너를 필수(`essential: true`)로 설정합니다. 하나가 종료되면 ECS 서비스가
Task 전체를 교체합니다. Celery 스케줄러는 한 개로 유지하며, Worker와 Beat를 각각
실행합니다. [Fargate 컨테이너 설정](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html) · [Celery 주기 작업](https://docs.celeryq.dev/en/latest/userguide/periodic-tasks.html)

- Fargate의 네트워크 모드는 `awsvpc`로 설정합니다. ECS Task는 공개 IP 없이 사설 앱
  서브넷에서 실행합니다. 두 가용 영역의 공개 서브넷에 배치된 ALB가 HTTPS 443 연결을
  종료하고, 사설 웹 Task의 HTTP 8000으로 전달합니다. HTTP 80 요청은 HTTPS로 전환합니다. ALB 대상
  그룹은 `ip` 유형이고, ALB 유휴 제한 시간은 초기 60초로 설정합니다.
- 웹의 포트 8000은 ALB 보안 그룹에서만 열고, RDS 5432는 웹·메일 처리·마이그레이션
  Task 보안 그룹에서만 허용합니다. ElastiCache 6379는 메일 처리 Task 보안 그룹에서만
  허용합니다. 같은 Task의 Worker와 Beat는 보안 그룹을 공유합니다. DB와 브로커에는
  공개 인터넷 경로를 두지 않습니다.
- 앱 서브넷의 NAT 경로는 웹의 Google API HTTPS 연결, Worker의 SES SMTP 587 연결,
  이미지 다운로드와 AWS 서비스 호출에 사용합니다. 사용량이 늘면 ECR·S3·CloudWatch·
  Secrets Manager용 VPC 엔드포인트 도입과 NAT 비용을 비교합니다. Google API에는
  별도의 외부 송신 경로를 유지합니다.
- ElastiCache는 노드 기반, 클러스터 모드 비활성화, 전송 암호화와 인증을 사용합니다.
  읽기/쓰기 기본 엔드포인트로 연결합니다. 태스크 수를 늘리기 전에 Valkey TLS 연결과
  Celery 작업 송수신을 검증합니다.
- 메일 처리 서비스의 실행 개수를 1로 고정합니다. 기존 Task를 중지한 뒤 새 Task로
  교체해 Beat가 동시에 두 개 실행되지 않게 합니다. 교체 중 예약 확인과 발송은 잠시
  중단될 수 있으며, 새 Task가 DB에 남은 도래 예약을 다시 확인하는지 테스트합니다.
  독립 확장이 필요해지면 Worker 전용 서비스를 분리합니다.

[Fargate Task 정의](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html) · [ECS 롤링 배포](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-ecs.html) · [ElastiCache 전송 암호화](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/in-transit-encryption.html)

## 3. 환경 변수와 비밀 관리

| 변수 또는 값 | 적용 대상 | 설정 |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE`, `DJANGO_DEBUG`, `EDUFLOW_PUBLIC_HOST` | 전체 | `config.settings_production`, `0`, 서비스 도메인. `EDUFLOW_PUBLIC_HOST`는 운영 설정에서 읽도록 추가합니다. |
| `DJANGO_SECRET_KEY` | 전체 | Secrets Manager의 운영 전용 키를 사용합니다. 웹 Task들은 같은 키를 써서 동일한 세션을 검증합니다. |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | 웹·Worker·마이그레이션 | RDS 엔드포인트, `5432`, `eduflow`. |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | 웹·Worker·마이그레이션 | Secrets Manager에서 주입합니다. 마이그레이션 Task만 스키마 변경 계정을 사용합니다. |
| `CELERY_BROKER_URL` | Worker·Beat | Secrets Manager에 `rediss://:<암호>@<기본 엔드포인트>:6379/0?ssl_cert_reqs=required&ssl_check_hostname=true` 형태로 저장합니다. 비밀번호의 특수 문자는 URL 인코딩합니다. |
| SMTP 설정 | Worker | `DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `DJANGO_EMAIL_HOST=email-smtp.ap-northeast-2.amazonaws.com`, `DJANGO_EMAIL_PORT=587`, `DJANGO_EMAIL_USE_TLS=1`, `DJANGO_EMAIL_USE_SSL=0`. SES SMTP 전용 계정과 비밀번호는 비밀로 주입하고 `DJANGO_DEFAULT_FROM_EMAIL`에는 검증된 발신 주소를 넣습니다. |
| Google Sheets 설정 | 웹 | `GOOGLE_SHEETS_SPREADSHEET_ID`는 대상 문서 ID입니다. 서비스 계정 JSON을 Secrets Manager에 보관하고 초기화 컨테이너가 전용 임시 볼륨에 파일로 기록합니다. 웹 Task는 이 볼륨을 읽기 전용으로 마운트하고 `GOOGLE_APPLICATION_CREDENTIALS`에 경로를 설정합니다. |

태스크 실행 역할은 ECR에서 이미지를 내려받고 CloudWatch에 로그를 쓸 수 있게 합니다.
환경 변수로 주입하는 비밀은 실행 역할에 해당 ARN만 허용합니다. Google 키를 런타임에
가져오는 초기화 컨테이너에는 웹 Task 역할을 사용합니다. 같은 웹 Task의 컨테이너가
이 역할을 공유하므로 해당 JSON 비밀 읽기 권한만 부여합니다. 키 파일 읽기는 웹 실행
계정에 제한합니다. 비밀이 교체되면 관련 서비스의 Task를
재배포해 새 값을 받도록 합니다. [ECS Secrets Manager 환경 변수 주입](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html)

SES 초기 검증은 검증된 발신·수신 주소나 메일박스 시뮬레이터로 진행합니다. 일반
신청자에게 보내려면 서울 리전에서 SES 프로덕션 접근 권한을 받고, 도메인 검증과 DKIM을
완료합니다. [SES 프로덕션 접근](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html) · [SES SMTP 엔드포인트](https://docs.aws.amazon.com/general/latest/gr/ses.html)

## 4. 배포 순서

1. VPC, 서브넷, 보안 그룹, DNS·인증서, ALB, RDS, ElastiCache, ECR, 로그 그룹,
   Secrets Manager와 IAM 역할을 생성합니다. 검증 환경과 운영 환경의 리소스를 분리합니다.
2. PostgreSQL을 사용하는 CI에서 `pytest`와 Django 운영 설정의
   `python manage.py check --deploy`를 실행합니다. 컨테이너를 빌드하고 ECR에 푸시한
   뒤 동일 이미지 digest로 각 Task Definition의 새 리비전을 등록합니다.
3. 마이그레이션 Task를 사설 앱 서브넷에서 한 번 실행합니다. CI 배포 동시 실행을 막고,
   완료 및 종료 코드 0을 확인할 때까지 기존 서비스를 유지합니다.
4. 웹 서비스의 안정 상태와 Task 리비전을 확인한 뒤 메일 처리 서비스를 갱신합니다.
   Worker와 Beat를 함께 교체하므로 메일 처리는 잠시 중단될 수 있습니다. 서로 다른
   코드 버전이 잠시 공존하므로 DB 변경과 작업 이름·인자 형식은 초기
   배포에서 호환되게 유지합니다. 스키마 제거는 새 버전이 안정화된 뒤 별도로 적용합니다.
5. HTTPS 웹과 정적 파일, 접수·검색·권한, 안내 예약 및 처리, Google Sheets 내보내기를
   검증 환경에서 스모크 테스트합니다. 운영 전환 시 DB 초기화와 테스트 데이터 삽입을
   서로 분리하고 `seed_demo`는 검증 환경에서만 실행합니다.

### AWS CLI 배포 예시

AWS 리소스와 이미지의 Task Definition을 등록한 뒤 실행하는 예시입니다.
`ECS_CLUSTER`와 `*_TASK_DEF`에는 클러스터 이름과 해당 배포의 Task Definition ARN을,
`MIGRATION_NETWORK_JSON`에는 사설 서브넷·보안 그룹과 `assignPublicIp=DISABLED`를 포함한
`awsvpcConfiguration` JSON을 전달합니다. 마이그레이션 컨테이너 이름은 `app`으로 등록합니다.

```sh
set -eu
export AWS_REGION=ap-northeast-2

migration_arn=$(aws ecs run-task --cluster "$ECS_CLUSTER" \
    --task-definition "$MIGRATION_TASK_DEF" --launch-type FARGATE \
    --network-configuration "$MIGRATION_NETWORK_JSON" \
    --query 'tasks[0].taskArn' --output text)
if [ -z "$migration_arn" ] || [ "$migration_arn" = None ]; then
    echo 'Could not start the migration task' >&2
    exit 1
fi
aws ecs wait tasks-stopped --cluster "$ECS_CLUSTER" --tasks "$migration_arn"
exit_code=$(aws ecs describe-tasks --cluster "$ECS_CLUSTER" --tasks "$migration_arn" \
    --query "tasks[0].containers[?name=='app'].exitCode | [0]" --output text)
test "$exit_code" = 0

check_release() {
    deployed=$(aws ecs describe-services --cluster "$ECS_CLUSTER" \
        --services "$1" --query 'services[0].taskDefinition' --output text)
    test "$deployed" = "$2"
}

aws ecs update-service --cluster "$ECS_CLUSTER" --service eduflow-web \
    --task-definition "$WEB_TASK_DEF"
aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services eduflow-web
check_release eduflow-web "$WEB_TASK_DEF"

aws ecs update-service --cluster "$ECS_CLUSTER" --service eduflow-jobs \
    --task-definition "$JOBS_TASK_DEF"
aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services eduflow-jobs
check_release eduflow-jobs "$JOBS_TASK_DEF"
```

각 서비스가 안정화되면 실행 중인 Task Definition이 배포하려던 ARN과 일치하는지도
확인합니다. 자동 롤백 뒤에도 서비스는 이전 리비전에서 안정 상태가 될 수 있습니다.
[ECS 배포 실패 감지와 자동 롤백](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html)

## 5. 배포 확인과 복구

- **스모크 테스트** — 공개 교육과 대표 이미지가 HTTPS로 로드되는지 확인합니다. 접수·확인중 건수가 정원을
  넘어도 신청을 받고, 완료 건수가 정원에 도달하거나 접수 기간이 끝나면 신규 신청을 거절하는지 확인합니다.
  운영자만 신청과 발송 기록을 조회할 수 있는지 확인합니다. 테스트 수신자로 안내
  메일 한 통을 받고, 테스트 스프레드시트로 필터링 결과가 저장되는지 확인합니다.
- **로그와 알림** — ECS의 `awslogs`로 웹·Worker·Beat 로그 그룹을 나눕니다. 배포 실패,
  ALB 5xx, 비정상 대상, Worker 재시작, DB 연결 수, 메일 예약 지연과 SES 반송을
  알림으로 연결합니다. 예약 지연 수집은 별도 애플리케이션 지표로 구현합니다.
- **애플리케이션 롤백** — 웹이나 메일 처리 서비스에 문제가 생기면 이전 정상 Task
  Definition 리비전으로 되돌립니다. 스키마와 작업 메시지를 호환되게 유지해 이전 버전이
  서비스를 이어받도록 합니다. 메일 처리 Task 교체 시 Beat를 한 개로 유지합니다.
- **DB 복구** — 운영 DB 장애는 RDS 백업을 별도 인스턴스로 복원하고 데이터 정합성을
  확인한 뒤 연결을 전환합니다. 복구 시점 이후 접수와 이미 발송된 예약을 확인해,
  중복 발송 여부를 판단하기 전에는 복원 DB를 대상으로 Worker를 가동하지 않습니다.
