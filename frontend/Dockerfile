# 1단계: 빌드 환경 (Node.js)
FROM node:20-alpine as builder

# 작업 디렉토리 설정
WORKDIR /app

# 패키지 파일 복사 및 종속성 설치
COPY package.json package-lock.json* ./
RUN npm install

# 소스 코드 복사 및 빌드
COPY . .
RUN npm run build

# 2단계: 실행 환경 (Nginx)
FROM nginx:alpine

# 커스텀 Nginx 설정 복사
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 1단계에서 빌드된 정적 파일들을 Nginx 서빙 폴더로 복사
COPY --from=builder /app/dist /usr/share/nginx/html

# Cloud Run에서 사용할 포트 노출
EXPOSE 8080

# Nginx 실행
CMD ["nginx", "-g", "daemon off;"]
