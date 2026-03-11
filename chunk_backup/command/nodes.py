from mcdreforged.command.builder.command_builder_utils import get_float, remove_divider_prefix
from mcdreforged.api.command import ArgumentNode, CommandSyntaxError, ParseResult


class InvalidCoordinate(CommandSyntaxError):
    """当输入的不是合法数字时抛出"""

    def __init__(self, char_read: int):
        super().__init__('Invalid coordinate number', char_read)


class IncompleteCoordinate(CommandSyntaxError):
    """当坐标数量不足时抛出"""

    def __init__(self, char_read: int):
        super().__init__('Incomplete coordinate', char_read)


class IncompleteIntegerList(CommandSyntaxError):
    """输入为空（缺少参数）时抛出"""

    def __init__(self, char_read: int):
        super().__init__('Incomplete integer list, expected at least one number', char_read)


class InvalidIntegerList(CommandSyntaxError):
    """遇到非数字、非逗号、非负号的非法字符，或数字格式错误时抛出"""

    def __init__(self, char_read: int):
        super().__init__('Invalid character or format in integer list', char_read)


class EmptyInteger(CommandSyntaxError):
    """出现连续逗号（空值）时抛出"""

    def __init__(self, char_read: int):
        super().__init__('Empty value between delimiters', char_read)


class TrailingComma(CommandSyntaxError):
    """输入以逗号结尾时抛出"""

    def __init__(self, char_read: int):
        super().__init__('Trailing comma at the end', char_read)


# --- 二维坐标节点 (x, z) ---
class Position2D(ArgumentNode):
    """
    一个用于解析 Minecraft 二维坐标 (x, z) 的参数节点。
    它接受两个连续的浮点数作为输入。
    """

    def __init__(self, name: str):
        super().__init__(name)
        self.__number = 2  # 坐标数量：2个

    def parse(self, text: str) -> ParseResult:
        """
        解析输入文本，尝试读取两个浮点数作为坐标。
        """
        total_read = 0
        coords = []

        for i in range(self.__number):
            # 1. 跳过可能存在的空格（DIVIDER）
            #    使用 remove_divider_prefix 来获取去掉开头空格后的文本及其长度
            stripped_text = text[total_read:]
            prefix_len = len(stripped_text) - len(remove_divider_prefix(stripped_text))
            total_read += prefix_len

            # 2. 尝试从当前位置解析一个浮点数
            value, read = get_float(text[total_read:])

            # 3. 处理解析结果
            if read == 0:  # 没有读取到任何字符，说明数字不完整或缺失
                raise IncompleteCoordinate(total_read)

            if value is None:  # 读取到了字符但不是合法浮点数
                # 注意：char_read 应该指向错误发生的位置
                raise InvalidCoordinate(total_read + 1)  # +1 是因为错误发生在当前读取的开头

            # 4. 成功解析到一个浮点数，累加读取长度并保存值
            total_read += read
            coords.append(value)

        # 5. 成功读取到两个浮点数，返回结果
        return ParseResult(coords, total_read)


# --- 三维坐标节点 (x, y, z) ---
class Position3D(ArgumentNode):
    """
    一个用于解析 Minecraft 三维坐标 (x, y, z) 的参数节点。
    它接受三个连续的浮点数作为输入。
    """

    def __init__(self, name: str):
        super().__init__(name)
        self.__number = 3  # 坐标数量：3个

    def parse(self, text: str) -> ParseResult:
        """
        解析输入文本，尝试读取三个浮点数作为坐标。
        """
        total_read = 0
        coords = []

        for i in range(self.__number):
            # 1. 跳过可能存在的空格
            stripped_text = text[total_read:]
            prefix_len = len(stripped_text) - len(remove_divider_prefix(stripped_text))
            total_read += prefix_len

            # 2. 尝试解析一个浮点数
            value, read = get_float(text[total_read:])

            # 3. 处理解析结果
            if read == 0:
                raise IncompleteCoordinate(total_read)
            if value is None:
                raise InvalidCoordinate(total_read + 1)

            # 4. 累加读取长度并保存值
            total_read += read
            coords.append(value)

        # 5. 成功读取到三个浮点数，返回结果
        return ParseResult(coords, total_read)


