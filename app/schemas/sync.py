# app\schemas\sync.py
from pydantic import BaseModel, Field
from typing import Optional

class SyncSettingsBase(BaseModel):
    auto_sync_enabled: bool = Field(..., description="Enable or disable automatic synchronization")
    sync_interval: str = Field(..., pattern="^(daily|weekly|monthly)$", description="Interval: daily, weekly, or monthly")
    sync_time: str = Field(..., pattern="^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", description="Time in HH:MM format")

class SyncSettingsUpdate(SyncSettingsBase):
    pass

class SyncSettingsResponse(SyncSettingsBase):
    id: int
    is_updating: bool
    
    class Config:
        from_attributes = True

class BackupSettingsUpdate(BaseModel):
    backup_enabled: bool
    backup_interval: str
    backup_time: str