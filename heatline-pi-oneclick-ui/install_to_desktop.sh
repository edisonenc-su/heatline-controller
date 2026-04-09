#!/bin/bash
set -e
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="$HOME/heatline-pi-oneclick-ui"
DESKTOP_FILE="Heatline-Pi-원클릭설정.desktop"
DESKTOP_DIR="$HOME/Desktop"

mkdir -p "$TARGET_DIR"
cp "$SRC_DIR/heatline_pi_oneclick_gui.py" "$TARGET_DIR/"
cp "$SRC_DIR/run_heatline_pi_oneclick.sh" "$TARGET_DIR/"
cp "$SRC_DIR/$DESKTOP_FILE" "$TARGET_DIR/"
chmod +x "$TARGET_DIR/heatline_pi_oneclick_gui.py" "$TARGET_DIR/run_heatline_pi_oneclick.sh"
mkdir -p "$DESKTOP_DIR"
cp "$TARGET_DIR/$DESKTOP_FILE" "$DESKTOP_DIR/"
chmod +x "$DESKTOP_DIR/$DESKTOP_FILE"

echo "설치 완료"
echo "프로그램 폴더: $TARGET_DIR"
echo "바탕화면 아이콘: $DESKTOP_DIR/$DESKTOP_FILE"
