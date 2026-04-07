#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import traceback
import urllib.request
import webbrowser
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext
except Exception as exc:
    print("Tkinter를 불러오지 못했습니다:", exc)
    print("다음을 실행 후 다시 시도하세요: sudo apt-get update && sudo apt-get install -y python3-tk")
    sys.exit(1)

APP_TITLE = "Heatline Pi 현장 등록 도우미"
DEFAULT_ENV_PATH = Path("/home/pi/heatline-pi-fastapi/.env")
DEFAULT_SERVICE = "heatline-pi-fastapi"
HEALTH_URL = "http://127.0.0.1:9000/health"
PROVISION_STATUS_URL = "http://127.0.0.1:9000/api/v1/provision/status"
DOCS_URL = "http://127.0.0.1:9000/docs"
STATUS_URL = "http://127.0.0.1:9000/api/v1/status"


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def update_env_text(original: str, updates: dict[str, str]) -> str:
    lines = original.splitlines()
    used = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue

        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            used.add(key)
        else:
            output.append(line)

    if output and output[-1].strip() != "":
        output.append("")

    for key, value in updates.items():
        if key not in used:
            output.append(f"{key}={value}")

    return "\n".join(output).rstrip() + "\n"


def run_command(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def http_get_json(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(data)
                return True, json.dumps(parsed, ensure_ascii=False, indent=2)
            except Exception:
                return True, data
    except Exception as exc:
        return False, str(exc)


def open_url(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except Exception:
        return False


class ProvisionApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x760")
        self.root.minsize(820, 680)

        self.env_path_var = tk.StringVar(value=str(DEFAULT_ENV_PATH))
        self.service_var = tk.StringVar(value=DEFAULT_SERVICE)
        self.device_serial_var = tk.StringVar()
        self.provision_key_var = tk.StringVar()
        self.last_check_ok = False

        self._build_ui()
        self.load_existing_values(initial=True)

    def _build_ui(self) -> None:
        frame = tk.Frame(self.root, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=APP_TITLE, font=("Arial", 18, "bold")).pack(anchor="w")
        tk.Label(
            frame,
            text="시리얼번호와 프로비전키만 입력하면 .env 저장 → 서비스 재시작 → 상태 확인까지 한 번에 진행합니다.",
            fg="#444",
            pady=8,
            justify="left",
        ).pack(anchor="w")

        form = tk.LabelFrame(frame, text="입력 정보", padx=12, pady=12)
        form.pack(fill="x", pady=(8, 12))

        self._row(form, 0, "ENV 파일 경로", self.env_path_var, width=72)
        self._row(form, 1, "서비스 이름", self.service_var, width=40)
        self._row(form, 2, "DEVICE_SERIAL", self.device_serial_var, width=64)
        self._row(form, 3, "PROVISION_KEY", self.provision_key_var, width=64, show="*")

        info = tk.LabelFrame(frame, text="작업 순서", padx=12, pady=10)
        info.pack(fill="x", pady=(0, 12))
        tk.Label(
            info,
            justify="left",
            anchor="w",
            text=(
                "1) 프론트에서 장비 등록 후 프로비전 키를 발급합니다.\n"
                "2) 여기에서 DEVICE_SERIAL, PROVISION_KEY 를 입력합니다.\n"
                "3) [저장 + 재시작 + 확인] 버튼을 누릅니다.\n"
                "4) 성공하면 [Pi 서버 열기] 버튼으로 /docs 또는 /health 를 바로 엽니다."
            ),
        ).pack(anchor="w")

        button_bar1 = tk.Frame(frame)
        button_bar1.pack(fill="x", pady=(0, 8))
        tk.Button(button_bar1, text="기존값 불러오기", command=self.load_existing_values, width=18).pack(side="left")
        tk.Button(button_bar1, text="ENV만 저장", command=self.save_env_only, width=16).pack(side="left", padx=8)
        tk.Button(button_bar1, text="저장 + 재시작 + 확인", command=self.save_restart_verify, width=24, bg="#2d7ff9", fg="white").pack(side="left")
        tk.Button(button_bar1, text="상태만 확인", command=self.verify_only, width=16).pack(side="left", padx=8)

        button_bar2 = tk.Frame(frame)
        button_bar2.pack(fill="x", pady=(0, 12))
        tk.Button(button_bar2, text="Pi 서버 열기 (/docs)", command=self.open_docs, width=20).pack(side="left")
        tk.Button(button_bar2, text="헬스 확인 열기 (/health)", command=self.open_health, width=22).pack(side="left", padx=8)
        tk.Button(button_bar2, text="상태 JSON 열기", command=self.open_status, width=18).pack(side="left")

        result_box = tk.LabelFrame(frame, text="실행 결과", padx=8, pady=8)
        result_box.pack(fill="both", expand=True)
        self.log = scrolledtext.ScrolledText(result_box, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

        tk.Label(
            frame,
            text="권한 오류가 나면 관리자 권한으로 실행해야 합니다. (.desktop 파일은 pkexec/sudo 실행 스크립트를 호출합니다)",
            fg="#666",
            pady=8,
        ).pack(anchor="w")

    def _row(self, parent: tk.Widget, row: int, label: str, variable: tk.StringVar, width: int = 50, show: str | None = None) -> None:
        tk.Label(parent, text=label, width=18, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
        entry = tk.Entry(parent, textvariable=variable, width=width)
        if show:
            entry.configure(show=show)
        entry.grid(row=row, column=1, sticky="we", pady=4, padx=(8, 0))
        parent.grid_columnconfigure(1, weight=1)

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.root.update_idletasks()

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def load_existing_values(self, initial: bool = False) -> None:
        try:
            path = Path(self.env_path_var.get().strip() or str(DEFAULT_ENV_PATH))
            text = read_text(path)
            values: dict[str, str] = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()

            self.device_serial_var.set(values.get("DEVICE_SERIAL", self.device_serial_var.get()))
            self.provision_key_var.set(values.get("PROVISION_KEY", self.provision_key_var.get()))
            if not initial:
                self.append_log(f"기존 ENV 로드 완료: {path}")
        except Exception as exc:
            self.append_log(f"ENV 로드 실패: {exc}")

    def validate_inputs(self) -> tuple[Path, str, str, str]:
        env_path = Path(self.env_path_var.get().strip() or str(DEFAULT_ENV_PATH))
        service = self.service_var.get().strip() or DEFAULT_SERVICE
        device_serial = self.device_serial_var.get().strip()
        provision_key = self.provision_key_var.get().strip()
        if not device_serial:
            raise ValueError("DEVICE_SERIAL 을 입력하세요.")
        if not provision_key:
            raise ValueError("PROVISION_KEY 를 입력하세요.")
        return env_path, service, device_serial, provision_key

    def save_env_only(self) -> None:
        try:
            env_path, _, device_serial, provision_key = self.validate_inputs()
            env_path.parent.mkdir(parents=True, exist_ok=True)
            original = read_text(env_path)
            updated = update_env_text(original, {"DEVICE_SERIAL": device_serial, "PROVISION_KEY": provision_key})
            env_path.write_text(updated, encoding="utf-8")
            self.clear_log()
            self.append_log(f"ENV 저장 완료: {env_path}")
            messagebox.showinfo(APP_TITLE, "ENV 저장이 완료되었습니다.")
        except Exception as exc:
            self.append_log(f"ENV 저장 실패: {exc}")
            messagebox.showerror(APP_TITLE, str(exc))

    def verify_only(self) -> None:
        self.clear_log()
        self.last_check_ok = False
        self.append_log("서비스 상태 확인 중...")
        rc, out, err = run_command(["systemctl", "is-active", self.service_var.get().strip() or DEFAULT_SERVICE])
        self.append_log(f"systemctl is-active 결과: rc={rc}, out={out or '-'}, err={err or '-'}")
        ok1, health = http_get_json(HEALTH_URL)
        self.append_log("\n[GET /health]")
        self.append_log(health)
        ok2, provision = http_get_json(PROVISION_STATUS_URL)
        self.append_log("\n[GET /api/v1/provision/status]")
        self.append_log(provision)
        self.last_check_ok = ok1 or ok2
        if self.last_check_ok:
            messagebox.showinfo(APP_TITLE, "상태 확인이 완료되었습니다. 필요하면 Pi 서버 열기 버튼을 눌러주세요.")
        else:
            messagebox.showwarning(APP_TITLE, "상태 조회에 실패했습니다. 아래 결과창을 확인하세요.")

    def save_restart_verify(self) -> None:
        try:
            env_path, service, device_serial, provision_key = self.validate_inputs()
            self.clear_log()
            self.last_check_ok = False
            self.append_log("1) ENV 저장 중...")
            env_path.parent.mkdir(parents=True, exist_ok=True)
            original = read_text(env_path)
            updated = update_env_text(original, {"DEVICE_SERIAL": device_serial, "PROVISION_KEY": provision_key})
            env_path.write_text(updated, encoding="utf-8")
            self.append_log(f"   완료: {env_path}")

            self.append_log("2) 서비스 재시작 중...")
            rc, out, err = run_command(["systemctl", "restart", service])
            if rc != 0:
                raise RuntimeError(
                    "서비스 재시작 실패\n"
                    f"명령: systemctl restart {service}\n"
                    f"stdout: {out or '-'}\n"
                    f"stderr: {err or '-'}"
                )
            self.append_log("   완료: systemctl restart 성공")

            self.append_log("3) 서비스 활성 상태 확인 중...")
            rc, out, err = run_command(["systemctl", "is-active", service])
            self.append_log(f"   systemctl is-active: {out or '-'}")
            if rc != 0 or out.strip() != "active":
                self.append_log(f"   stderr: {err or '-'}")

            self.append_log("4) /health 확인 중...")
            ok1, health = http_get_json(HEALTH_URL)
            self.append_log(health)

            self.append_log("5) /api/v1/provision/status 확인 중...")
            ok2, provision = http_get_json(PROVISION_STATUS_URL)
            self.append_log(provision)

            self.last_check_ok = ok1 or ok2
            if self.last_check_ok:
                self.append_log("\n정상 확인됨. 이제 [Pi 서버 열기 (/docs)] 버튼으로 서버 화면을 열 수 있습니다.")
                messagebox.showinfo(APP_TITLE, "정상 확인 완료. Pi 서버 열기 버튼으로 화면을 열 수 있습니다.")
            else:
                messagebox.showwarning(APP_TITLE, "재시작은 되었지만 API 확인은 실패했습니다. 아래 결과창을 확인하세요.")
        except Exception as exc:
            self.append_log("오류 발생:")
            self.append_log(str(exc))
            self.append_log("\n상세 정보:")
            self.append_log(traceback.format_exc())
            messagebox.showerror(APP_TITLE, str(exc))

    def open_docs(self) -> None:
        if open_url(DOCS_URL):
            self.append_log(f"브라우저 열기: {DOCS_URL}")
        else:
            self.append_log(f"브라우저 열기 실패: {DOCS_URL}")

    def open_health(self) -> None:
        if open_url(HEALTH_URL):
            self.append_log(f"브라우저 열기: {HEALTH_URL}")
        else:
            self.append_log(f"브라우저 열기 실패: {HEALTH_URL}")

    def open_status(self) -> None:
        if open_url(STATUS_URL):
            self.append_log(f"브라우저 열기: {STATUS_URL}")
        else:
            self.append_log(f"브라우저 열기 실패: {STATUS_URL}")


def main() -> None:
    root = tk.Tk()
    ProvisionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
