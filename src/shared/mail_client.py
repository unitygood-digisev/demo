"""唯一的寄信入口（CLAUDE.md 第 5 節的例外，2026-10-15 經同意）。

限制（違反就丟例外，不寄）：
- 收件人只能是 .env 白名單（MAIL_TO）裡的公司信箱（config/mail.yaml 的 allowed_domain）。
- 寄件人也必須是公司信箱。
- 內容等級不能高於 config/mail.yaml 的 max_level（預設內部一般）。
- 同一種郵件同一天最多寄一次；寄送紀錄存本機（只記時間、種類、收件人數、主旨雜湊，不記內容）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from shared.classify import Classifier
from shared.config import PROJECT_ROOT, load_dotenv, load_yaml

_ADDR = re.compile(r"^[A-Za-z0-9._+-]+@([A-Za-z0-9.-]+)$")  # 不接受 % 等舊式轉信寫法


class MailError(Exception):
    """違反寄送規則或寄送失敗（訊息為白話中文）。"""


class MailNotConfigured(MailError):
    """.env 還沒設定寄件帳號、密碼或收件人。"""


class MailClient:
    def __init__(
        self,
        config_dir: Path | None = None,
        log_path: Path = PROJECT_ROOT / "data" / "interim" / "mail" / "sent.jsonl",
        smtp_factory=smtplib.SMTP,
        env_file: Path | None = None,
    ) -> None:
        self.cfg = load_yaml("mail.yaml", config_dir)
        self.classifier = Classifier(config_dir)
        self.log_path = log_path
        self.smtp_factory = smtp_factory
        self.env_file = env_file

    def _addr_ok(self, addr: str) -> bool:
        m = _ADDR.match(addr)
        return bool(m) and m[1].lower() == str(self.cfg["allowed_domain"]).lower()

    def already_sent(self, kind: str, day: dt.date) -> bool:
        """讀寄送紀錄。紀錄壞掉時丟 MailError、不寄（寧可不寄，也不要每天重寄）。"""
        if not self.log_path.exists():
            return False
        try:
            text = self.log_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise MailError(
                f"寄送紀錄 {self.log_path.name} 無法讀取，為避免重寄已停止，請負責人檢查"
            ) from e
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if not isinstance(r, dict):
                    raise ValueError
            except ValueError as e:
                raise MailError(
                    f"寄送紀錄 {self.log_path.name} 第 {n} 行壞掉，為避免重寄已停止，請負責人檢查"
                ) from e
            if r.get("kind") == kind and r.get("day") == day.isoformat():
                return True
        return False

    def send(self, subject: str, body: str, *, level: str, kind: str, day: dt.date) -> bool:
        """寄出回傳 True；今天已寄過回傳 False。違反規則丟 MailError。"""
        if not self.cfg.get("enabled", False):
            raise MailNotConfigured("config/mail.yaml 的 enabled 為 false，不寄信")
        max_level = str(self.cfg.get("max_level", "內部一般"))
        if level not in self.classifier.levels:
            raise MailError(f"不認得的資料等級「{level}」，已拒寄")
        if self.classifier.rank(level) > self.classifier.rank(max_level):
            raise MailError(f"資料等級「{level}」高於允許寄送的「{max_level}」，已拒寄")
        try:
            load_dotenv(self.env_file)
        except ValueError as e:
            raise MailError(str(e)) from e
        sender = os.environ.get(self.cfg["sender_env"], "").strip()
        password = os.environ.get(self.cfg["password_env"], "").strip()
        to: list[str] = []
        for x in os.environ.get(self.cfg["recipients_env"], "").split(","):
            if x.strip() and x.strip().lower() not in {t.lower() for t in to}:
                to.append(x.strip())  # 重複的收件人只留一個
        if not sender or not password or not to:
            raise MailNotConfigured(
                "尚未設定寄件帳號、應用程式密碼或收件人（.env 的 MAIL_FROM、MAIL_APP_PASSWORD、MAIL_TO），未寄出"
            )
        if not self._addr_ok(sender):
            raise MailError(f"寄件帳號必須是 @{self.cfg['allowed_domain']} 的公司信箱，已拒寄")
        bad = [a for a in to if not self._addr_ok(a)]
        if bad:
            raise MailError(
                f"收件人有 {len(bad)} 個不是 @{self.cfg['allowed_domain']} 的公司信箱，已全部拒寄"
            )
        if self.already_sent(kind, day):
            return False
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(to)
        msg.set_content(body)
        try:
            with self.smtp_factory(
                self.cfg["smtp_host"], int(self.cfg["smtp_port"]), timeout=30
            ) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(sender, password)
                s.send_message(msg)
        except smtplib.SMTPAuthenticationError as e:
            raise MailError(
                "寄件帳號登入失敗，請確認應用程式密碼是否正確、是否已開啟兩步驟驗證"
            ) from e
        except (smtplib.SMTPException, OSError) as e:
            raise MailError(f"寄信失敗（{type(e).__name__}），請稍後重跑") from e
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "time": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "day": day.isoformat(),
            "kind": kind,
            "level": level,
            "recipients": len(to),
            "subject_sha256": hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16],
        }
        # 上一筆紀錄若沒寫完（沒有換行），先補換行，避免新紀錄接在壞行後面
        lead = ""
        if self.log_path.is_file() and self.log_path.stat().st_size:
            with self.log_path.open("rb") as f:
                f.seek(-1, os.SEEK_END)
                lead = "" if f.read(1) == b"\n" else "\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(lead + json.dumps(rec, ensure_ascii=False) + "\n")
        return True