class IntegerList(ArgumentNode):
    """
    解析一个由逗号分隔的整数列表。
    - 支持英文逗号 ',' 和中文逗号 '，'，可混用。
    - 支持负整数（负号 '-' 必须紧跟在逗号后或开头）。
    - 不允许出现空格，但空格作为命令参数分隔符时，会截断解析并返回已解析部分。
    - 不允许以逗号结尾。
    - 不允许连续逗号（即空元素）。
    - 解析完成后自动去除重复整数，并保留首次出现的顺序。
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.delimiters = {',', '，'}

    def parse(self, text: str) -> ParseResult:
        if not text:
            raise IncompleteIntegerList(0)

        values = []
        current_chars = []

        for i, ch in enumerate(text):
            if ch.isdigit():
                current_chars.append(ch)
            elif ch == '-':
                if current_chars:
                    raise InvalidIntegerList(i)  # 负号只能出现在数字开头
                current_chars.append(ch)
            elif ch in self.delimiters:
                if not current_chars:
                    raise EmptyInteger(i)        # 逗号前无数字
                # 完成当前数字
                try:
                    num_str = ''.join(current_chars)
                    values.append(int(num_str))
                except ValueError:
                    raise InvalidIntegerList(i)
                current_chars = []
            elif ch == ' ':
                # 遇到空格：先完成当前数字（如果有）
                if current_chars:
                    try:
                        num_str = ''.join(current_chars)
                        values.append(int(num_str))
                    except ValueError:
                        raise InvalidIntegerList(i)
                    current_chars = []
                else:
                    # 没有累积数字，检查是否在合法位置
                    if not values:
                        raise InvalidIntegerList(i)  # 开头空格
                    if i > 0 and text[i-1] in self.delimiters:
                        raise EmptyInteger(i)        # 逗号后直接空格
                # 去重并返回
                seen = set()
                unique_values = []
                for v in values:
                    if v not in seen:
                        seen.add(v)
                        unique_values.append(v)
                return ParseResult(unique_values, i)  # 已解析长度不包括空格
            else:
                raise InvalidIntegerList(i)           # 非法字符

        # 遍历完所有字符（未遇到空格）
        if not current_chars:
            raise TrailingComma(i)                     # 最后是逗号
        try:
            num_str = ''.join(current_chars)
            values.append(int(num_str))
        except ValueError:
            raise InvalidIntegerList(i)

        # 去重
        seen = set()
        unique_values = []
        for v in values:
            if v not in seen:
                seen.add(v)
                unique_values.append(v)
        return ParseResult(unique_values, len(text))


class IntegerRangeList(ArgumentNode):
    """
    解析一个正整数范围列表，数字最小为 1。
    支持格式：
    - 单个数字：1
    - 逗号分隔的数字：1,2,3（支持中英文逗号）
    - 范围：1-5 或 5-1（自动转为 1~5）
    - 逗号分隔的范围：1-5,10-20
    - 混合：1,2-4,5
    遇到空格时，根据是否有后续子节点决定合法性：
    - 如果有子节点，空格作为分隔符，截断返回已解析部分。
    - 如果没有子节点，空格非法，抛出异常。
    最终整数列表去重并升序排序。
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.delimiters = {',', '，'}

    def _validate_positive(self, num: int, pos: int):
        if num < 1:
            raise CommandSyntaxError(f'Number must be >= 1, got {num}', pos)

    def parse(self, text: str) -> ParseResult:
        if not text:
            raise IncompleteIntegerList(0)

        values = []
        current_chars = []
        in_range = False
        range_start = 0

        for i, ch in enumerate(text):
            if ch.isdigit():
                current_chars.append(ch)
            elif ch == '-':
                if in_range:
                    raise CommandSyntaxError('Unexpected "-"', i)
                if not current_chars:
                    raise CommandSyntaxError('Range start missing', i)
                try:
                    range_start = int(''.join(current_chars))
                except ValueError:
                    raise CommandSyntaxError('Invalid number', i)
                self._validate_positive(range_start, i)
                in_range = True
                current_chars = []
            elif ch in self.delimiters:
                # 遇到逗号：先完成当前正在处理的元素
                if in_range:
                    if not current_chars:
                        raise CommandSyntaxError('Incomplete range at delimiter', i)
                    try:
                        end = int(''.join(current_chars))
                    except ValueError:
                        raise CommandSyntaxError('Invalid number', i)
                    self._validate_positive(end, i)
                    low = min(range_start, end)
                    high = max(range_start, end)
                    for num in range(low, high + 1):
                        values.append(num)
                    in_range = False
                    current_chars = []
                else:
                    if not current_chars:
                        raise EmptyInteger(i)  # 连续逗号
                    try:
                        num = int(''.join(current_chars))
                    except ValueError:
                        raise CommandSyntaxError('Invalid number', i)
                    self._validate_positive(num, i)
                    values.append(num)
                    current_chars = []
                # 逗号本身不添加任何东西，继续循环
            elif ch == ' ':
                # 遇到空格：先完成当前正在处理的元素
                if in_range:
                    if not current_chars:
                        raise CommandSyntaxError('Incomplete range at space', i)
                    try:
                        end = int(''.join(current_chars))
                    except ValueError:
                        raise CommandSyntaxError('Invalid number', i)
                    self._validate_positive(end, i)
                    low = min(range_start, end)
                    high = max(range_start, end)
                    for num in range(low, high + 1):
                        values.append(num)
                    in_range = False
                    current_chars = []
                else:
                    if current_chars:
                        try:
                            num = int(''.join(current_chars))
                        except ValueError:
                            raise CommandSyntaxError('Invalid number', i)
                        self._validate_positive(num, i)
                        values.append(num)
                        current_chars = []
                    else:
                        # 没有累积数字：检查非法空格位置
                        if i == 0:
                            raise CommandSyntaxError('Unexpected space at beginning', i)
                        if text[i-1] in self.delimiters:
                            raise EmptyInteger(i)
                        raise CommandSyntaxError('Unexpected space', i)

                # 根据是否有后续子节点决定空格是否合法
                if not self.has_children():
                    raise CommandSyntaxError('Unexpected trailing space (no more arguments expected)', i)

                # 去重并排序后返回
                seen = set()
                unique = []
                for v in values:
                    if v not in seen:
                        seen.add(v)
                        unique.append(v)
                unique.sort()
                return ParseResult(unique, i)
            else:
                raise CommandSyntaxError(f'Illegal character "{ch}"', i)

        # 遍历完所有字符（未遇到空格）
        if in_range:
            if not current_chars:
                raise CommandSyntaxError('Incomplete range at end', len(text))
            try:
                end = int(''.join(current_chars))
            except ValueError:
                raise CommandSyntaxError('Invalid number', len(text))
            self._validate_positive(end, len(text))
            low = min(range_start, end)
            high = max(range_start, end)
            for num in range(low, high + 1):
                values.append(num)
        else:
            if current_chars:
                try:
                    num = int(''.join(current_chars))
                except ValueError:
                    raise CommandSyntaxError('Invalid number', len(text))
                self._validate_positive(num, len(text))
                values.append(num)
            else:
                if text and text[-1] in self.delimiters:
                    raise TrailingComma(len(text) - 1)

        seen = set()
        unique = []
        for v in values:
            if v not in seen:
                seen.add(v)
                unique.append(v)
        unique.sort()
        return ParseResult(unique, len(text))