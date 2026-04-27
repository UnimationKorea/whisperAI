# 🚀 Whisper 백엔드 Cloud Run 배포 가이드

이 가이드는 다른 계정에서 새 프로젝트를 생성하고, Whisper 백엔드를 Google Cloud Run에 배포하는 전체 과정을 담고 있습니다.

---

## 1단계: Google Cloud 준비 (새 계정/새 프로젝트)

1.  **GCP 콘솔 접속**: 배포할 계정으로 로그인한 뒤 [Google Cloud Console](https://console.cloud.google.com/)에 접속합니다.
2.  **프로젝트 생성**: 상단 프로젝트 선택창에서 **[새 프로젝트]**를 클릭하여 이름을 정하고 생성합니다. (예: `whisper-stt-project`)
3.  **결제 정보 등록**: 왼쪽 메뉴의 **[결제]** 탭에서 결제 수단(카드 등)을 등록해야 Cloud Run 사용이 가능합니다.

---

## 2단계: 필수 API 활성화 및 CLI 설정

1.  **gcloud CLI 설치**: 컴퓨터에 [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)가 설치되어 있어야 합니다.
2.  **로그인 및 프로젝트 설정**: 터미널(PowerShell 등)을 열고 다음 명령어를 순서대로 실행합니다.
    ```powershell
    # 1. 새 계정으로 로그인 (브라우저가 뜹니다)
    gcloud auth login

    # 2. 프로젝트 ID 확인 (방금 만든 프로젝트 ID 복사)
    gcloud projects list

    # 3. 사용할 프로젝트 설정
    gcloud config set project [YOUR_PROJECT_ID]
    ```
3.  **필수 API 활성화**: 다음 명령어로 필요한 기능을 켭니다.
    ```powershell
    gcloud services enable run.googleapis.com \
                           containerregistry.googleapis.com \
                           cloudbuild.googleapis.com \
                           artifactregistry.googleapis.com
    ```

---

## 3단계: Artifact Registry (이미지 저장소) 생성

빌드된 Docker 이미지를 저장할 공간을 만듭니다.
```powershell
# 리전은 서울(asia-northeast3)로 설정하는 것이 빠릅니다.
gcloud artifacts repositories create whisper-repo \
    --repository-format=docker \
    --location=asia-northeast3 \
    --description="Whisper Backend Repository"
```

---

## 4단계: 이미지 빌드 및 푸시 (Cloud Build 사용)

로컬의 소스 코드를 구글 서버로 보내서 이미지를 빌드합니다. (로컬에 Docker가 없어도 가능합니다!)
```powershell
# 백엔드 폴더(Dockerfile이 있는 곳)에서 실행하세요.
gcloud builds submit --tag asia-northeast3-docker.pkg.dev/[YOUR_PROJECT_ID]/whisper-repo/whisper-backend:latest
```

---

## 5단계: Cloud Run에 배포하기

가장 중요한 단계입니다. Whisper는 자원을 많이 쓰므로 설정을 잘 해줘야 합니다.

```powershell
gcloud run deploy whisper-backend \
    --image asia-northeast3-docker.pkg.dev/[YOUR_PROJECT_ID]/whisper-repo/whisper-backend:latest \
    --platform managed \
    --region asia-northeast3 \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 1 \
    --timeout 600 \
    --port 8080 \
    --set-env-vars "WHISPER_MODEL=tiny,WHISPER_DEVICE=cpu"
```

### 💡 주요 설정 설명:
*   `--memory 2Gi`: Whisper 모델을 돌리려면 최소 2GB 이상의 메모리가 필요합니다. (안 그러면 에러 발생)
*   `--timeout 600`: WebSocket 연결이 도중에 끊기지 않도록 타임아웃을 10분(600초)으로 늘립니다.
*   `--allow-unauthenticated`: 누구나 접속할 수 있도록 공개 설정합니다.

---

## 6단계: 프론트엔드 연결 수정

배포가 완료되면 `https://whisper-backend-xxxx.a.run.app` 형태의 URL이 나옵니다.
이 주소를 프론트엔드의 `App.jsx`에 반영해야 합니다.

1.  **`whisper/frontend/src/App.jsx`** 파일 상단의 `WS_URL` 부분을 배포된 주소로 수정합니다.
2.  이때, `https://` 대신 **`wss://`**를 사용해야 합니다.
    *   예: `wss://whisper-backend-xxxx.a.run.app/ws/stt`

---

## ⚠️ 주의사항 및 팁

1.  **첫 호출(Cold Start) 지연**: 인스턴스가 꺼져 있다가 처음 켜질 때 모델 로딩 때문에 10~20초 정도 응답이 늦을 수 있습니다.
2.  **비용 관리**: 테스트가 끝난 후에는 Cloud Run 서비스를 삭제하거나 **최소 인스턴스 수를 0**으로 유지하여 비용이 나가지 않게 하세요.
3.  **모델 크기**: `tiny` 대신 `base`나 `small`을 쓰고 싶다면 `--memory`를 4Gi 이상으로 늘려야 안정적입니다.
