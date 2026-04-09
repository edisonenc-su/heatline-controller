#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext
except Exception as exc:
    print("Tkinter를 불러오지 못했습니다:", exc)
    print("다음을 실행 후 다시 시도하세요: sudo apt-get update && sudo apt-get install -y python3-tk")
    sys.exit(1)

APP_TITLE = "Heatline Pi 원클릭 설정"
DEFAULT_ENV_PATH = Path("/home/pi/heatline-pi-fastapi/.env")
DEFAULT_SERVICE = "heatline-pi-fastapi"
HEALTH_URL = "http://127.0.0.1:9000/health"
PROVISION_STATUS_URL = "http://127.0.0.1:9000/api/v1/provision/status"
DOCS_URL = "http://127.0.0.1:9000/docs"
AUTOSTART_DESKTOP = Path.home() / ".config" / "autostart" / "heatline-pi-fastapi.desktop"


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


def xdg_open(url: str) -> tuple[bool, str]:
    rc, out, err = run_command(["xdg-open", url])
    if rc == 0:
        return True, out or "브라우저를 열었습니다."
    return False, err or out or "브라우저 열기에 실패했습니다."


class OneClickApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("920x800")
        self.root.minsize(860, 720)
        self.env_path_var = tk.StringVar(value=str(DEFAULT_ENV_PATH))
        self.service_var = tk.StringVar(value=DEFAULT_SERVICE)
        self.device_serial_var = tk.StringVar()
        self.provision_key_var = tk.StringVar()
        self.status_var = tk.StringVar(value="대기 중")
        self._build_ui()
        self.load_existing_values(initial=True)

    def _build_ui(self) -> None:
        root_frame = tk.Frame(self.root, padx=18, pady=18)
        root_frame.pack(fill="both", expand=True)

        tk.Label(root_frame, text=APP_TITLE, font=("Arial", 20, "bold")).pack(anchor="w")
        tk.Label(
            root_frame,
            text="현장 작업자는 시리얼번호와 프로비전키만 입력하고, 적용 버튼만 누르면 됩니다.",
            fg="#444",
            pady=8,
            justify="left",
        ).pack(anchor="w")

        summary = tk.Frame(root_frame, bd=1, relief="solid", padx=12, pady=10, bg="#f6f8fb")
        summary.pack(fill="x", pady=(4, 12))
        tk.Label(summary, text="작업 흐름", font=("Arial", 11, "bold"), bg="#f6f8fb").pack(anchor="w")
        tk.Label(
            summary,
            text=(
                "1) DEVICE_SERIAL 입력\n"
                "2) PROVISION_KEY 입력\n"
                "3) [적용하기] 클릭\n"
                "4) ENV 저장 + 시작프로그램 등록 + 서비스 재시작 + 상태확인 자동 실행\n"
                "5) 완료 후 [서버 열기] 버튼으로 Pi 서버 화면 확인"
            ),
            justify="left",
            anchor="w",
            bg="#f6f8fb",
        ).pack(anchor="w")

        form = tk.LabelFrame(root_frame, text="입력", padx=12, pady=12)
        form.pack(fill="x", pady=(0, 12))
        self._row(form, 0, "DEVICE_SERIAL", self.device_serial_var, 64)
        self._row(form, 1, "PROVISION_KEY", self.provision_key_var, 64, show="*")

        extra = tk.LabelFrame(root_frame, text="고급 설정(기본값 그대로 사용 권장)", padx=12, pady=12)
        extra.pack(fill="x", pady=(0, 12))
        self._row(extra, 0, "ENV 경로", self.env_path_var, 72)
        self._row(extra, 1, "서비스명", self.service_var, 36)

        actions = tk.Frame(root_frame)
        actions.pack(fill="x", pady=(0, 8))
        tk.Button(actions, text="기존값 불러오기", width=16, command=self.load_existing_values).pack(side="left")
        tk.Button(actions, text="적용하기", width=24, bg="#1570ef", fg="white", command=self.apply_all).pack(side="left", padx=8)
        tk.Button(actions, text="상태만 확인", width=16, command=self.verify_only).pack(side="left")

        open_bar = tk.Frame(root_frame)
        open_bar.pack(fill="x", pady=(0, 12))
        tk.Button(open_bar, text="서버 열기 (/docs)", width=18, command=self.open_docs).pack(side="left")
        tk.Button(open_bar, text="헬스 열기 (/health)", width=18, command=self.open_health).pack(side="left", padx=8)
        tk.Button(open_bar, text="프로비전 상태 열기", width=18, command=self.open_provision).pack(side="left")

        status_box = tk.Frame(root_frame)
        status_box.pack(fill="x", pady=(0, 8))
        tk.Label(status_box, text="현재 상태:", font=("Arial", 11, "bold")).pack(side="left")
        tk.Label(status_box, textvariable=self.status_var, fg="#0f5132", font=("Arial", 11)).pack(side="left", padx=8)

        log_frame = tk.LabelFrame(root_frame, text="실행 결과", padx=8, pady=8)
        log_frame.pack(fill="both", expand=True)
        self.log = scrolledtext.ScrolledText(log_frame, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    def _row(self, parent: tk.Widget, row: int, label: str, variable: tk.StringVar, width: int, show: str | None = None) -> None:
        tk.Label(parent, text=label, width=16, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
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

    def set_status(self, text: str, ok: bool = True) -> None:
        self.status_var.set(text)

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
            if values.get("DEVICE_SERIAL"):
                self.device_serial_var.set(values["DEVICE_SERIAL"])
            if values.get("PROVISION_KEY"):
                self.provision_key_var.set(values["PROVISION_KEY"])
            if not initial:
                self.append_log(f"기존 ENV 로드 완료: {path}")
                self.set_status("기존값 불러오기 완료")
        except Exception as exc:
            self.append_log(f"기존값 로드 실패: {exc}")

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

    def save_env(self, env_path: Path, device_serial: str, provision_key: str) -> None:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        original = read_text(env_path)
        updated = update_env_text(original, {"DEVICE_SERIAL": device_serial, "PROVISION_KEY": provision_key})
        env_path.write_text(updated, encoding="utf-8")
        self.append_log(f"ENV 저장 완료: {env_path}")

    def enable_startup(self, service: str) -> None:
        self.append_log("시작프로그램 등록 중... (systemctl enable)")
        rc, out, err = run_command(["systemctl", "enable", service])
        if rc != 0:
            raise RuntimeError(f"systemctl enable 실패\nstdout: {out or '-'}\nstderr: {err or '-'}")
        self.append_log(f"시작프로그램 등록 완료: {out or 'enabled'}")

    def restart_service(self, service: str) -> None:
        self.append_log("서비스 재시작 중...")
        rc, out, err = run_command(["systemctl", "restart", service])
        if rc != 0:
            raise RuntimeError(f"systemctl restart 실패\nstdout: {out or '-'}\nstderr: {err or '-'}")
        self.append_log("서비스 재시작 완료")

    def verify_service(self, service: str) -> bool:
        rc, out, err = run_command(["systemctl", "is-enabled", service])
        self.append_log(f"systemctl is-enabled: {out or '-'}")
        rc2, out2, err2 = run_command(["systemctl", "is-active", service])
        self.append_log(f"systemctl is-active: {out2 or '-'}")
        if err:
            self.append_log(f"is-enabled stderr: {err}")
        if err2:
            self.append_log(f"is-active stderr: {err2}")
        return out2.strip() == "active"

    def verify_http(self) -> bool:
        self.append_log("서버 응답 확인 중...")
        ok1, health = http_get_json(HEALTH_URL)
        self.append_log("\n[GET /health]")
        self.append_log(health)
        ok2, provision = http_get_json(PROVISION_STATUS_URL)
        self.append_log("\n[GET /api/v1/provision/status]")
        self.append_log(provision)
        return ok1 or ok2

    def apply_all(self) -> None:
        try:
            env_path, service, device_serial, provision_key = self.validate_inputs()
            self.clear_log()
            self.set_status("작업 중...")
            self.append_log("1) ENV 저장")
            self.save_env(env_path, device_serial, provision_key)

            self.append_log("2) 시작프로그램 등록")
            self.enable_startup(service)

            self.append_log("3) 서비스 재시작")
            self.restart_service(service)
            time.sleep(2)

            self.append_log("4) 서비스 상태 확인")
            active_ok = self.verify_service(service)

            self.append_log("5) HTTP 상태 확인")
            http_ok = self.verify_http()

            if active_ok and http_ok:
                self.set_status("완료 - 서버 정상 실행 중")
                messagebox.showinfo(APP_TITLE, "완료되었습니다. 이제 '서버 열기' 버튼으로 바로 확인할 수 있습니다.")
            else:
                self.set_status("일부 확인 실패")
                messagebox.showwarning(APP_TITLE, "적용은 되었지만 일부 확인에 실패했습니다. 결과창을 확인하세요.")
        except Exception as exc:
            self.set_status("오류 발생")
            self.append_log("오류 발생:")
            self.append_log(str(exc))
            self.append_log("\n상세 정보:")
            self.append_log(traceback.format_exc())
            messagebox.showerror(APP_TITLE, str(exc))

    def verify_only(self) -> None:
        try:
            self.clear_log()
            self.set_status("확인 중...")
            service = self.service_var.get().strip() or DEFAULT_SERVICE
            active_ok = self.verify_service(service)
            http_ok = self.verify_http()
            if active_ok and http_ok:
                self.set_status("정상 실행 중")
                messagebox.showinfo(APP_TITLE, "서버가 정상 실행 중입니다.")
            else:
                self.set_status("확인 실패")
                messagebox.showwarning(APP_TITLE, "일부 확인에 실패했습니다. 결과창을 확인하세요.")
        except Exception as exc:
            self.set_status("오류 발생")
            self.append_log(str(exc))
            messagebox.showerror(APP_TITLE, str(exc))

    def open_docs(self) -> None:
        ok, msg = xdg_open(DOCS_URL)
        self.append_log(f"/docs 열기: {msg}")

    def open_health(self) -> None:
        ok, msg = xdg_open(HEALTH_URL)
        self.append_log(f"/health 열기: {msg}")

    def open_provision(self) -> None:
        ok, msg = xdg_open(PROVISION_STATUS_URL)
        self.append_log(f"/api/v1/provision/status 열기: {msg}")


def main() -> None:
    root = tk.Tk()
    OneClickApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
