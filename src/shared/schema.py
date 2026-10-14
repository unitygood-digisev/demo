"""共用資料模型。每個欄位都有繁體中文描述；可空欄位缺值時輸出顯示「待補」。"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Level = Literal["公開", "內部一般", "內部敏感", "客戶機密"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_row: int | None = Field(None, description="來源檔案的 Excel 列號，用於追查數字出處")


class Project(_Base):
    project_id: str = Field(description="項目編號")
    client: str = Field(description="客戶名稱")
    name: str = Field(description="專案名稱")
    owner: str = Field(description="負責人")
    start_date: dt.date = Field(description="起始日")
    planned_end_date: dt.date = Field(description="預計結案日")
    status: Literal["未開始", "進行中", "已結案", "暫停"] = Field(description="狀態")


class Milestone(_Base):
    project_id: str = Field(description="所屬項目編號")
    name: str = Field(description="里程碑名稱")
    planned_date: dt.date = Field(description="預計完成日")
    actual_date: dt.date | None = Field(None, description="實際完成日（未完成可空）")
    status: str = Field(description="狀態，例如 未開始／進行中／已完成")


class Contract(_Base):
    contract_id: str = Field(description="合約編號")
    project_id: str | None = Field(None, description="對應項目編號")
    client: str = Field(description="客戶名稱")
    total_amount: float | None = Field(None, description="合約總價（元）")
    currency: str | None = Field(None, description="幣別，非 TWD 標「幣別待確認」")
    sign_date: dt.date | None = Field(None, description="簽約日")
    start_date: dt.date | None = Field(None, description="起始日")
    end_date: dt.date | None = Field(None, description="迄止日")
    auto_renew: Literal["是", "否", "未確認"] = Field("未確認", description="是否自動續約")
    renewal_terms: str | None = Field(None, description="續約條款原文【待法務確認】")
    payment_terms: str | None = Field(None, description="付款條件原文【待法務確認】")


class Receivable(_Base):
    invoice_id: str = Field(description="發票號碼")
    project_id: str = Field(description="項目編號")
    invoice_date: dt.date = Field(description="發票日")
    due_date: dt.date = Field(description="到期日")
    amount: float = Field(description="發票金額（元）")
    received: float | None = Field(None, description="已收金額（元）")
    received_date: dt.date | None = Field(None, description="收款日")


class TimeEntry(_Base):
    date: dt.date = Field(description="日期")
    person_code: str = Field(description="人員代碼（不使用姓名；不得出現在輸出）")
    project_id: str | None = Field(None, description="項目編號（非專案工時可空）")
    task_category: str = Field(description="任務類別")
    hours: float = Field(description="小時數")


class Lead(_Base):
    lead_id: str = Field(description="名單編號")
    source: Literal["展會", "永續評鑑", "介紹", "其他"] = Field(description="名單來源")
    registered_date: dt.date = Field(description="登記日")
    company: str = Field(description="公司名稱（不含聯絡人個資）")
    stage: str = Field(description="目前階段")


class NewsItem(_Base):
    id: str = Field(description="文章編號（由正規化網址雜湊產生）")
    source_id: str = Field(description="來源代號")
    title: str = Field(description="標題")
    url: str = Field(description="原文網址（只能來自輸入資料）")
    published: dt.datetime | None = Field(None, description="發布時間")
    excerpt: str | None = Field(None, description="內文摘錄")
    fetched_at: dt.datetime = Field(description="抓取時間")
    extra_urls: tuple[str, ...] = Field((), description="合併的同一事件其他來源連結")


class Page(_Base):
    page_id: str = Field(description="Wiki 頁面編號")
    title: str = Field(description="頁面標題")
    summary: str | None = Field(None, description="一句話摘要")
    points: tuple[str, ...] = Field((), description="要點（最多 7 條，每條須有出處）")
    citations: tuple[str, ...] = Field((), description="出處（文件名＋頁碼或章節）")
    level: Level = Field(description="資料等級")
    updated: dt.date | None = Field(None, description="更新日期")
