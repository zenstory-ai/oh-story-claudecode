"""Publishing-preparation regressions; no host CLI, network or third-party packages."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/story-publish/scripts/check-publish-format.py"
spec = importlib.util.spec_from_file_location("publish_format", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


LONG = """> 格式版本：1
> 目标平台：番茄小说
> 作品类型：长篇
> 核验：2026-10-29；Web 创建作品弹窗

# 书本名称：春风：第2年

- 作者/笔名：江上清风
- 签约模式：完本模式
- 目标读者：男频
- 主角1：江晨
- 主角2：（不填）

## 封面

- 模式：仅提示词
- 状态：提示词已生成，图片未生成
- 提示词：
````text
## 画面构图
```text
山间春风
```
````
- 图片：

## 阅读标签

- 主分类：都市日常
- 主题：
- 角色：
- 情节：

## 内容标签

- 情节：
- 情感：
- 人设：皇叔
- 世界观：

## 作品简介

江晨穿越到平行世界，靠一部手机整顿军宣。

## 待作者确认

主题、角色、情节标签还没定。

## 待平台核实

无

## 来源说明

设定/题材定位.md；番茄长篇参考。
"""

SHORT = LONG.replace("> 作品类型：长篇", "> 作品类型：短故事").replace(
    "- 签约模式：完本模式\n- 目标读者：男频\n- 主角1：江晨\n- 主角2：（不填）",
    "- 是否使用AI：否\n- 试读比例：\n- 发布协议：",
)
SHORT = SHORT[:SHORT.index("## 阅读标签")] + """## 作品分类

- 主分类：婚姻家庭
- 情节：先婚后爱、重生
- 角色：白月光
- 情绪：甜宠
- 背景：现代

