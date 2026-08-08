"""凭据加密 + 多源脚本生成验证。

用法: .venv\Scripts\python scripts\security_smoke.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backupapp.model import AppConfig, BackupPlan  # noqa: E402
from backupapp.security import (  # noqa: E402
    decrypt_secret, encrypt_secret, keyring_get, keyring_set, plain_sb, secrets)
from backupapp.scripts import generator  # noqa: E402


def main() -> None:
    # --- DPAPI 往返（Windows） ---
    if sys.platform == "win32":
        enc = encrypt_secret("s3cr3t-中文密码", "dpapi")
        assert enc != "s3cr3t-中文密码", "DPAPI 未加密"
        assert decrypt_secret(enc, "dpapi") == "s3cr3t-中文密码", "DPAPI 解密不一致"
        assert decrypt_secret("", "dpapi") == "", "空值应原样返回"
        print("[ok] dpapi roundtrip (含中文)")

    # --- keyring 往返（Windows 凭据管理器） ---
    keyring_set("smoke_test", "k3y-value")
    assert keyring_get("smoke_test") == "k3y-value", "keyring 读取不一致"
    keyring_set("smoke_test", "")
    print("[ok] keyring roundtrip")

    # --- plain_sb / secrets 组合 ---
    from backupapp.model import SelfBackup
    sb = SelfBackup(credential_store="plain", password="pw", archive_password="apw")
    assert secrets(sb) == ("pw", "apw")
    assert plain_sb(sb).password == "pw"
    if sys.platform == "win32":
        sbd = SelfBackup(credential_store="dpapi",
                         password=encrypt_secret("pw", "dpapi"),
                         archive_password=encrypt_secret("apw", "dpapi"))
        assert plain_sb(sbd).password == "pw"
        assert plain_sb(sbd).archive_password == "apw"
        print("[ok] plain_sb/secrets dpapi")
    sbs = SelfBackup(credential_store="keyring", password="", archive_password="")
    keyring_set("selfbackup_remote", "kr-pw")
    keyring_set("selfbackup_archive", "kr-apw")
    assert plain_sb(sbs).password == "kr-pw"
    keyring_set("selfbackup_remote", "")
    keyring_set("selfbackup_archive", "")
    print("[ok] plain_sb/secrets keyring")

    # --- 多源脚本生成 ---
    app = AppConfig(id="multi", name="Multi")
    plan = BackupPlan(
        id="cfg", name="cfg", compress=True, format="zip", password="p@ss'word",
        sources=["C:/Users/foo/AppData/Roaming/App1", "C:/Users/foo/.config/app2"],
        destination="D:/Backups/multi")
    sh = generator.generate(app, plan, "backup", "sh")
    assert "C:/Users/foo/AppData/Roaming/App1" in sh and "app2" in sh
    assert "-C" in sh, "sh 多源 -C 参数缺失"
    assert "PW='p@ss'\\''word'" in sh, f"sh 密码转义错误: {sh[sh.find('PW='):sh.find(chr(10), sh.find('PW='))]}"
    print("[ok] sh multi-source + password")

    ps = generator.generate(app, plan, "backup", "ps1")
    assert '"C:/Users/foo/AppData/Roaming/App1",' in ps
    assert '"C:/Users/foo/.config/app2",' in ps
    print("[ok] ps1 multi-source array")

    bat = generator.generate(app, plan, "backup", "bat")
    assert 'robocopy "C:/Users/foo/AppData/Roaming/App1" "%DEST%\\%APP%_%TS%\\App1"' in bat
    assert 'robocopy "C:/Users/foo/.config/app2" "%DEST%\\%APP%_%TS%\\app2"' in bat
    print("[ok] bat multi-source robocopy block")

    # 单源保持原行为
    plan2 = BackupPlan(id="p2", name="p2", compress=False, format="zip", password="",
                       sources=["~/cfg"], destination="~/bk")
    sh2 = generator.generate(app, plan2, "backup", "sh")
    assert 'cp -a "~/cfg"' in sh2 or '"~/cfg"' in sh2
    print("[ok] single-source no-compress")

    print("SECURITY + SCRIPT SMOKE ALL PASS")


if __name__ == "__main__":
    main()
