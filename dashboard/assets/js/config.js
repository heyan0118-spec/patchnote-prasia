/**
 * 대시보드 환경 설정
 */
const CONFIG = {
    // 호스트가 localhost이거나, 로컬 파일로 열었을 경우(hostname이 비어있음) 로컬 API 서버 사용
    API_BASE: (!window.location.hostname || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
        ? "http://localhost:8000"
        : "" // 운영 서버 배포 시 여기에 URL 입력
};
