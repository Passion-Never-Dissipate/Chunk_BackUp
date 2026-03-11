import json
import re
from typing import Any, List, Optional, Union

from mcdreforged.api.rtext import RStyle, RClickAction, RColor, RText, RTextList
from mcdreforged.minecraft.rtext.click_event import RClickSuggestCommand, RClickRunCommand, RClickOpenUrl
from mcdreforged.minecraft.rtext.hover_event import RHoverText
from mcdreforged.minecraft.rtext.text import RTextBase


class MessageFormatException(Exception):
    """自定义异常类，用于处理消息格式化错误"""
    pass


color_and_style_dict = {
    "§k": [RStyle.obfuscated, "style"],
    "§1": [RColor.dark_blue, "color"],
    "§l": [RStyle.bold, "style"],
    "§m": [RStyle.strikethrough, "style"],
    "§n": [RStyle.underlined, "style"],
    "§o": [RStyle.italic, "style"],
    "§0": [RColor.black, "color"],
    "§2": [RColor.dark_green, "color"],
    "§3": [RColor.dark_aqua, "color"],
    "§4": [RColor.dark_red, "color"],
    "§5": [RColor.dark_purple, "color"],
    "§6": [RColor.gold, "color"],
    "§7": [RColor.gray, "color"],
    "§8": [RColor.dark_gray, "color"],
    "§9": [RColor.blue, "color"],
    "§a": [RColor.green, "color"],
    "§b": [RColor.aqua, "color"],
    "§c": [RColor.red, "color"],
    "§d": [RColor.light_purple, "color"],
    "§e": [RColor.yellow, "color"],
    "§f": [RColor.white, "color"],
    "§r": [RColor.reset, "color"]
}

action_dict = {
    "ou": RClickAction.open_url,
    "rc": RClickAction.run_command,
    "sc": RClickAction.suggest_command,
    "cc": RClickAction.copy_to_clipboard,
    "of": RClickAction.open_file,
    "open_url": RClickAction.open_url,
    "run_command": RClickAction.run_command,
    "suggest_command": RClickAction.suggest_command,
    "copy_to_clipboard": RClickAction.copy_to_clipboard,
    "open_file": RClickAction.open_file
}


