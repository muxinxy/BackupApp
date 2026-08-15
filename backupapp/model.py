"""数据模型：AppConfig / BackupPlan / Settings。

JSON 字段保持驼峰命名（与设计草案一致），代码内用 snake_case。
每个对象带 schemaVersion，存储层加载时走迁移钩子。
"""

from dataclasses import dataclass, field
from datetime import datetime

SCHEMA_VERSION = 2

MIGRATIONS: dict[int, callable] = {}
"""v1 起。MIGRATIONS[v] 把 v 版 dict 升级为 v+1 版。"""


def _migrate_v1_to_v2(d: dict) -> dict:
    """v1 -> v2：selfBackup 单对象 -> selfBackups 按协议分组（每协议独立配置）。"""
    sb = d.get("selfBackup")
    if isinstance(sb, dict) and sb:
        proto = str(sb.get("protocol", "webdav"))
        d["selfBackups"] = {proto: sb}
    d.pop("selfBackup", None)
    return d


MIGRATIONS[1] = _migrate_v1_to_v2


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _migrate(d: dict) -> dict:
    v = int(d.get("schemaVersion", 1))
    while v < SCHEMA_VERSION:
        fn = MIGRATIONS.get(v)
        d = fn(d) if fn else d
        v += 1
        d["schemaVersion"] = v
    return d


@dataclass
class BackupPlan:
    id: str
    name: str
    enabled: bool = True
    sources: list[str] = field(default_factory=list)
    destination: str = ""
    retention: int = 14
    keep_monthly: bool = True
    retention_unit: str = "count"  # count=保留最近 N 份 | days=保留最近 N 天内的
    keep_yearly: bool = False
    compress: bool = True
    format: str = "zip"  # zip | 7z | tar.gz
    password: str = ""   # 压缩包密码（zip AES / 7z）；空 = 无密码
    exclude: list[str] = field(default_factory=list)
    backup_mode: str = "copy"    # copy | link（备份后源路径替换为指向 destination 的链接）
    restore_mode: str = "copy"   # copy | link（恢复时重建链接而非拷贝回源路径）
    link_type: str = "junction"  # junction | symlink
    schedule_mode: str = "global"          # global | custom（计划任务排期：与全局一致或自定义）
    schedule_frequency: str = "daily"      # daily | weekly | atLogon | days | hourly | minutely
    schedule_time: str = "02:30"
    schedule_day_of_week: int = 1          # 1=Mon .. 7=Sun（weekly 时生效）
    schedule_interval: int = 1             # 每 N 天/小时/分钟（days/hourly/minutely 时生效）
    created_at: str = ""
    updated_at: str = ""
    last_run_at: str | None = None
    last_result: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "sources": list(self.sources),
            "destination": self.destination,
            "retention": self.retention,
            "keepMonthly": self.keep_monthly,
            "retentionUnit": self.retention_unit,
            "keepYearly": self.keep_yearly,
            "compress": self.compress,
            "format": self.format,
            "password": self.password,
            "exclude": list(self.exclude),
            "backupMode": self.backup_mode,
            "restoreMode": self.restore_mode,
            "linkType": self.link_type,
            "scheduleMode": self.schedule_mode,
            "scheduleFrequency": self.schedule_frequency,
            "scheduleTime": self.schedule_time,
            "scheduleDayOfWeek": self.schedule_day_of_week,
            "scheduleInterval": self.schedule_interval,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "lastRunAt": self.last_run_at,
            "lastResult": self.last_result,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BackupPlan":
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            enabled=bool(d.get("enabled", True)),
            sources=[str(s) for s in d.get("sources", [])],
            destination=str(d.get("destination", "")),
            retention=int(d.get("retention", 14)),
            keep_monthly=bool(d.get("keepMonthly", True)),
            retention_unit=str(d.get("retentionUnit", "count")),
            keep_yearly=bool(d.get("keepYearly", False)),
            compress=bool(d.get("compress", True)),
            format=str(d.get("format", "zip")),
            password=str(d.get("password", "")),
            exclude=[str(s) for s in d.get("exclude", [])],
            backup_mode=str(d.get("backupMode", "copy")),
            restore_mode=str(d.get("restoreMode", "copy")),
            link_type=str(d.get("linkType", "junction")),
            schedule_mode=str(d.get("scheduleMode", "global")),
            schedule_frequency=str(d.get("scheduleFrequency", "daily")),
            schedule_time=str(d.get("scheduleTime", "02:30")),
            schedule_day_of_week=int(d.get("scheduleDayOfWeek", 1)),
            schedule_interval=int(d.get("scheduleInterval", 1)),
            created_at=str(d.get("createdAt", "")),
            updated_at=str(d.get("updatedAt", "")),
            last_run_at=d.get("lastRunAt"),
            last_result=d.get("lastResult"),
        )


