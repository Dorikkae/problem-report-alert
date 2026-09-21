# 문제보고 알림

Windows 문제보고 시트 감시 및 Slack 알림 프로그램.

## 자동 업데이트
프로그램은 `manifest.json`을 확인해 새 버전이 있으면 자동으로 EXE를 내려받아 교체하고 재실행합니다.

## Release 만들기
GitHub의 **Actions → Build and Release → Run workflow**에서 버전을 입력하면 Windows EXE 빌드, Release 생성, SHA-256 계산, `manifest.json` 갱신이 자동으로 진행됩니다.

> Google Sheet URL, Slack Bot Token, Google 로그인 데이터는 저장소에 올리지 않습니다.
