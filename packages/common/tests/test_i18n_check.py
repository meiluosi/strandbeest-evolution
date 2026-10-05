"""E1-01: the CJK-literal checker passes on the repo and catches a deliberately added literal."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("check_cjk", ROOT / "scripts" / "check_no_hardcoded_cjk.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def make_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / "apps/web-demo/src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_repository_is_clean():
    assert check.main(["--root", str(ROOT)]) == 0


def test_catches_markup_attribute_and_script_literals(tmp_path):
    root = make_tree(
        tmp_path,
        {
            "A.svelte": '<script lang="ts">const a = "你好";</script>\n<p>文本</p>\n<input title="提示" />',
            "b.ts": "export const x = `模板 ${1}`;",
        },
    )
    assert len(check.scan(root, {})) == 4


def test_ignores_comments_and_honours_allowlist(tmp_path):
    root = make_tree(
        tmp_path,
        {
            "A.svelte": "<!-- 注释 -->\n<script>\n// 行注释\n/* 块注释 */\nconst u = 'http://x';\n</script>",
            "core.ts": 'export const n = "中文";',
            "t.test.ts": 'const z = "任意";',
        },
    )
    allow = {"files": ["apps/web-demo/src/t.test.ts"], "strings": {"apps/web-demo/src/core.ts": ["中文"]}}
    assert check.scan(root, allow) == []
    # same literal in a file that is not allow-listed is reported with its line number
    (root / "apps/web-demo/src/c.ts").write_text('\n\nexport const n = "中文";', encoding="utf-8")
    assert check.scan(root, allow) == ["apps/web-demo/src/c.ts:3: hard-coded CJK literal '中文'"]


def test_allowlist_file_is_valid_json():
    data = json.loads((ROOT / "scripts" / "i18n-allowlist.json").read_text())
    assert set(data) >= {"files", "strings"}