@dataclass
class AppConfig:
    id: str
    name: str
    vendor: str = ""
    version: str = ""
    note: str = ""
    config_paths: list[str] = field(default_factory=list)
    data_paths: list[str] = field(default_factory=list)
    created_at: str = ""
    plans: list[BackupPlan] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "vendor": self.vendor,
            "version": self.version,
            "note": self.note,
            "configPaths": list(self.config_paths),
            "dataPaths": list(self.data_paths),
            "createdAt": self.created_at,
            "plans": [p.to_dict() for p in self.plans],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        d = _migrate(d)
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            vendor=str(d.get("vendor", "")),
            version=str(d.get("version", "")),
            note=str(d.get("note", "")),
            config_paths=[str(s) for s in d.get("configPaths", [])],
            data_paths=[str(s) for s in d.get("dataPaths", [])],
            created_at=str(d.get("createdAt", "")),
            plans=[BackupPlan.from_dict(p) for p in d.get("plans", [])],
        )

    def get_plan(self, plan_id: str) -> BackupPlan | None:
        for p in self.plans:
            if p.id == plan_id:
                return p
        return None


@dataclass
class General:
    language: str = "zh-CN"
    log_level: str = "info"
    max_log_size_mb: int = 5
    theme: str = "light"  # light | dark | system

    def to_dict(self) -> dict:
        return {"language": self.language, "logLevel": self.log_level,
                "maxLogSizeMB": self.max_log_size_mb, "theme": self.theme}

    @classmethod
    def from_dict(cls, d: dict) -> "General":
        return cls(language=str(d.get("language", "zh-CN")),
                   log_level=str(d.get("logLevel", "info")),
                   max_log_size_mb=int(d.get("maxLogSizeMB", 5)),
                   theme=str(d.get("theme", "light")))


@dataclass
class SchedulerCfg:
    enabled: bool = False
    frequency: str = "daily"  # daily | weekly | atLogon | days | hourly | minutely
    time: str = "02:30"
    day_of_week: int = 1      # 1=Mon .. 7=Sun（weekly 时生效）
    interval: int = 1         # 每 N 天/小时/分钟（days/hourly/minutely 时生效）
    args: list[str] = field(default_factory=lambda: ["backup", "--all"])

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "frequency": self.frequency,
                "time": self.time, "dayOfWeek": self.day_of_week,
                "interval": self.interval, "args": list(self.args)}

    @classmethod
    def from_dict(cls, d: dict) -> "SchedulerCfg":
        return cls(enabled=bool(d.get("enabled", False)),
                   frequency=str(d.get("frequency", "daily")),
                   time=str(d.get("time", "02:30")),
                   day_of_week=int(d.get("dayOfWeek", 1)),
                   interval=int(d.get("interval", 1)),
                   args=[str(a) for a in d.get("args", ["backup", "--all"])])


