#!/usr/bin/env python3
"""
扫描并移除元数据损坏的 dist-info，解决 pip install 时 version=None 导致的 TypeError。
"""
import os
import re
import sys

def get_site_packages():
    import site
    return site.getsitepackages()

def check_dist_info(dist_info_path):
    """检查 dist-info 的 METADATA 是否有效，返回 (is_valid, package_name)"""
    metadata_path = os.path.join(dist_info_path, "METADATA")
    if not os.path.exists(metadata_path):
        return False, os.path.basename(dist_info_path)
    try:
        with open(metadata_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        # 检查 Version 字段
        version_match = re.search(r"^Version:\s*(.+)$", content, re.MULTILINE)
        if not version_match:
            return False, os.path.basename(dist_info_path)
        version = version_match.group(1).strip()
        if not version or version == "None":
            return False, os.path.basename(dist_info_path)
        # 检查 Name 字段
        name_match = re.search(r"^Name:\s*(.+)$", content, re.MULTILINE)
        if not name_match or not name_match.group(1).strip():
            return False, os.path.basename(dist_info_path)
        return True, name_match.group(1).strip()
    except Exception:
        return False, os.path.basename(dist_info_path)

def main():
    sp_dirs = get_site_packages()
    removed = []
    for sp in sp_dirs:
        if not os.path.exists(sp):
            continue
        for name in os.listdir(sp):
            if name.endswith(".dist-info") and "-" in name:
                path = os.path.join(sp, name)
                if not os.path.isdir(path):
                    continue
                valid, pkg = check_dist_info(path)
                if not valid:
                    try:
                        import shutil
                        shutil.rmtree(path)
                        removed.append(name)
                        print(f"Removed: {path}")
                    except Exception as e:
                        print(f"Failed to remove {path}: {e}", file=sys.stderr)
    if removed:
        print(f"\nRemoved {len(removed)} corrupted dist-info: {removed}")
        print("Now run: pip install -r requirements.txt")
    else:
        print("No corrupted metadata found.")

if __name__ == "__main__":
    main()