""" + SHORT[SHORT.index("## 作品简介"):]


def errors(text):
    return checker.check(text)[0]


def warnings(text):
    return checker.check(text)[1]


class ContractTests(unittest.TestCase):
    def test_valid_long_and_short(self):
        self.assertEqual(checker.check(LONG), ([], []))
        self.assertEqual(checker.check(SHORT), ([], []))

    def test_header_one_item_per_line_in_order(self):
        self.assertTrue(errors(LONG.replace("> 目标平台：番茄小说\n> 作品类型：长篇", "> 目标平台：番茄小说；作品类型：长篇")))
        self.assertTrue(errors(LONG.replace("> 格式版本：1\n", "")))
        self.assertTrue(errors(LONG.replace("> 格式版本：1", "> 格式版本：2")))

    def test_platform_and_work_type_select_rules(self):
        self.assertTrue(errors(LONG.replace("番茄小说", "起点中文网", 1)))
        self.assertTrue(errors(LONG.replace("> 作品类型：长篇", "> 作品类型：短故事")))

    def test_title_heading_first_and_may_be_pending(self):
        self.assertTrue(errors(LONG.replace("# 书本名称：春风：第2年", "# 番茄建书资料")))
        self.assertEqual(errors(LONG.replace("# 书本名称：春风：第2年", "# 书本名称：")), [])

    def test_placeholders_never_in_values(self):
        for before, after in (("- 主角1：江晨", "- 主角1：待作者确认"),
                              ("- 人设：皇叔", "- 人设：建议皇叔"),
                              ("# 书本名称：春风：第2年", "# 书本名称：待确认"),
                              ("江晨穿越到平行世界，靠一部手机整顿军宣。", "待作者确认")):
            with self.subTest(after=after):
                self.assertTrue(errors(LONG.replace(before, after)))

    def test_basics_order_and_choices(self):
        self.assertTrue(errors(LONG.replace("- 主角1：江晨\n", "")))
        self.assertTrue(errors(LONG.replace("签约模式：完本模式", "签约模式：日更")))
        self.assertEqual(errors(LONG.replace("签约模式：完本模式", "签约模式：")), [])

    def test_section_order_and_fenced_prompt_headings(self):
        self.assertTrue(errors(LONG.replace("## 封面", "## 来源说明", 1)))
        self.assertEqual(errors(LONG.replace("````text", "~~~~text").replace("````", "~~~~")), [])

    def test_field_lines(self):
        self.assertTrue(errors(LONG.replace("- 主题：\n- 角色：", "- 主题：国运；角色：全能")))
        self.assertTrue(errors(LONG.replace("- 世界观：", "- 世界观：军旅\n- 世界观：乡村")))
        self.assertTrue(errors(LONG.replace("- 图片：\n", "")))
        self.assertTrue(errors(LONG.replace("- 模式：仅提示词", "- 模式：直接生图")))


class PlatformRuleTests(unittest.TestCase):
    def test_reading_tags_follow_audience(self):
        self.assertTrue(errors(LONG.replace("主分类：都市日常", "主分类：豪门总裁")))  # 女频候选
        self.assertTrue(errors(LONG.replace("- 主题：", "- 主题：仕途、天灾、谍战")))
        self.assertTrue(errors(LONG.replace("目标读者：男频", "目标读者：")))

    def test_content_tags_candidates_and_limits(self):
        self.assertTrue(errors(LONG.replace("- 世界观：", "- 世界观：军旅、乡村")))
        self.assertTrue(errors(LONG.replace("人设：皇叔", "人设：现代")))

    def test_short_groups_and_total(self):
        self.assertTrue(errors(SHORT.replace("角色：白月光", "角色：现代")))
        self.assertTrue(errors(SHORT.replace("情绪：甜宠", "情绪：甜宠、甜宠")))
        eight = SHORT.replace("情节：先婚后爱、重生", "情节：先婚后爱、重生、穿越、暗恋")
        self.assertEqual(errors(eight), [])
        self.assertTrue(errors(eight.replace("背景：现代", "背景：现代、古代")))
        self.assertTrue(errors(SHORT.replace("是否使用AI：否", "是否使用AI：用了一点")))

    def test_platform_limits_warn_without_failing(self):
        for text in (LONG.replace("春风：第2年", "春风:归来"),
                     LONG.replace("春风：第2年", "春风……又一年"),
                     LONG.replace("春风：第2年", "春" * 16),
                     LONG.replace("主角1：江晨", "主角1：欧阳江晨之子"),
                     LONG.replace("江晨穿越到平行世界，靠一部手机整顿军宣。", "长" * 501),
                     SHORT.replace("春风：第2年", "春" * 26)):
            with self.subTest(text=text[90:130]):
                self.assertTrue(warnings(text))
                self.assertEqual(errors(text), [])
        self.assertEqual(warnings(SHORT.replace("春风：第2年", "春" * 20 + "abcdefghij")), [])

    def test_reference_candidates_and_limits(self):
        expected = {
            "fanqie-short.md": {"主分类": (24, None), "情节": (34, None), "角色": (26, None),
                                "情绪": (8, None), "背景": (10, None)},
            "fanqie-reading-male.md": {"主分类": (19, 1), "主题": (33, 2), "角色": (22, 2), "情节": (80, 2)},
            "fanqie-reading-female.md": {"主分类": (21, 1), "主题": (25, 2), "角色": (41, 2), "情节": (95, 2)},
            "fanqie-content-tags.md": {"情节": (144, 4), "情感": (58, 2), "人设": (94, 4), "世界观": (60, 1)},
        }
        for name, groups in expected.items():
            options = checker.load_options(name)
            self.assertEqual({key: (len(values), limit) for key, (values, limit) in options.items()}, groups, name)

    def test_no_bundled_images(self):
        # Evidence screenshots stay in docs/; skill copies are deployed into every project.
        self.assertEqual(list((ROOT / "skills/story-publish").rglob("*.png")), [])


class CliTests(unittest.TestCase):
    def test_unicode_path_readonly_and_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="publish check ") as directory:
            path = Path(directory) / "发布资料-番茄小说.md"
            path.write_text("﻿" + LONG.replace("春风：第2年", "春" * 16), encoding="utf-8")
            before = path.read_bytes()
            env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
            run = lambda: subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, env=env)
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            self.assertIn("WARN", result.stdout.decode("utf-8"))
            self.assertEqual(path.read_bytes(), before)
            path.write_text("# 错误格式", encoding="utf-8")
            self.assertEqual(run().returncode, 1)
            path.unlink()
            self.assertEqual(run().returncode, 1)


if __name__ == "__main__":
    unittest.main()
