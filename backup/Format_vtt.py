import re

def process_vtt_file(input_file, output_file):
    # 读取文件内容
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 把文件按照空行分隔为字幕块
    blocks = content.split('\n\n')
    processed_blocks = []
    
    # 跳过WEBVTT块（不保留）
    if blocks and blocks[0].strip().startswith('WEBVTT'):
        blocks = blocks[1:]  # 跳过WEBVTT块
    
    i = 0
    while i < len(blocks):
        block = blocks[i].strip()
        lines = block.split('\n')
        
        # 检查是否为有效的字幕块（至少包含时间行和文本行）
        timestamp_pattern = r'^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}$'
        
        # 情况1: 如果块不包含时间戳行，则跳过
        if not any(re.match(timestamp_pattern, line) for line in lines):
            i += 1
            continue
        
        # 情况2: 如果时间戳行后面有空行，再跟文本行，则跳过整个块
        has_empty_line = False
        for j in range(len(lines)):
            if re.match(timestamp_pattern, lines[j]):
                if j + 1 < len(lines) and lines[j + 1].strip() == '':
                    has_empty_line = True
                    break
        
        if has_empty_line:
            i += 1
            continue
        
        # 情况3: 如果时间戳行后面没有文本行，跳过该块
        has_text = False
        for j in range(len(lines)):
            if re.match(timestamp_pattern, lines[j]):
                if j + 1 < len(lines) and lines[j + 1].strip() != '':
                    has_text = True
                    break
        
        if not has_text:
            i += 1
            continue
            
        # 保存当前有效块以备后续检查重复文本
        processed_blocks.append(block)
        i += 1
    
    # 处理连续多行内容相同的情况（合并）
    final_blocks = []
    i = 0
    
    while i < len(processed_blocks):
        current_block = processed_blocks[i]
        current_lines = current_block.strip().split('\n')
        
        # 提取时间戳和文本
        timestamp_pattern = r'^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}$'
        if len(current_lines) >= 2:
            # 找到时间戳行的索引
            timestamp_idx = -1
            for j, line in enumerate(current_lines):
                if re.match(timestamp_pattern, line):
                    timestamp_idx = j
                    break
                    
            if timestamp_idx != -1:
                timestamp_line = current_lines[timestamp_idx]
                start_time = timestamp_line.split(' --> ')[0]
                # 获取时间戳后的所有文本行
                text_content = '\n'.join(current_lines[timestamp_idx+1:])
                
                # 查找连续的相同内容块
                j = i + 1
                while j < len(processed_blocks):
                    next_block = processed_blocks[j]
                    next_lines = next_block.strip().split('\n')
                    
                    # 找到下一个块的时间戳行
                    next_timestamp_idx = -1
                    for k, line in enumerate(next_lines):
                        if re.match(timestamp_pattern, line):
                            next_timestamp_idx = k
                            break
                            
                    if next_timestamp_idx != -1:
                        next_text = '\n'.join(next_lines[next_timestamp_idx+1:])
                        
                        # 如果文本内容相同，合并时间戳
                        if next_text == text_content:
                            end_time = next_lines[next_timestamp_idx].split(' --> ')[1]
                            j += 1
                        else:
                            break
                    else:
                        break
                
                if j > i + 1:  # 有需要合并的块
                    end_time = None
                    for k in range(j-1, i, -1):
                        next_lines = processed_blocks[k].strip().split('\n')
                        for line in next_lines:
                            if re.match(timestamp_pattern, line):
                                end_time = line.split(' --> ')[1]
                                break
                        if end_time:
                            break
                    
                    if end_time:
                        merged_block = f"{start_time} --> {end_time}\n{text_content}"
                        final_blocks.append(merged_block)
                    else:
                        final_blocks.append(current_block)
                    i = j
                else:
                    final_blocks.append(current_block)
                    i += 1
            else:
                final_blocks.append(current_block)
                i += 1
        else:
            final_blocks.append(current_block)
            i += 1
    
    # 调整时间戳，确保当前块的开始时间不早于前一个块的结束时间
    adjusted_blocks = []
    prev_end_time = None
    
    for block in final_blocks:
        lines = block.strip().split('\n')
        timestamp_pattern = r'^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}$'
        
        # 找到时间戳行
        timestamp_line = None
        timestamp_index = -1
        for i, line in enumerate(lines):
            if re.match(timestamp_pattern, line):
                timestamp_line = line
                timestamp_index = i
                break
        
        if timestamp_line and timestamp_index != -1:
            times = timestamp_line.split(' --> ')
            start_time = times[0]
            end_time = times[1]
            
            # 检查当前开始时间是否早于前一个结束时间
            if prev_end_time and is_time_earlier(start_time, prev_end_time):
                # 将当前开始时间设置为前一个结束时间加1毫秒
                new_start_time = add_millisecond(prev_end_time)
                new_timestamp = f"{new_start_time} --> {end_time}"
                lines[timestamp_index] = new_timestamp
                
                # 如果新的开始时间晚于结束时间，将结束时间也调整
                if is_time_earlier(end_time, new_start_time):
                    lines[timestamp_index] = f"{new_start_time} --> {new_start_time}"
            
            prev_end_time = end_time
        
        adjusted_blocks.append('\n'.join(lines))
    
    # 添加编号并替换小数点为逗号
    numbered_blocks = []
    counter = 1
    
    for block in adjusted_blocks:
        lines = block.strip().split('\n')
        # 替换时间戳中的小数点为逗号
        for i, line in enumerate(lines):
            timestamp_pattern = r'^\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}$'
            if re.match(timestamp_pattern, line):
                lines[i] = line.replace('.', ',')
        
        numbered_block = f"{counter}\n{'\n'.join(lines)}"
        numbered_blocks.append(numbered_block)
        counter += 1
    
    # 写入处理后的内容到输出文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(numbered_blocks))

# 检查时间t1是否早于t2
def is_time_earlier(t1, t2):
    t1_parts = t1.split(':')
    t2_parts = t2.split(':')
    
    # 转换为总毫秒数
    t1_ms = (int(t1_parts[0]) * 3600 + int(t1_parts[1]) * 60 + float(t1_parts[2])) * 1000
    t2_ms = (int(t2_parts[0]) * 3600 + int(t2_parts[1]) * 60 + float(t2_parts[2])) * 1000
    
    return t1_ms < t2_ms

# 向时间添加1毫秒
def add_millisecond(time_str):
    hours, minutes, seconds = time_str.split(':')
    
    # 将字符串转换为数字
    hours_int = int(hours)
    minutes_int = int(minutes)
    seconds_float = float(seconds)
    
    # 增加1毫秒(0.001秒)
    seconds_float += 0.001
    
    # 处理进位
    if seconds_float >= 60:
        seconds_float -= 60
        minutes_int += 1
        if minutes_int >= 60:
            minutes_int -= 60
            hours_int += 1
    
    # 格式化时间并确保毫秒部分有3位
    formatted_seconds = f"{seconds_float:.3f}"
    if len(formatted_seconds.split('.')[0]) == 1:
        formatted_seconds = f"0{formatted_seconds}"
    
    return f"{hours_int:02d}:{minutes_int:02d}:{formatted_seconds}"

# 用法示例
input_file = '/Users/yanzhang/Downloads/backup/local_video/output/transcript.vtt'
output_file = '/Users/yanzhang/Downloads/transcript.srt'
process_vtt_file(input_file, output_file)