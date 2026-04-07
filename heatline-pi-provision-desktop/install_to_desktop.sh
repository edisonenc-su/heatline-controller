#!/bin/bash
set -e
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="$HOME/heatline-pi-provision-desktop"
DESKTOP_FILE_NAME="Heatline-Pi-현장등록.desktop"
DESKTOP_DIR="$HOME/Desktop"

mkdir -p "$TARGET_DIR"
cp "$SRC_DIR/pi_provision_helper_desktop.py" "$TARGET_DIR/"
cp "$SRC_DIR/run_heatline_pi_helper.sh" "$TARGET_DIR/"
cp "$SRC_DIR/$DESKTOP_FILE_NAME" "$TARGET_DIR/"
chmod +x "$TARGET_DIR/run_heatline_pi_helper.sh"
chmod +x "$TARGET_DIR/pi_provision_helper_desktop.py"

mkdir -p "$DESKTOP_DIR"
cp "$TARGET_DIR/$DESKTOP_FILE_NAME" "$DESKTOP_DIR/"
chmod +x "$DESKTOP_DIR/$DESKTOP_FILE_NAME"

echo "설치 완료"
echo "프로그램 폴더: $TARGET_DIR"
echo "바탕화면 아이콘: $DESKTOP_DIR/$DESKTOP_FILE_NAME"
echo "더블클릭 후 실행 권한 질문이 나오면 허용하세요."