class Message:
    INVISIBLE__prefix = '¶†'

    @staticmethod
    def apply_styles(obj: RText, style_lst: list) -> None:
        """应用样式列表到RText对象"""
        if style_lst:
            obj.set_styles(style_lst)

    @staticmethod
    def apply_color_and_style_dict(node: str, obj: RText) -> None:
        """应用颜色和样式

        Args:
            node: 颜色/样式代码
            obj: RText对象
        """
        key = node.strip()

        if key in color_and_style_dict:
            value, node_type = color_and_style_dict[key]
            if node_type == "color":
                obj.set_color(value)
            elif node_type == "style":
                style_lst = [value]
                Message.apply_styles(obj, style_lst)

    @staticmethod
    def parse_value(value_str: str) -> Any:
        """解析值字符串，支持JSON格式的复杂值"""
        value_str = value_str.strip()

        # 尝试解析为JSON
        if (value_str.startswith('{') and value_str.endswith('}')) or \
                (value_str.startswith('[') and value_str.endswith(']')):
            try:
                return json.loads(value_str)
            except json.JSONDecodeError:
                pass

        # 尝试解析为布尔值
        if value_str.lower() == 'true':
            return True
        if value_str.lower() == 'false':
            return False

        # 尝试解析为数字
        try:
            if '.' in value_str:
                return float(value_str)
            else:
                return int(value_str)
        except ValueError:
            pass

        # 返回字符串，将\n转换为实际的换行符
        # 注意：在字符串中，\\n表示两个字符\和n，需要转换为换行符\n
        return value_str.replace('\\n', '\n')

    @staticmethod
    def apply_action_dict(node: str, obj: RText) -> None:
        """应用动作字典，支持多种点击事件类型

        Args:
            node: 动作节点字符串
            obj: RText对象
            : 是否解析颜色代码，默认为True
        """
        if '=' not in node:
            return

        try:
            key, value = node.split("=", 1)
            key = key.strip()
            value = Message.parse_value(value)

            if key in action_dict:
                # 创建对应的RClickEvent对象
                if key in ["sc", "suggest_command"]:
                    click_event = RClickSuggestCommand(str(value))
                elif key in ["rc", "run_command"]:
                    click_event = RClickRunCommand(str(value))
                elif key in ["ou", "open_url"]:
                    click_event = RClickOpenUrl(str(value))
                else:
                    # 默认使用action_dict中的动作
                    obj.set_click_event(action_dict[key], str(value))
                    return

                obj.set_click_event(click_event)

            elif key in ["st", "show_text"]:
                # 处理悬停文本
                if isinstance(value, dict):
                    # 如果是字典，直接创建RText
                    hover_text = RTextBase.from_json_object(value)
                else:
                    # 如果是字符串，直接创建RText对象
                    # 注意：这里我们不处理字符串中的颜色代码，它们会保留在文本中
                    hover_text = RText(str(value))

                obj.set_hover_event(RHoverText(text=hover_text))

        except Exception as e:
            raise MessageFormatException(f"Failed to parse action node '{node}': {str(e)}")

    @staticmethod
    def add_obj_list(code: List[str], text: List[str], obj_list: RTextList, flag: int) -> None:
        """添加对象列表

        Args:
            code: 代码列表
            text: 文本列表
            obj_list: RTextList对象
            flag: 标志
        """
        for i, (code_line, text_line) in enumerate(zip(code, text)):
            # 确定是否添加换行符
            if i == len(code) - 1 and flag > 1:
                obj = RText(text_line + "\n")
            else:
                obj = RText(text_line)

            # 解析代码行中的各个部分
            if code_line:
                for node in code_line.split("<>"):
                    node = node.strip()
                    if not node:
                        continue

                    # 检查是否是颜色/样式代码
                    if node in color_and_style_dict:
                        Message.apply_color_and_style_dict(node, obj)
                    elif "=" in node:
                        # 事件
                        Message.apply_action_dict(node, obj, )

            obj_list.append(obj)

    @classmethod
    def parse_single_line(cls, line: str, _prefix: str = INVISIBLE__prefix) -> RTextBase:
        """解析单行消息

        Args:
            line: 单行文本
            _prefix: 前缀
        """
        # 替换真正的换行符为占位符，防止正则表达式问题
        line_with_placeholder = line.replace('\n', '___NEWLINE___')

        # 提取所有代码段和文本段
        code_segments = re.findall(f"{re.escape(_prefix)}(.*?){re.escape(_prefix)}", line_with_placeholder, re.S)
        text_segments = [i for i in re.split(f"{re.escape(_prefix)}.*?{re.escape(_prefix)}", line_with_placeholder, re.S)
                         if i]

        # 恢复换行符
        text_segments = [seg.replace('___NEWLINE___', '\n') for seg in text_segments]

        if len(text_segments) == 0:
            return RText("")

        if len(code_segments) == 0:
            # 没有代码，只有纯文本
            return RText(line)

        # 构建RText对象
        result = RTextList()
        for i, text in enumerate(text_segments):
            text_obj = RText(text)

            if i < len(code_segments):
                code = code_segments[i]
                # 处理代码
                if code:
                    for node in code.split("<>"):
                        node = node.strip()
                        if not node:
                            continue

                        if node in color_and_style_dict:
                            cls.apply_color_and_style_dict(node, text_obj, )
                        elif "=" in node:
                            cls.apply_action_dict(node, text_obj, )

            result.append(text_obj)

        return result if len(result.children) > 1 else result.children[0] if result.children else RText("")

    @classmethod
    def get_json_str(cls, text: Union[str, RTextBase], _prefix: str = INVISIBLE__prefix) -> RTextList:
        """获取JSON字符串

        Args:
            text: 文本
            _prefix: 前缀
        """
        if not text:
            return RTextList()

        if isinstance(text, RTextBase):
            text = text.to_plain_text()

        obj_list = RTextList()
        lines = text.splitlines(keepends=True)  # 保持换行符

        for line in lines:
            # 检查是否以换行符结尾
            has_newline = line.endswith('\n')
            line = line.rstrip('\n')

            if not line.strip():
                # 空行
                if has_newline:
                    obj_list.append(RText("\n"))
                continue

            # 替换真正的换行符为占位符，防止正则表达式问题
            line_with_placeholder = line.replace('\n', '___NEWLINE___')

            # 提取代码和文本
            code = re.findall(f"{re.escape(_prefix)}(.*?){re.escape(_prefix)}", line_with_placeholder, re.S)
            text_segments = [i for i in
                             re.split(f"{re.escape(_prefix)}.*?{re.escape(_prefix)}", line_with_placeholder, re.S) if i]

            # 恢复换行符
            text_segments = [seg.replace('___NEWLINE___', '\n') for seg in text_segments]

            if len(text_segments) == 0:
                continue

            if len(code) == 0:
                # 纯文本行
                obj = RText(line)
                if has_newline:
                    obj = obj + "\n"
                obj_list.append(obj)
            elif len(text_segments) == len(code):
                # 代码和文本段数量相等
                for i, (code_line, text_line) in enumerate(zip(code, text_segments)):
                    obj = RText(text_line)

                    # 处理代码
                    if code_line:
                        for node in code_line.split("<>"):
                            node = node.strip()
                            if not node:
                                continue

                            if node in color_and_style_dict:
                                cls.apply_color_and_style_dict(node, obj, )
                            elif "=" in node:
                                cls.apply_action_dict(node, obj, )

                    # 如果是最后一个且需要换行
                    if i == len(code) - 1 and has_newline:
                        obj = obj + "\n"

                    obj_list.append(obj)
            else:
                # 其他情况，直接解析整行
                obj = cls.parse_single_line(line, _prefix, )
                if has_newline:
                    obj = obj + "\n"
                obj_list.append(obj)

        return obj_list

    @classmethod
    def merge_rtext_lists(cls, *args, separator: Optional[Union[str, RTextBase]] = "\n") -> RTextList:
        """
        将多个 RTextList 对象合并为一个 RTextList，保留原有样式，可选择插入分隔符。

        支持两种调用方式：
            1. merge_rtext_lists(r1, r2, r3, ..., separator=...)
            2. merge_rtext_lists([r1, r2, r3, ...], separator=...)

        Args:
            *args: 可变参数。可以是多个 RTextList 对象，也可以是一个包含 RTextList 的列表。
            separator: 可选的分隔符，可以是字符串或 RTextBase 对象。若为字符串，会自动转换为 RText。

        Returns:
            合并后的 RTextList 对象
        """
        # ----- 参数解析 -----
        if len(args) == 1 and isinstance(args[0], list):
            # 情况2：传入了一个列表
            rtext_lists = args[0]
        else:
            # 情况1：传入了多个独立参数
            rtext_lists = list(args)

        # ----- 空输入处理 -----
        if not rtext_lists:
            return RTextList()

        # ----- 准备分隔符对象 -----
        sep_obj = None
        if separator is not None:
            sep_obj = separator if isinstance(separator, RTextBase) else RText(separator)

        # ----- 合并 -----
        result = RTextList()
        result.header_empty = True  # 合并结果不以特殊样式开头

        for i, rtl in enumerate(rtext_lists):
            if not isinstance(rtl, RTextList):
                raise TypeError(f'Expected RTextList, got {type(rtl).__name__}')

            # 在非首个元素前插入分隔符
            if i > 0 and sep_obj is not None:
                # 若分隔符有 copy 方法则使用副本，防止后续修改影响
                result.children.append(sep_obj.copy() if hasattr(sep_obj, 'copy') else sep_obj)

            # 添加当前 RTextList 的所有内容
            if not rtl.header_empty:
                result.children.append(rtl.header)
            result.children.extend(rtl.children)

        return result

    @classmethod
    def get_multiline_json_str(cls, text_list: List[str], separator: str = "\n", _prefix: str = "#") -> RTextList:
        """
        将多个文本按顺序换行输出为JSON字符串

        Args:
            text_list: 文本字符串列表
            separator: 文本之间的分隔符，默认为换行符
            _prefix: 格式化前缀，默认为"#"
        """
        if not text_list:
            return RTextList()

        result = RTextList()

        for i, text in enumerate(text_list):
            # 解析当前文本
            parsed_text = cls.get_json_str(text, _prefix)

            # 将解析后的内容添加到结果中
            for child in parsed_text.children:
                result.append(child)

            # 如果不是最后一个文本，添加分隔符
            if i < len(text_list) - 1:
                if separator:
                    result.append(RText(separator))

        return result

    @classmethod
    def to_plain_text(cls, text: str, _prefix: str = INVISIBLE__prefix) -> str:
        """转换为纯文本（移除所有格式代码）"""
        return re.sub(f"{_prefix}.*?{_prefix}", "", text)

    @classmethod
    def to_minecraft_format(cls, text: str, _prefix: str = INVISIBLE__prefix) -> str:
        """转换为Minecraft格式代码（§格式）"""
        result = text

        # 替换颜色和样式代码
        for code, (value, node_type) in color_and_style_dict.items():
            if node_type == "color":
                result = re.sub(f"{_prefix}{re.escape(code)}{_prefix}", code, result)
            elif node_type == "style":
                result = re.sub(f"{_prefix}{re.escape(code)}{_prefix}", code, result)

        # 移除其他代码
        result = re.sub(f"{_prefix}[^#]*?{_prefix}", "", result)

        return result
