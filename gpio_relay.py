from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any



def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RelayConfig:
    enabled: bool = _to_bool(os.getenv("HEATER_RELAY_ENABLED"), False)
    gpio_pin: int = int(os.getenv("HEATER_RELAY_GPIO_PIN", "18"))
    active_low: bool = _to_bool(os.getenv("HEATER_RELAY_ACTIVE_LOW"), True)
    backend: str = os.getenv("HEATER_RELAY_BACKEND", "auto").strip().lower() or "auto"
    dry_run: bool = _to_bool(os.getenv("HEATER_RELAY_DRY_RUN"), False)
    pinctrl_path: str = os.getenv("HEATER_RELAY_PINCTRL_PATH", "").strip()


class BaseRelayDriver:
    backend_name = "base"

    def write(self, electrical_high: bool) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        return None


class DisabledRelayDriver(BaseRelayDriver):
    backend_name = "disabled"

    def write(self, electrical_high: bool) -> None:
        return None


class DryRunRelayDriver(BaseRelayDriver):
    backend_name = "dry-run"

    def __init__(self) -> None:
        self.last_written_high: bool | None = None

    def write(self, electrical_high: bool) -> None:
        self.last_written_high = bool(electrical_high)


class PinctrlRelayDriver(BaseRelayDriver):
    backend_name = "pinctrl"

    def __init__(self, pin: int, executable: str) -> None:
        self.pin = int(pin)
        self.executable = executable
        self._run("set", str(self.pin), "op", "dl")

    def _run(self, *args: str) -> None:
        completed = subprocess.run(
            [self.executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(stderr or f"pinctrl failed with exit code {completed.returncode}")

    def write(self, electrical_high: bool) -> None:
        self._run("set", str(self.pin), "dh" if electrical_high else "dl")


class RPiGPIORelayDriver(BaseRelayDriver):
    backend_name = "rpi-gpio"

    def __init__(self, pin: int) -> None:
        import RPi.GPIO as GPIO  # type: ignore

        self.GPIO = GPIO
        self.pin = int(pin)
        self.GPIO.setwarnings(False)
        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setup(self.pin, self.GPIO.OUT, initial=self.GPIO.LOW)

    def write(self, electrical_high: bool) -> None:
        self.GPIO.output(self.pin, self.GPIO.HIGH if electrical_high else self.GPIO.LOW)

    def close(self) -> None:
        try:
            self.GPIO.cleanup(self.pin)
        except Exception:
            pass


class LgpioRelayDriver(BaseRelayDriver):
    backend_name = "lgpio"

    def __init__(self, pin: int) -> None:
        import lgpio  # type: ignore

        self.lgpio = lgpio
        self.pin = int(pin)
        self.handle = self.lgpio.gpiochip_open(0)
        self.lgpio.gpio_claim_output(self.handle, self.pin, 0)

    def write(self, electrical_high: bool) -> None:
        self.lgpio.gpio_write(self.handle, self.pin, 1 if electrical_high else 0)

    def close(self) -> None:
        try:
            self.lgpio.gpio_free(self.handle, self.pin)
        except Exception:
            pass
        try:
            self.lgpio.gpiochip_close(self.handle)
        except Exception:
            pass


class HeaterRelayController:
    def __init__(self) -> None:
        self.config = RelayConfig()
        self._lock = Lock()
        self._driver: BaseRelayDriver | None = None
        self._initialized = False
        self._backend_name = "uninitialized"
        self._heater_on: bool | None = None
        self._last_error: str | None = None

    def _resolve_pinctrl_path(self) -> str | None:
        if self.config.pinctrl_path:
            return self.config.pinctrl_path
        return shutil.which("pinctrl")

    def _build_driver(self) -> BaseRelayDriver:
        if not self.config.enabled:
            self._backend_name = "disabled"
            return DisabledRelayDriver()

        if self.config.dry_run:
            self._backend_name = "dry-run"
            return DryRunRelayDriver()

        candidates = [self.config.backend] if self.config.backend != "auto" else ["pinctrl", "lgpio", "rpi-gpio"]
        errors: list[str] = []

        for backend in candidates:
            try:
                if backend == "pinctrl":
                    executable = self._resolve_pinctrl_path()
                    if executable:
                        self._backend_name = "pinctrl"
                        return PinctrlRelayDriver(self.config.gpio_pin, executable)
                    errors.append("pinctrl command not found")
                elif backend == "lgpio":
                    self._backend_name = "lgpio"
                    return LgpioRelayDriver(self.config.gpio_pin)
                elif backend in {"rpi", "rpi-gpio", "rpi_gpio"}:
                    self._backend_name = "rpi-gpio"
                    return RPiGPIORelayDriver(self.config.gpio_pin)
                else:
                    errors.append(f"unsupported backend: {backend}")
            except Exception as exc:
                errors.append(f"{backend}: {exc}")

        self._backend_name = "error"
        raise RuntimeError(
            "GPIO relay backend initialization failed. "
            + "; ".join(errors or ["no backend available"])
        )

    def initialize(self) -> dict[str, Any]:
        with self._lock:
            if self._initialized:
                return self.status()
            self._driver = self._build_driver()
            self._initialized = True
            self._last_error = None
            return self.status()

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()
        if self._driver is None:
            raise RuntimeError("GPIO relay driver is not initialized")

    def _logical_to_electrical(self, heater_on: bool) -> bool:
        return (not heater_on) if self.config.active_low else bool(heater_on)

    def set_heater(self, heater_on: bool, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            desired = bool(heater_on)
            if not force and self._heater_on is desired:
                return self.status()
            electrical_high = self._logical_to_electrical(desired)
            self._driver.write(electrical_high)
            self._heater_on = desired
            self._last_error = None
            return self.status()

    def sync_from_runtime(self, runtime_snapshot: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        return self.set_heater(bool(runtime_snapshot.get("heater_on")), force=force)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "gpio_pin": self.config.gpio_pin,
            "active_low": self.config.active_low,
            "backend": self._backend_name,
            "initialized": self._initialized,
            "heater_on": self._heater_on,
            "last_error": self._last_error,
            "config": asdict(self.config),
        }

    def fail(self, exc: Exception) -> dict[str, Any]:
        self._last_error = str(exc)
        return self.status()

    def close(self) -> None:
        with self._lock:
            if self._driver is not None:
                try:
                    self._driver.close()
                finally:
                    self._driver = None
                    self._initialized = False


heater_relay_controller = HeaterRelayController()
