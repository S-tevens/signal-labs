from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import re

Health = Literal['Excellent','Good','Fair','Poor']
SECRET = re.compile(r'(?i)(?:password|passwd|secret|token|api[_-]?key)\s*[:=]|bearer\s+\S+|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
class Metric(Strict):
    name: str = Field(pattern=r'^[a-zA-Z0-9_.-]{1,80}$')
    value: float
    unit: str = Field(max_length=24, pattern=r'^[a-zA-Z0-9%/_. -]*$')
    @model_validator(mode='after')
    def matching_unit(self):
        units={'cpu_pct':'%','mem_pct':'%','disk_pct':'%','bandwidth_mbps':'mbps','latency_ms':'ms','packet_loss_pct':'%','service_up':'bool','connectivity_up':'bool'}
        if self.name in units and self.unit != units[self.name]: raise ValueError('Metric unit does not match name')
        return self
class Event(Strict):
    category: str = Field(pattern=r'^[a-zA-Z0-9_.-]{1,80}$')
    severity: Literal['info','warning','critical','low','medium','high','error','debug','warn']
    count: int = Field(ge=1, le=1000000)
    summary: str = Field(max_length=200)
    @field_validator('severity', mode='before')
    @classmethod
    def normalize(cls, v): return v.lower() if isinstance(v,str) else v
    @field_validator('summary')
    @classmethod
    def screen(cls,v):
        if SECRET.search(v) or '\n' in v or '\r' in v: raise ValueError('unsafe event summary')
        return v
class Payload(Strict):
    payload_id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    tenant_ref: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    collector_id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    source_id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    region: str = Field(pattern=r'^[a-z0-9-]{1,32}$')
    event_ts_utc: str
    source_tz: str = Field(max_length=64)
    window_s: int = Field(ge=0,le=86400)
    metric: Metric|None = None
    event: Event|None = None
    health_state: Health
    collector_version: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,40}$')
    @field_validator('event_ts_utc')
    @classmethod
    def utc(cls,v):
        d=datetime.fromisoformat(v.replace('Z','+00:00'))
        if d.tzinfo is None or d.utcoffset().total_seconds()!=0: raise ValueError('UTC required')
        return d.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    @field_validator('source_tz')
    @classmethod
    def tz(cls,v):
        try: ZoneInfo(v)
        except Exception: raise ValueError('IANA timezone required')
        return v
    @model_validator(mode='after')
    def one(self):
        if (self.metric is None)==(self.event is None): raise ValueError('exactly one of metric or event required')
        return self
class Heartbeat(Strict):
    collector_id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    collector_version: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,40}$')
    config_hash: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')
    resource_usage: dict[str,float] = Field(default_factory=dict)
    @field_validator('resource_usage')
    @classmethod
    def resources(cls,v):
        if set(v)-{'cpu','memory','disk','cpu_percent','memory_percent','disk_percent'}: raise ValueError('unknown resource field')
        return v
