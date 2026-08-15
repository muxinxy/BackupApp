"""S3 上传器：boto3（兼容 AWS S3 与 MinIO 等 S3 兼容存储）。

下载：generate_presigned_url + httpx GET（follow_redirects=True）。
S3 兼容网关（如阿里云盘 S3 端点）会 302 到 CDN/OSS 签名地址——
boto3 不跟随跨域重定向（HeadObject/GetObject 直接抛 302/403），
改用 httpx 手动跟随：跨域时自动剥 Authorization，且不带 Referer，绕开 OSS 防盗链。
"""

from ..model import SelfBackup
from .base import BACKUP_PREFIX, RemoteFile, Uploader


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
        self.client = boto3.client("s3", **kwargs,
                                   config=__import__("botocore").config.Config(
                                       connect_timeout=sb.timeout or 10,
                                       read_timeout=sb.timeout or 10,
                                       retries={"max_attempts": 2}))
        self.bucket = sb.bucket
        self.prefix = sb.remote_path.strip("/")
        self.timeout = sb.timeout or 10

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

    def download(self, remote_name: str, local_path: str) -> None:
        import httpx
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(remote_name)},
            ExpiresIn=300)
        r = httpx.get(url, follow_redirects=True, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"下载失败: HTTP {r.status_code} {r.text[:200]}")
        with open(local_path, "wb") as f:
            f.write(r.content)

    def list(self) -> list[RemoteFile]:
        out = []
        kw = {"Bucket": self.bucket, "Prefix": self._key()}
        while True:
            r = self.client.list_objects_v2(**kw)
            for obj in r.get("Contents", []):
                name = obj["Key"].split("/")[-1]
                if name.startswith(BACKUP_PREFIX):
                    out.append(RemoteFile(
                        name=name,
                        size=int(obj.get("Size", 0)),
                        mtime=obj.get("LastModified", "").isoformat()
                        if obj.get("LastModified") else "",
                    ))
            if not r.get("IsTruncated"):
                break
            kw["ContinuationToken"] = r.get("NextContinuationToken")
        return out

    def delete(self, remote_name: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(remote_name))