@dataclass
class SelfBackup:
    enabled: bool = False
    protocol: str = "webdav"  # webdav | s3 | ftp | sftp
    host: str = ""
    port: int | None = None
    remote_path: str = ""
    username: str = ""
    password: str = ""
    credential_store: str = "plain"  # plain | dpapi | keyring
    bucket: str = ""
    region: str = ""
    endpoint: str = ""
    use_ssl: bool = True
    timeout: int = 10  # 连接/IO 超时（秒）
    retention: int = 30
    compress: bool = True
    format: str = "zip"
    archive_password: str = ""
    local_copy: bool = True

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "protocol": self.protocol,
                "host": self.host, "port": self.port,
                "remotePath": self.remote_path, "username": self.username,
                "password": self.password, "credentialStore": self.credential_store,
                "bucket": self.bucket, "region": self.region,
                "endpoint": self.endpoint, "useSsl": self.use_ssl,
                "timeout": self.timeout, "retention": self.retention,
                "compress": self.compress, "format": self.format,
                "archivePassword": self.archive_password,
                "localCopy": self.local_copy}

    @classmethod
    def from_dict(cls, d: dict) -> "SelfBackup":
        return cls(enabled=bool(d.get("enabled", False)),
                   protocol=str(d.get("protocol", "webdav")),
                   host=str(d.get("host", "")),
                   port=d.get("port"),
                   remote_path=str(d.get("remotePath", "")),
                   username=str(d.get("username", "")),
                   password=str(d.get("password", "")),
                   credential_store=str(d.get("credentialStore", "plain")),
                   bucket=str(d.get("bucket", "")),
                   region=str(d.get("region", "")),
                   endpoint=str(d.get("endpoint", "")),
                   use_ssl=bool(d.get("useSsl", True)),
                   timeout=int(d.get("timeout", 10)),
                   retention=int(d.get("retention", 30)),
                   compress=bool(d.get("compress", True)),
                   format=str(d.get("format", "zip")),
                   archive_password=str(d.get("archivePassword", "")),
                   local_copy=bool(d.get("localCopy", True)))


@dataclass
class ScriptsCfg:
    default_flavor: str = "ps1"  # ps1 | bat | sh
    embed_config: bool = True    # 脚本自包含（参数内嵌） vs 引用 data 目录

    def to_dict(self) -> dict:
        return {"defaultFlavor": self.default_flavor, "embedConfig": self.embed_config}

    @classmethod
    def from_dict(cls, d: dict) -> "ScriptsCfg":
        return cls(default_flavor=str(d.get("defaultFlavor", "ps1")),
                   embed_config=bool(d.get("embedConfig", True)))


@dataclass
class Settings:
    schema_version: int = SCHEMA_VERSION
    general: General = field(default_factory=General)
    scheduler: SchedulerCfg = field(default_factory=SchedulerCfg)
    self_backups: dict[str, SelfBackup] = field(default_factory=dict)
    scripts: ScriptsCfg = field(default_factory=ScriptsCfg)
    scheduler_registered: bool = False

    def sb(self, protocol: str) -> SelfBackup:
        """指定协议的自身备份配置；不存在时返回该协议默认值（不写入）。"""
        return self.self_backups.get(protocol, SelfBackup(protocol=protocol))

    def enabled_sbs(self) -> list[SelfBackup]:
        """已启用的自身备份配置列表。"""
        return [sb for sb in self.self_backups.values() if sb.enabled]

    @classmethod
    def default(cls) -> "Settings":
        return cls()

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "general": self.general.to_dict(),
            "scheduler": self.scheduler.to_dict(),
            "selfBackups": {k: v.to_dict() for k, v in self.self_backups.items()},
            "scripts": self.scripts.to_dict(),
            "schedulerRegistered": self.scheduler_registered,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        d = _migrate(d)
        sbs = {k: SelfBackup.from_dict(v) for k, v in d.get("selfBackups", {}).items()}
        return cls(
            schema_version=int(d.get("schemaVersion", SCHEMA_VERSION)),
            general=General.from_dict(d.get("general", {})),
            scheduler=SchedulerCfg.from_dict(d.get("scheduler", {})),
            self_backups=sbs,
            scripts=ScriptsCfg.from_dict(d.get("scripts", {})),
            scheduler_registered=bool(d.get("schedulerRegistered", False)),
        )
