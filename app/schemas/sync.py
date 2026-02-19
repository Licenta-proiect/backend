# app\schemas\sync.py
from pydantic import BaseModel, Field
from typing import Optional

class SyncSettingsBase(BaseModel):
    auto_sync_enabled: bool = Field(..., description="Activează sau dezactivează sincronizarea automată")
    sync_interval: str = Field(..., pattern="^(daily|weekly|monthly)$", description="Intervalul: daily, weekly sau monthly")
    sync_time: str = Field(..., pattern="^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", description="Ora în format HH:MM")

class SyncSettingsUpdate(SyncSettingsBase):
    pass

class SyncSettingsResponse(SyncSettingsBase):
    id: int
    is_updating: bool
    
    class Config:
        from_attributes = True