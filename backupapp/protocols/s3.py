"""S3 上传器：boto3（兼容 AWS S3 与 MinIO 等 S3 兼容存储）。"""

from ..model import SelfBackup
from .base import BACKUP_PREFIX, Uploader


class S3Uploader(Uploader):
    def __init__(self, sb: SelfBackup):
        if not sb.bucket:
            raise ValueError("S3 未配置 bucket")
        import boto3
        kwargs = {
            "aws_access_key_id": sb.username or None,
            "aws_secret_access_key": sb.password or None,
            "region_name": sb.region or None,
        }
        if sb.endpoint:
            kwargs["endpoint_url"] = sb.endpoint
        self.client = boto3.client("s3", **kwargs)
        self.bucket = sb.bucket
        self.prefix = sb.remote_path.strip("/")

    def _key(self, name: str = "") -> str:
        return f"{self.prefix}/{name}" if name else self.prefix

    def test(self) -> tuple[bool, str]:
        try:
            self.client.list_objects_v2(Bucket=self.bucket, MaxKeys=1)
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def upload(self, local_path: str, remote_name: str) -> None:
        self.client.upload_file(local_path, self.bucket, self._key(remote_name))

    def list(self) -> list[str]:
        out = []
        kw = {"Bucket": self.bucket, "Prefix": self._key()}
        while True:
            r = self.client.list_objects_v2(**kw)
            for obj in r.get("Contents", []):
                name = obj["Key"].split("/")[-1]
                if name.startswith(BACKUP_PREFIX):
                    out.append(name)
            if not r.get("IsTruncated"):
                break
            kw["ContinuationToken"] = r.get("NextContinuationToken")
        return out

    def delete(self, remote_name: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(remote_name))
